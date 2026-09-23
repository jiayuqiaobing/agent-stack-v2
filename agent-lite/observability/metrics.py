"""metrics.py — 从 span JSONL 聚合出可读指标

实现 docs/3-可观测数据模型.md 第 8 节的 `GET /metrics` 契约。

设计要点：
- **聚合在读取时计算**，写入时零开销（trace.export_span 只管追加一行）
- 只读，不改任何既有接口
- 数据源就是 trace.py 写的 JSONL，不引入数据库
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from observability import trace

logger = logging.getLogger(__name__)

# 允许的时间窗口
WINDOW_HOURS = {"1h": 1, "6h": 6, "24h": 24, "7d": 24 * 7}
DEFAULT_WINDOW = "24h"


def _percentile(sorted_values: list[float], p: float) -> float:
    """线性插值法求分位点（P 为 0~1）"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = p * (len(sorted_values) - 1)
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    frac = pos - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


def load_spans(window: str = DEFAULT_WINDOW) -> list[dict]:
    """读取时间窗口内的全部 span

    逐日读取 spans-YYYY-MM-DD.jsonl。读不动的行直接跳过（日志文件可能因为
    进程被杀而留下半行）—— 可观测数据不该因为一行坏数据就整体不可用。
    """
    hours = WINDOW_HOURS.get(window, 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    spans: list[dict] = []
    today = datetime.now()
    days = {today - timedelta(days=i) for i in range((hours // 24) + 1)}

    for day in sorted(days):
        path = trace._daily_log_path(day.strftime("%Y-%m-%d"))
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        span = json.loads(line)
                    except json.JSONDecodeError:
                        continue        # 坏行跳过，不影响整体
                    if span.get("start_time", 0) >= cutoff.timestamp():
                        spans.append(span)
        except OSError:
            logger.warning("读取 span 文件失败：%s", path, exc_info=True)

    return spans


def _empty_report(window: str) -> dict:
    """没有数据时的骨架 —— 字段齐全，值全为 0，便于调用方统一处理"""
    return {
        "window": window,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spans": 0,
        "requests": {"total": 0, "ok": 0, "error": 0, "error_rate": 0.0},
        "latency_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
        "llm": {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "cache_hit_tokens": 0, "cache_hit_rate": 0.0,
        },
        "tools": {"calls": 0, "success_rate": 0.0, "by_name": {}},
        "rag": {"searches": 0, "avg_hit_count": 0.0, "degraded_count": 0},
        "memory": {"summarize_calls": 0},
        "hints": [],
    }


def build_report(window: str = DEFAULT_WINDOW, spans: Iterable[dict] | None = None) -> dict:
    """把 span 列表聚合成 /metrics 的返回结构"""
    if spans is None:
        spans = load_spans(window)
    spans = list(spans)

    if not spans:
        return _empty_report(window)

    report = _empty_report(window)
    report["spans"] = len(spans)

    # ---- 延迟与错误率：以根 span（kind=agent，parent 为 null）为准 ----
    agent_spans = [s for s in spans if s.get("kind") == "agent"]
    durations = sorted(
        s["duration_ms"] for s in agent_spans
        if isinstance(s.get("duration_ms"), (int, float))
    )
    if durations:
        report["latency_ms"] = {
            "p50": round(_percentile(durations, 0.50), 1),
            "p95": round(_percentile(durations, 0.95), 1),
            "p99": round(_percentile(durations, 0.99), 1),
        }
        total = len(durations)
        errors = sum(1 for s in agent_spans if s.get("status") == "error")
        report["requests"] = {
            "total": total,
            "ok": total - errors,
            "error": errors,
            "error_rate": round(errors / total, 4) if total else 0.0,
        }

    # ---- LLM ----（缓存命中率是本项目的关键指标：验证前缀缓存设计是否生效）
    llm_spans = [s for s in spans if s.get("kind") == "llm"]
    if llm_spans:
        prompt_tokens = sum(int(s["attributes"].get("prompt_tokens", 0)) for s in llm_spans)
        completion_tokens = sum(int(s["attributes"].get("completion_tokens", 0)) for s in llm_spans)
        cache_tokens = sum(int(s["attributes"].get("cache_hit_tokens", 0)) for s in llm_spans)
        report["llm"] = {
            "calls": len(llm_spans),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache_hit_tokens": cache_tokens,
            "cache_hit_rate": round(cache_tokens / prompt_tokens, 4) if prompt_tokens else 0.0,
        }

    # ---- 工具 ----（name 冗余在 attributes.tool_name，便于按名聚合）
    tool_spans = [s for s in spans if s.get("kind") == "tool"]
    if tool_spans:
        by_name: dict[str, int] = {}
        for s in tool_spans:
            name = s["attributes"].get("tool_name") or s.get("name", "unknown")
            by_name[name] = by_name.get(name, 0) + 1
        ok = sum(1 for s in tool_spans if s["attributes"].get("success"))
        report["tools"] = {
            "calls": len(tool_spans),
            "success_rate": round(ok / len(tool_spans), 4),
            "by_name": dict(sorted(by_name.items(), key=lambda kv: -kv[1])),
        }

    # ---- RAG ----
    rag_spans = [s for s in spans if s.get("kind") == "rag"]
    if rag_spans:
        searches = [s for s in rag_spans if s.get("name") == "rag.search"]
        hits = [int(s["attributes"].get("hit_count", 0)) for s in searches]
        report["rag"] = {
            "searches": len(searches),
            "avg_hit_count": round(sum(hits) / len(hits), 2) if hits else 0.0,
            "degraded_count": sum(1 for s in rag_spans if s["attributes"].get("degraded")),
        }

    # ---- 记忆 ----
    report["memory"] = {
        "summarize_calls": sum(1 for s in spans if s.get("name") == "memory.summarize"),
    }

    # ---- 提示：把"需要人注意"的信号直接写进响应 ----
    hints: list[str] = []
    rate = report["llm"]["cache_hit_rate"]
    if report["llm"]["calls"] >= 10 and rate < 0.5:
        hints.append(
            f"缓存命中率 {rate:.1%} 偏低（<50%）—— v1 的 system prompt 前置设计可能已失效，"
            f"输入成本会显著上升"
        )
    if report["requests"]["total"] and report["requests"]["error_rate"] > 0.1:
        hints.append(f"错误率 {report['requests']['error_rate']:.1%} 偏高（>10%）")
    if report["rag"]["degraded_count"] > 0:
        hints.append(
            f"RAG 降级 {report['rag']['degraded_count']} 次 —— embedding 可能又出问题了"
            f"（v1 曾静默失效过）"
        )
    if report["tools"]["calls"] and report["tools"]["success_rate"] < 0.9:
        hints.append(f"工具成功率 {report['tools']['success_rate']:.1%} 偏低（<90%）")

    report["hints"] = hints
    return report
