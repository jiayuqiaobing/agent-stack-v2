"""公开检索。只在这一轮需要查网上事实时才被导入。

行为来自各家 Agent 的网页检索，不是整包搬仓库：
先 DuckDuckGo 摘要，没有再查中文维基。两边都失败才返回错误。
"""

import json
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "检索公开资料摘要。只在需要最新或外部事实时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词"},
            },
            "required": ["query"],
        },
    },
}


def _get_json(url: str):
    request = Request(url, headers={"User-Agent": "agent-lite"})
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _duckduckgo(query: str) -> list[str]:
    url = "https://api.duckduckgo.com/?q=" + quote(query) + "&format=json&no_html=1&skip_disambig=1"
    data = _get_json(url)
    lines = []
    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        lines.append(abstract)
    for topic in data.get("RelatedTopics") or []:
        if isinstance(topic, dict) and topic.get("Text"):
            lines.append(str(topic["Text"]))
        if len(lines) >= 5:
            break
    return lines


def _wikipedia(query: str) -> list[str]:
    url = (
        "https://zh.wikipedia.org/w/api.php?action=opensearch&limit=3&namespace=0&format=json&search="
        + quote(query)
    )
    data = _get_json(url)
    if not isinstance(data, list) or len(data) < 3:
        return []
    titles = data[1] if isinstance(data[1], list) else []
    summaries = data[2] if isinstance(data[2], list) else []
    lines = []
    for title, summary in zip(titles, summaries):
        text = str(summary or "").strip()
        if text:
            lines.append(f"{title}：{text}")
    return lines[:3]


def web_search_sync(query: str) -> str:
    target = (query or "").strip()
    if not target:
        return "错误: 没有检索词"
    errors = []
    for name, fn in (("DuckDuckGo", _duckduckgo), ("维基", _wikipedia)):
        try:
            lines = fn(target)
        except (URLError, json.JSONDecodeError, TimeoutError, OSError, ValueError) as e:
            errors.append(f"{name}: {e}")
            continue
        if lines:
            return "\n".join(lines)
    if errors:
        return "错误: 检索失败: " + "；".join(errors)
    return "没有检索到可引用的摘要"


async def web_search(query: str) -> str:
    import asyncio
    return await asyncio.to_thread(web_search_sync, query)
