"""trace.py — trace/span 数据模型与传播

实现 docs/3-可观测数据模型.md 的契约。本模块只负责：

    1. trace_id / span_id 的生成（W3C Trace Context 格式）
    2. span 数据结构（符合契约字段）
    3. contextvars 传播（深层函数无需层层传参即可拿到当前 span）
    4. HTTP header 读写（X-Trace-Id / X-Parent-Span-Id）

**本阶段不接业务埋点** —— 埋点是阶段二的事（见 docs/2-产品规格.md 阶段二）。

设计约束（来自契约文档）：
- trace_id 32 位小写 hex，span_id 16 位小写 hex —— 就是 W3C 标准，将来接 OTel 不用改
- session_id 与 trace_id 正交：一个 session（多轮对话）产生多个 trace
- 可观测是旁路：本模块的任何调用都不得改变业务逻辑的行为与结果
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 常量与 ID 生成
# ============================================================================

# W3C Trace Context 格式（见契约文档第 3 节）
TRACE_ID_HEX_LEN = 32          # 16 字节
SPAN_ID_HEX_LEN = 16           # 8 字节

TRACE_ID_HEADER = "X-Trace-Id"
PARENT_SPAN_ID_HEADER = "X-Parent-Span-Id"

# 合法的 trace_id：32 位小写 hex（全 0 是 W3C 规定的非法值）
_VALID_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")

# span kind 白名单（见契约文档第 5 节）
VALID_KINDS = frozenset({"agent", "llm", "tool", "rag", "memory"})

# 存储：与既有 logs/ 目录一致，已在 .gitignore 中
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


def new_trace_id() -> str:
    """生成 W3C 格式的 trace_id（32 位小写 hex）"""
    return secrets.token_hex(16)


def new_span_id() -> str:
    """生成 W3C 格式的 span_id（16 位小写 hex）"""
    return secrets.token_hex(8)


def is_valid_trace_id(value: str | None) -> bool:
    """校验外部传入的 trace_id 是否合法

    客户端也可以自带 X-Trace-Id（便于跨系统串联），但**必须校验格式** ——
    非法值一律丢弃并重新生成，防止被注入任意字符串污染日志。
    """
    if not isinstance(value, str):
        return False
    if not _VALID_TRACE_ID.match(value):
        return False
    return value != "0" * TRACE_ID_HEX_LEN      # 全 0 为 W3C 保留的非法值


def now() -> float:
    """当前 Unix 时间戳（秒，含毫秒小数）"""
    return datetime.now(timezone.utc).timestamp()


# ============================================================================
# 上下文传播（contextvars）
# ============================================================================
#
# 为什么用 contextvars 而不是：
#   参数传递 —— agent.py → execute_tool() → _call_mcp_tool() 链路已很深，
#               加参数会污染所有函数签名
#   全局变量 —— v1 踩过"多 session 交叉"的坑，根因就是共享可变状态
#
# contextvars 在 asyncio 下是安全的：每个 task 有独立的上下文副本。

_current_trace_id: ContextVar[Optional[str]] = ContextVar("current_trace_id", default=None)
_current_span_id: ContextVar[Optional[str]] = ContextVar("current_span_id", default=None)


def get_trace_id() -> Optional[str]:
    """取当前上下文的 trace_id（不在 trace 中时为 None）"""
    return _current_trace_id.get()


def get_current_span_id() -> Optional[str]:
    """取当前 span 的 span_id，用作新 span 的 parent_span_id"""
    return _current_span_id.get()


@dataclass
class SpanContext:
    """进入一个 span 的作用域，退出时自动恢复到外层

    用法：
        with span_context(new_span_id, trace_id):
            ...  # 这里的 get_current_span_id() 返回新 span
        # 退出后恢复到外层的 span_id
    """

    span_id: str
    trace_id: str
    _trace_token: Any = None
    _span_token: Any = None

    def __enter__(self) -> "SpanContext":
        self._trace_token = _current_trace_id.set(self.trace_id)
        self._span_token = _current_span_id.set(self.span_id)
        return self

    def __exit__(self, *exc_info) -> None:
        # 逆序恢复，保证嵌套层级正确
        if self._span_token is not None:
            _current_span_id.reset(self._span_token)
        if self._trace_token is not None:
            _current_trace_id.reset(self._trace_token)


def span_context(span_id: str, trace_id: str) -> SpanContext:
    """创建（不进入）一个 span 上下文，配合 with 使用"""
    return SpanContext(span_id=span_id, trace_id=trace_id)


def begin_trace(incoming_trace_id: str | None = None) -> tuple[str, str, SpanContext]:
    """开启一条新 trace

    参数：
        incoming_trace_id: 来自 HTTP header X-Trace-Id，非法则忽略并重新生成

    返回：(trace_id, root_span_id, 已进入的上下文)
    """
    trace_id = incoming_trace_id if is_valid_trace_id(incoming_trace_id) else new_trace_id()
    if incoming_trace_id and not is_valid_trace_id(incoming_trace_id):
        logger.warning("X-Trace-Id 格式非法，已丢弃并重新生成：%r", incoming_trace_id)

    root_span_id = new_span_id()
    return trace_id, root_span_id, span_context(root_span_id, trace_id)


# ============================================================================
# Span 数据结构（符合契约文档第 4 节字段定义）
# ============================================================================


def make_span(
    name: str,
    kind: str,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    session_id: str = "default",
    attributes: dict | None = None,
) -> dict:
    """创建一个 span（此时尚未结束，end_time / duration_ms 为 None）

    参数：
        name:      低基数操作名，如 "llm.chat" / "tool.calculate"
                   ⚠️ 不要把用户输入拼进 name，否则指标无法聚合
        kind:      agent | llm | tool | rag | memory
        trace_id:  缺省取当前上下文
        parent_span_id: 缺省取当前上下文中的 span_id
        attributes: 按 kind 定义的业务字段
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"非法 span kind: {kind!r}，必须是 {sorted(VALID_KINDS)} 之一")

    return {
        "trace_id": trace_id or get_trace_id() or new_trace_id(),
        "span_id": new_span_id(),
        "parent_span_id": parent_span_id if parent_span_id is not None else get_current_span_id(),
        "name": name,
        "kind": kind,
        "session_id": session_id,
        "start_time": now(),
        "end_time": None,
        "duration_ms": None,
        "status": "unset",
        "error": None,
        "attributes": attributes or {},
    }


def finish_span(span: dict, status: str = "ok", error: Exception | None = None) -> dict:
    """结束一个 span，补齐 end_time / duration_ms / status

    参数：
        status: "ok" | "error" | "unset"
        error:  仅 status="error" 时传，会记录 {type, message}
    """
    span["end_time"] = now()
    span["duration_ms"] = round((span["end_time"] - span["start_time"]) * 1000, 3)
    span["status"] = status
    if error is not None:
        span["error"] = {"type": type(error).__name__, "message": str(error)}
    return span


_daily_log_path_cache: dict[str, str] = {}


def _daily_log_path(day: Optional[str] = None) -> str:
    day = day or datetime.now().strftime("%Y-%m-%d")
    if day not in _daily_log_path_cache:
        _daily_log_path_cache[day] = os.path.join(_LOG_DIR, f"spans-{day}.jsonl")
    return _daily_log_path_cache[day]


def export_span(span: dict) -> None:
    """把 span 追加写入 JSONL（一行一个 span）

    为什么用 JSONL 而不是 JSON 数组：
        - 追加写，进程崩溃也不丢已落盘数据
        - 可以直接 grep / jq 查，不需要先解析整个文件
        - 零依赖，不需要引入 SQLite / Prometheus

    写入失败**只记日志不抛异常** —— 可观测是旁路，不能因为它挂掉业务。
    """
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_daily_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(span, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("span 写入失败（不影响业务）", exc_info=True)


# ============================================================================
# HTTP header 读写
# ============================================================================


def trace_id_from_headers(headers: Any) -> str | None:
    """从请求头提取 trace_id，非法则返回 None（调用方应重新生成）"""
    value = headers.get(TRACE_ID_HEADER) if hasattr(headers, "get") else None
    return value if is_valid_trace_id(value) else None


def trace_headers(trace_id: str, span_id: str | None = None) -> dict:
    """构造响应头 —— agent 必须回写 X-Trace-Id，便于调用方对账"""
    headers = {TRACE_ID_HEADER: trace_id}
    if span_id:
        headers[PARENT_SPAN_ID_HEADER] = span_id
    return headers
