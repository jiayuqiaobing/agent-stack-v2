"""一轮对话的辅助：整理输入、决定工具、拼上用得到的技能、执行查证。

计算、当前时间、天气不在这里。那三个只留给 tests/，模型看不到。
"""

import os
import re

from tools_local import execute_tool

_SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
_STOPPED = {"calculate", "get_time", "get_weather", "load_tool"}

def clean_input(text: str) -> str:
    raw = (text or "").replace("\x00", " ").strip()
    raw = re.sub(r"[ \t]+\n", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    if len(raw) > 8000:
        raw = raw[:8000]
    return raw


def _fn(item) -> dict:
    if not isinstance(item, dict):
        return {}
    fn = item.get("function") or {}
    return fn if isinstance(fn, dict) else {}


def _schema(tools: list | None, name: str) -> dict | None:
    if not isinstance(tools, list):
        return None
    for item in tools:
        if _fn(item).get("name") == name and name not in _STOPPED:
            return item
    return None


def _wants_web(text: str) -> bool:
    return bool(re.search(r"最新|新闻|今天发生|网上|维基|百科", text))


def _wants_project(text: str) -> bool:
    return bool(re.search(r"项目里|代码里|哪个文件|在哪定义|在哪个文件|源码", text))


def _wants_span(text: str) -> bool:
    return bool(re.search(r"第\s*\d+\s*行", text) and re.search(r"\.py|\.md|文件|源码", text))


def _wants_session(text: str) -> bool:
    return bool(re.search(r"刚才|之前说|我说过|上一句|前面说", text))


def _wants_word(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]{3,}", text) and re.search(r"什么意思|怎么翻译|英文释义|单词", text))


def _wants_shell(text: str) -> bool:
    return bool(re.search(r"运行命令|执行命令|终端|命令行|pytest|pip ", text))


def _wants_browser(text: str) -> bool:
    return bool(re.search(r"打开网页|用浏览器|页面上|渲染后", text))


def _wants_file(text: str) -> bool:
    return bool(re.search(r"读文件|读取|文件内容|目录|requirements\.txt|\.py\b|\.md\b", text))


def _urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)>\]]+", text)


def _wants_remote(text: str, name: str, description: str) -> bool:
    blob = f"{name} {description}"
    if re.search(r"股票|财报|基金|汇率", text) and re.search(r"financ|stock|finance|金融", blob, re.I):
        return True
    if re.search(r"网站检测|能不能打开|连通", text) and re.search(r"website|http|网站", blob, re.I):
        return True
    return False


def matching_skill(text: str) -> str:
    if not os.path.isdir(_SKILL_DIR):
        return ""
    pieces = []
    for name in sorted(os.listdir(_SKILL_DIR)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(_SKILL_DIR, name)
        try:
            body = open(path, encoding="utf-8").read().strip()
        except OSError:
            continue
        when = ""
        rest = body
        if body.startswith("when:"):
            first, _, rest = body.partition("\n")
            when = first.split(":", 1)[1].strip()
        if when:
            try:
                if not re.search(when, text):
                    continue
            except re.error:
                continue
        if rest.strip():
            pieces.append(rest.strip())
        if len(pieces) >= 2:
            break
    return "\n\n".join(pieces)


def prepare_turn(text: str, tools: list | None, tool_session_map: dict | None = None, memory=None, mode: str | None = None) -> dict:
    """聊天每轮都能检索和打开网页。计划再额外拆题。"""
    cleaned = clean_input(text)
    from runtime.web_lookup import WEB_SEARCH
    from runtime.browser_tool import BROWSER
    chosen = [WEB_SEARCH, BROWSER]
    if _urls(cleaned):
        page = _schema(tools, "fetch_url")
        if page:
            chosen.append(page)
    if _wants_file(cleaned) and not _wants_span(cleaned):
        reader = _schema(tools, "read_file")
        if reader:
            chosen.append(reader)
    if _wants_project(cleaned):
        from runtime.project_lookup import PROJECT_SEARCH
        chosen.append(PROJECT_SEARCH)
    if _wants_span(cleaned):
        from runtime.project_lookup import READ_SPAN
        chosen.append(READ_SPAN)
    if _wants_session(cleaned):
        from runtime.session_lookup import SESSION_SEARCH, bind_memory
        if memory is not None:
            bind_memory(memory)
        chosen.append(SESSION_SEARCH)
    if _wants_word(cleaned):
        from runtime.word_lookup import WORD_LOOKUP
        chosen.append(WORD_LOOKUP)
    if mode == "plan":
        from runtime.brief import BRIEF
        chosen.append(BRIEF)
    if _wants_shell(cleaned):
        from runtime.shell_tool import SHELL
        chosen.append(SHELL)
    if _wants_browser(cleaned):
        from runtime.browser_tool import BROWSER
        chosen.append(BROWSER)
    for item in tools if isinstance(tools, list) else []:
        fn = _fn(item)
        name = fn.get("name") or ""
        if name in _STOPPED or name in {"fetch_url", "read_file", "web_search", "search_project", "read_span", "search_session", "define_word", "make_brief", "run_command", "open_page"}:
            continue
        if name not in (tool_session_map or {}):
            continue
        if _wants_remote(cleaned, name, fn.get("description") or ""):
            chosen.append(item)
    unique = []
    seen_names = set()
    for item in chosen:
        name = _fn(item).get("name")
        if name and name not in seen_names:
            seen_names.add(name)
            unique.append(item)
    chosen = unique
    note = matching_skill(cleaned)
    if chosen:
        names = "、".join(_fn(item).get("name", "") for item in chosen)
        extra = f"这一轮可以调用：{names}。查完再回答，不要向用户解释为什么调用。"
        note = (note + "\n\n" + extra).strip() if note else extra
    return {"text": cleaned, "tools": chosen, "note": note}


async def run_assist(name: str, args: dict | None) -> str | None:
    if not isinstance(args, dict):
        args = {}
    if name in _STOPPED:
        return f"错误: 工具 '{name}' 已停用"
    if name == "web_search":
        from runtime.web_lookup import web_search
        return await web_search(str(args.get("query") or ""))
    if name == "search_project":
        from runtime.project_lookup import search_project
        return await search_project(str(args.get("query") or ""))
    if name == "read_span":
        from runtime.project_lookup import read_span
        return await read_span(str(args.get("path") or ""), args.get("line"))
    if name == "search_session":
        from runtime.session_lookup import search_session
        return await search_session(str(args.get("query") or ""))
    if name == "define_word":
        from runtime.word_lookup import define_word
        return await define_word(str(args.get("word") or ""))
    if name == "make_brief":
        from runtime.brief import make_brief
        return make_brief(args)
    if name == "run_command":
        from runtime.shell_tool import run_command
        return await run_command(str(args.get("command") or ""))
    if name == "open_page":
        from runtime.browser_tool import open_page
        return await open_page(str(args.get("url") or ""))
    if name in {"fetch_url", "read_file"}:
        return await execute_tool(name, args)
    return None
