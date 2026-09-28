"""在当前会话已经说过的话里查找。只在用户提起刚才或之前时才导入。

不跨会话。对应各家 Agent 的会话记忆检索，不是全局搜索。
"""

from contextvars import ContextVar

SESSION_SEARCH = {
    "type": "function",
    "function": {
        "name": "search_session",
        "description": "在本会话已经出现过的话里查找，不查别的会话。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要找的原话或关键词"},
            },
            "required": ["query"],
        },
    },
}

_memory: ContextVar = ContextVar("session_lookup_memory", default=None)


def bind_memory(memory) -> None:
    _memory.set(memory)


def search_session_sync(query: str) -> str:
    memory = _memory.get()
    if memory is None:
        return "错误: 当前没有会话"
    needle = (query or "").strip()
    if len(needle) < 1:
        return "错误: 没有查找词"
    hits = []
    for msg in getattr(memory, "short_term", []) or []:
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content") or "")
        if needle in content and msg.get("role") in {"user", "assistant"}:
            hits.append(f"{msg.get('role')}: {content[:180]}")
        if len(hits) >= 8:
            break
    if not hits:
        return "本会话里没有这句"
    return "\n".join(hits)


async def search_session(query: str) -> str:
    return search_session_sync(query)
