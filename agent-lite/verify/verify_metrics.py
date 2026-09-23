"""verify_metrics.py — 指标聚合的独立验证

用**合成 span** 验证聚合逻辑，不依赖真实模型调用。
验收 docs/3-可观测数据模型.md 第 8 节的 /metrics 契约。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from observability import metrics, trace as T

results = []


def check(label, got, want):
    ok = got == want
    results.append(ok)
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + ("" if ok else f"   期望 {want!r}，实际 {got!r}"))


def mk(kind, name, dur, status="ok", attrs=None, parent=None):
    s = T.make_span(name, kind, attributes=attrs or {})
    s["parent_span_id"] = parent
    s["duration_ms"] = dur
    s["status"] = status
    s["end_time"] = s["start_time"] + dur / 1000
    return s


# ---------------------------------------------------------------- 空数据
empty = metrics.build_report("24h", spans=[])
check("空数据不崩，返回骨架", empty["requests"]["total"], 0)
check("空数据字段齐全", set(empty.keys()) >= {"window", "requests", "latency_ms", "llm", "tools", "rag", "hints"}, True)
check("空数据无提示", empty["hints"], [])

# ---------------------------------------------------------------- 正常聚合
spans = []

# 4 次根请求：3 成功 1 失败，延迟 100/200/300/400
for i, (dur, st) in enumerate([(100, "ok"), (200, "ok"), (300, "ok"), (400, "error")]):
    spans.append(mk("agent", "agent.turn", dur, status=st))

# 3 次 llm 调用：prompt 1000/1000/1000，completion 100，cache 800/600/0
for cache in (800, 600, 0):
    spans.append(mk("llm", "llm.chat", 50, attrs={
        "model": "test", "prompt_tokens": 1000, "completion_tokens": 100,
        "cache_hit_tokens": cache, "has_tool_calls": True,
    }))

# 4 次工具调用：3 成功 1 失败
for i, ok_flag in enumerate([True, True, True, False]):
    spans.append(mk("tool", "tool.calculate", 5, status="ok" if ok_flag else "error",
                    attrs={"tool_name": "calculate" if i < 3 else "weather",
                           "success": ok_flag, "source": "local"}))

# 2 次 RAG 检索：命中 2 和 4，其中 1 次降级
spans.append(mk("rag", "rag.search", 30, attrs={"k": 5, "hit_count": 2, "degraded": False}))
spans.append(mk("rag", "rag.search", 40, attrs={"k": 5, "hit_count": 4, "degraded": True}))

# 1 次记忆压缩
spans.append(mk("memory", "memory.summarize", 900, attrs={"before_count": 20, "after_count": 6}))

r = metrics.build_report("24h", spans=spans)

check("span 总数", r["spans"], len(spans))
check("请求数", r["requests"]["total"], 4)
check("成功数", r["requests"]["ok"], 3)
check("错误数", r["requests"]["error"], 1)
check("错误率", r["requests"]["error_rate"], 0.25)

# 分位数（4 个样本，线性插值）
check("P50", r["latency_ms"]["p50"], 250.0)
check("P95", r["latency_ms"]["p95"], 385.0)
check("P99", r["latency_ms"]["p99"], 397.0)

check("LLM 调用数", r["llm"]["calls"], 3)
check("prompt tokens 合计", r["llm"]["prompt_tokens"], 3000)
check("completion tokens 合计", r["llm"]["completion_tokens"], 300)
check("cache 命中 token 合计", r["llm"]["cache_hit_tokens"], 1400)
check("缓存命中率", r["llm"]["cache_hit_rate"], round(1400 / 3000, 4))

check("工具调用数", r["tools"]["calls"], 4)
check("工具成功率", r["tools"]["success_rate"], 0.75)
check("按名统计 calculate", r["tools"]["by_name"].get("calculate"), 3)
check("按名统计 weather", r["tools"]["by_name"].get("weather"), 1)

check("RAG 检索次数", r["rag"]["searches"], 2)
check("RAG 平均命中", r["rag"]["avg_hit_count"], 3.0)
check("RAG 降级次数", r["rag"]["degraded_count"], 1)
check("记忆压缩次数", r["memory"]["summarize_calls"], 1)

# ---------------------------------------------------------------- 提示规则
# 缓存命中率 46.7% < 50% 且 llm 调用数 < 10 → 不该提示（避免样本太小时误报）
hint_cache_small = [h for h in r["hints"] if "缓存命中率" in h]
check("LLM 调用数 < 10 时不触发缓存提示", len(hint_cache_small), 0)

# 工具成功率 75% < 90% → 应有提示
check("工具成功率低时给出提示", any("工具成功率" in h for h in r["hints"]), True)
# RAG 降级 > 0 → 应有提示
check("RAG 降级时给出提示", any("RAG 降级" in h for h in r["hints"]), True)
# 错误率 25% > 10% → 应有提示
check("错误率高时给出提示", any("错误率" in h for h in r["hints"]), True)

# ---------------------------------------------------------------- 缓存提示的大样本场景
many_llm = []
for _ in range(12):
    many_llm.append(mk("llm", "llm.chat", 10, attrs={
        "prompt_tokens": 1000, "completion_tokens": 10, "cache_hit_tokens": 100,
    }))
r2 = metrics.build_report("24h", spans=many_llm)
check("LLM 调用 >= 10 且命中率低 → 触发缓存提示",
      any("缓存命中率" in h for h in r2["hints"]), True)

# ---------------------------------------------------------------- 坏数据容错
check("坏 span（缺 duration）不崩", metrics.build_report("24h", spans=[{"kind": "agent"}])["requests"]["total"], 0)
check("未知 kind 被忽略", metrics.build_report("24h", spans=[mk("agent", "x", 5), {"kind": "外星"}] )["spans"], 2)

print()
if all(results):
    print(f"[OK] verify_metrics 全部通过（{len(results)}/{len(results)}）")
    raise SystemExit(0)
print(f"[FAIL] {results.count(False)}/{len(results)} 项未通过")
raise SystemExit(1)
