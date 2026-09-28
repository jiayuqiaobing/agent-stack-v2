"""查英文单词释义。只在句子里有英文词并且在问意思时才导入。

用 dictionaryapi.dev 的免费释义，不查中文词，也不做整段翻译。
"""

import json
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

WORD_LOOKUP = {
    "type": "function",
    "function": {
        "name": "define_word",
        "description": "查一个英文单词的词性和简短释义。",
        "parameters": {
            "type": "object",
            "properties": {
                "word": {"type": "string", "description": "英文单词"},
            },
            "required": ["word"],
        },
    },
}


def define_word_sync(word: str) -> str:
    target = "".join(ch for ch in (word or "").strip() if ch.isalpha())
    if len(target) < 2:
        return "错误: 需要一个英文单词"
    url = "https://api.dictionaryapi.dev/api/v2/entries/en/" + quote(target.lower())
    request = Request(url, headers={"User-Agent": "agent-lite"})
    try:
        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except (URLError, json.JSONDecodeError, TimeoutError, OSError, ValueError) as e:
        return f"错误: 释义查询失败: {e}"
    if not isinstance(data, list) or not data:
        return "没有查到这个单词"
    entry = data[0] if isinstance(data[0], dict) else {}
    lines = []
    for meaning in entry.get("meanings") or []:
        if not isinstance(meaning, dict):
            continue
        part = meaning.get("partOfSpeech") or ""
        defs = meaning.get("definitions") or []
        if defs and isinstance(defs[0], dict) and defs[0].get("definition"):
            lines.append(f"{part}: {defs[0]['definition']}")
        if len(lines) >= 3:
            break
    if not lines:
        return "没有查到这个单词"
    return target + "\n" + "\n".join(lines)


async def define_word(word: str) -> str:
    import asyncio
    return await asyncio.to_thread(define_word_sync, word)
