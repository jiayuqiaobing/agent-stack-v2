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
# session_id 也走上下文：契约要求每个 span 都带它，
# 靠调用方逐个传太容易漏（且漏了不会报错，只会静默丢数据）
_current_session_id: ContextVar[Optional[str]] = ContextVar("current_session_id", default=None)


def get_trace_id() -> Optional[str]:
    """取当前上下文的 trace_id（不在 trace 中时为 None）"""
    return _current_trace_id.get()


def get_current_span_id() -> Optional[str]:
    """取当前 span 的 span_id，用作新 span 的 parent_span_id"""
    return _current_span_id.get()


def get_session_id() -> Optional[str]:
    """取当前上下文的 session_id（未进入 trace 时为 None）"""
    return _current_session_id.get()


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
    session_id: str | None = None
    _trace_token: Any = None
    _span_token: Any = None
    _session_token: Any = None

    def __enter__(self) -> "SpanContext":
        self._trace_token = _current_trace_id.set(self.trace_id)
        self._span_token = _current_span_id.set(self.span_id)
        if self.session_id is not None:
            self._session_token = _current_session_id.set(self.session_id)
        return self

    def __exit__(self, *exc_info) -> None:
        # 逆序恢复，保证嵌套层级正确
        if self._session_token is not None:
            _current_session_id.reset(self._session_token)
        if self._span_token is not None:
            _current_span_id.reset(self._span_token)
        if self._trace_token is not None:
            _current_trace_id.reset(self._trace_token)


def span_context(span_id: str, trace_id: str, session_id: str | None = None) -> SpanContext:
    """创建（不进入）一个 span 上下文，配合 with 使用"""
    return SpanContext(span_id=span_id, trace_id=trace_id, session_id=session_id)


class TraceContext:
    """一条 trace 的上下文，进入时把根 span 设为"当前 span"

    这样深层函数（工具调用、RAG 检索）在 make_span 时会自动把根 span 当父节点，
    不需要层层传参。
    """

    def __init__(self, root_span: dict):
        self.root_span = root_span
        self.trace_id = root_span["trace_id"]
        self._ctx = span_context(
            root_span["span_id"], root_span["trace_id"], root_span.get("session_id")
        )

    def __enter__(self) -> dict:
        self._ctx.__enter__()
        return self.root_span

    def __exit__(self, *exc_info) -> None:
        self._ctx.__exit__(*exc_info)


def start_trace(
    name: str = "agent.turn",
    incoming_trace_id: str | None = None,
    session_id: str = "default",
) -> TraceContext:
    """开启一条新 trace 并创建根 span

    用法：
        with start_trace(session_id=sid) as root:
            ...                                  # 深层函数自动挂到 root 下
        finish_span(root)                        # 退出后结束根 span
        export_span(root)

    参数：
        incoming_trace_id: 来自 HTTP header X-Trace-Id，非法则忽略并重新生成

    ⚠️ 曾出过的 bug：根 span 的 parent 变成它自己。
       原因是 make_span 默认从上下文取父节点，而上下文里存的正是根 span。
       现在根 span 在这里显式创建（parent_span_id=None），不再有歧义。
    """
    trace_id = incoming_trace_id if is_valid_trace_id(incoming_trace_id) else new_trace_id()
    if incoming_trace_id and not is_valid_trace_id(incoming_trace_id):
        logger.warning("X-Trace-Id 格式非法，已丢弃并重新生成：%r", incoming_trace_id)

    root_span = make_span(name, "agent", trace_id=trace_id,
                          parent_span_id=None, session_id=session_id)
    return TraceContext(root_span)


def begin_trace(incoming_trace_id: str | None = None):
    """[兼容旧用法] 返回 (trace_id, root_span_id, 上下文)

    ⚠️ 已不推荐 —— 它只给 id 不给 span 对象，调用方无法把子 span 挂到根上。
    新代码请用 start_trace()，它直接返回根 span。
    """
    trace_id = incoming_trace_id if is_valid_trace_id(incoming_trace_id) else new_trace_id()
    if incoming_trace_id and not is_valid_trace_id(incoming_trace_id):
        logger.warning("X-Trace-Id 格式非法，已丢弃并重新生成：%r", incoming_trace_id)

    root_span_id = new_span_id()
    return trace_id, root_span_id, span_context(root_span_id, trace_id)


# ============================================================================
# Span 数据结构（符合契约文档第 4 节字段定义）
# ============================================================================


# 哨兵：区分「调用方没说 parent」（用上下文）和「调用方明确要求根 span，parent=None」
_UNSET = object()


def make_span(
    name: str,
    kind: str,
    trace_id: str | None = None,
    parent_span_id: Any = _UNSET,
    session_id: Any = _UNSET,
    attributes: dict | None = None,
) -> dict:
    """创建一个 span（此时尚未结束，end_time / duration_ms 为 None）

    参数：
        name:      低基数操作名，如 "llm.chat" / "tool.calculate"
                   ⚠️ 不要把用户输入拼进 name，否则指标无法聚合
        kind:      agent | llm | tool | rag | memory
        trace_id:  缺省取当前上下文
        parent_span_id:
            · 不传（默认）→ 取当前上下文里的 span_id（嵌套场景）
            · 显式传 None → **强制为根 span**，父节点为空
            · 传具体 id  → 显式指定父节点
        attributes: 按 kind 定义的业务字段

    为什么需要哨兵值区分：
        曾出过一个 bug —— 根 span 的 parent 变成它自己。
        原因是 begin_trace 把上下文的当前 span 设成了根 span，
        而 make_span 默认从上下文取 parent，于是"自己当自己的爹"。
        语义上必须能区分「没说」和「明确要求是根」。
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"非法 span kind: {kind!r}，必须是 {sorted(VALID_KINDS)} 之一")

    if parent_span_id is _UNSET:
        parent = get_current_span_id()
    else:
        parent = parent_span_id        # 显式 None 或显式 id

    # session_id 同理：不传则从上下文继承（契约要求每个 span 都带上它）
    if session_id is _UNSET:
        sess = get_session_id() or "default"
    else:
        sess = session_id

    return {
        "trace_id": trace_id or get_trace_id() or new_trace_id(),
        "span_id": new_span_id(),
        "parent_span_id": parent,
        "name": name,
        "kind": kind,
        "session_id": sess,
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
