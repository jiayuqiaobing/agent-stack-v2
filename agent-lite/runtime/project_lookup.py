"""在本项目源码里找文字。只在用户明确要找代码或文件时才被导入。

对应 Hermes 文件搜索里「按词找源码」这一小段，不包含改文件和跑命令。
"""

import os

PROJECT_SEARCH = {
    "type": "function",
    "function": {
        "name": "search_project",
        "description": "在当前项目源码里查找一段文字，返回文件和行号。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要找的文字"},
            },
            "required": ["query"],
        },
    },
}

READ_SPAN = {
    "type": "function",
    "function": {
        "name": "read_span",
        "description": "按文件和行号读取前后各 20 行。路径必须在项目内。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根的路径"},
                "line": {"type": "integer", "description": "中心行号"},
            },
            "required": ["path", "line"],
        },
    },
}

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKIP = {"logs", "chroma_db", "models", "__pycache__", ".git", ".venv"}
_EXT = {".py", ".md", ".html", ".txt", ".json"}


def search_project_sync(query: str) -> str:
    needle = (query or "").strip()
    if len(needle) < 2:
        return "错误: 查找词至少两个字"
    hits = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        dirnames[:] = [name for name in dirnames if name not in _SKIP]
        for filename in filenames:
            if scanned >= 400 or len(hits) >= 20:
                break
            if os.path.splitext(filename)[1].lower() not in _EXT:
                continue
            path = os.path.join(dirpath, filename)
            scanned += 1
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    for lineno, line in enumerate(handle, start=1):
                        if needle in line:
                            rel = os.path.relpath(path, _ROOT)
                            hits.append(f"{rel}:{lineno}: {line.strip()[:160]}")
                            if len(hits) >= 20:
                                break
            except OSError:
                continue
        if scanned >= 400 or len(hits) >= 20:
            break
    if not hits:
        return "项目里没有找到这段文字"
    return "\n".join(hits)


def _inside(path: str) -> str | None:
    full = os.path.normpath(os.path.join(_ROOT, path))
    if not full.startswith(_ROOT):
        return None
    return full


def read_span_sync(path: str, line: int) -> str:
    target = _inside(path or "")
    if target is None:
        return "错误: 不能读项目外的文件"
    if not os.path.isfile(target):
        return "错误: 文件不存在"
    try:
        center = int(line)
    except (TypeError, ValueError):
        return "错误: 行号不对"
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as handle:
            rows = handle.readlines()
    except OSError as e:
        return f"错误: 读文件失败: {e}"
    start = max(center - 20, 1)
    end = min(center + 20, len(rows))
    chunk = []
    for lineno in range(start, end + 1):
        chunk.append(f"{lineno}: {rows[lineno - 1].rstrip()}")
    return "\n".join(chunk) if chunk else "错误: 这一行超出文件长度"


async def search_project(query: str) -> str:
    import asyncio
    return await asyncio.to_thread(search_project_sync, query)


async def read_span(path: str, line: int) -> str:
    import asyncio
    return await asyncio.to_thread(read_span_sync, path, line)
