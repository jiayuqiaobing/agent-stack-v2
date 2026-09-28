"""
agent-lite/tools_local.py

本地工具定义 — 计算器 + 文件读取 + 系统时间
"""

import asyncio
import ast
import json
import operator
import os
import logging
import re
from datetime import datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


# ============================================================================
# 工具函数实现
# ============================================================================

# 安全的 AST 运算符白名单
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _safe_eval_node(node):
    """递归 AST 遍历器，拒绝一切不在白名单中的节点"""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.BinOp):
        return _SAFE_OPS[type(node.op)](_safe_eval_node(node.left), _safe_eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        return _SAFE_OPS[type(node.op)](_safe_eval_node(node.operand))
    if isinstance(node, ast.Constant):
        return node.value
    raise ValueError(f"不支持的表达式")


async def safe_calculate(expression: str) -> str:
    """安全的数学计算，只允许四则运算和幂运算"""
    try:
        expression = expression.replace("^", "**")
        return str(round(_safe_eval_node(ast.parse(expression, mode="eval")), 6))
    except Exception as e:
        return f"计算错误: {e}"


# 项目根目录（用于限制文件访问范围）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _read_file_sync(file_path: str) -> str:
    """safe_read_file 的同步实现，在线程池中运行，避免阻塞事件循环"""
    full_path = os.path.normpath(os.path.join(PROJECT_ROOT, file_path))
    if not full_path.startswith(PROJECT_ROOT):
        return "错误: 禁止访问项目目录外的文件"
    if not os.path.exists(full_path):
        return f"错误: 路径不存在: {file_path}"
    if os.path.isdir(full_path):
        items = os.listdir(full_path)
        lines = [
            f"  {'[DIR]' if os.path.isdir(os.path.join(full_path, n)) else '[FILE]'} {n}"
            for n in sorted(items)
        ]
        return "目录内容:\n" + "\n".join(lines)
    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    if len(content) > 3000:
        content = content[:3000] + "\n...(已截断)..."
    return content


async def safe_read_file(file_path: str) -> str:
    """读取项目目录下的文件内容或列出目录结构（线程池执行，不阻塞事件循环）"""
    return await asyncio.to_thread(_read_file_sync, file_path)


async def get_current_time() -> str:
    """查询当前日期和时间"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fetch_url_sync(url: str) -> str:
    target = (url or "").strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        return "错误: 只接受 http 或 https 地址"
    request = Request(target, headers={"User-Agent": "agent-lite"})
    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read(200_000)
            charset = response.headers.get_content_charset() or "utf-8"
    except URLError as e:
        return f"错误: 打不开这个地址: {e.reason}"
    text = raw.decode(charset, errors="replace")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "错误: 页面没有可读文字"
    if len(text) > 4000:
        text = text[:4000] + " ...(已截断)"
    return text


async def fetch_url(url: str) -> str:
    """读取一个网页的正文，供回答时引用"""
    return await asyncio.to_thread(_fetch_url_sync, url)


def _weather_sync(city: str, day: str = "today") -> str:
    target = (city or "").strip()
    if not target:
        return "错误: 没有城市名"
    request = Request(
        f"https://wttr.in/{target}?format=j1",
        headers={"User-Agent": "agent-lite"},
    )
    try:
        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except (URLError, json.JSONDecodeError, TimeoutError) as e:
        return f"错误: 天气查询失败: {e}"
    days = data.get("weather") or []
    index = {"today": 0, "tomorrow": 1, "the_day_after_tomorrow": 2}.get(day, 0)
    if day == "all":
        picked = days
    else:
        picked = days[index:index + 1]
    if not picked:
        return "错误: 没有这一天的天气"
    lines = []
    for item in picked:
        hourly = item.get("hourly") or [{}]
        desc = ((hourly[min(4, len(hourly) - 1)].get("weatherDesc") or [{}])[0]).get("value") or ""
        lines.append(f"{item.get('date')}：{desc}，{item.get('mintempC')}°C ~ {item.get('maxtempC')}°C")
    return "\n".join(lines)


async def get_weather(city: str, day: str = "today") -> str:
    """查询城市天气。进程内调用，不另开 MCP 进程。"""
    return await asyncio.to_thread(_weather_sync, city, day)


# ============================================================================
# 工具注册表 — 名称 → 异步函数
# ============================================================================

TOOL_REGISTRY = {
    "calculate": safe_calculate,
    "read_file": safe_read_file,
    "get_time": get_current_time,
    "fetch_url": fetch_url,
    "get_weather": get_weather,
}


# ============================================================================
# OpenAI Function Calling JSON Schema
# ============================================================================

CALCULATOR_TOOL = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": "执行数学计算，支持 + - * / **（幂）和括号。回复中不使用LaTeX格式。",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "数学表达式，如 '3+(4/2)'。"}
            },
            "required": ["expression"],
        },
    },
}

READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读取项目目录下的文件内容或列出目录结构",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "相对于项目根目录的路径"}
            },
            "required": ["file_path"],
        },
    },
}

GET_TIME_TOOL = {
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "查询当前日期和时间",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

FETCH_URL_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": "打开用户给出的 http 或 https 网页，读取正文。用户提到网上的内容、梗、新闻或链接时必须先调用，不要只凭记忆。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "完整网址，以 http:// 或 https:// 开头"}
            },
            "required": ["url"],
        },
    },
}


WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询城市天气，今天、明天或后天。",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，如北京"},
                "day": {
                    "type": "string",
                    "description": "today / tomorrow / the_day_after_tomorrow / all",
                },
            },
            "required": ["city"],
        },
    },
}


LOCAL_TOOLS = [CALCULATOR_TOOL, READ_FILE_TOOL, GET_TIME_TOOL, FETCH_URL_TOOL, WEATHER_TOOL]


# ============================================================================
# 工具执行分发器
# ============================================================================

async def execute_tool(name: str, args: dict | None) -> str:
    """根据工具名分发到对应异步函数"""
    if not isinstance(args, dict):
        args = {}
    if name not in TOOL_REGISTRY:
        return f"错误: 未知工具 '{name}'"
    try:
        return str(await TOOL_REGISTRY[name](**args))
    except TypeError as e:
        logger.warning("工具 %s 参数不对：%s", name, e)
        return f"错误: 工具 '{name}' 参数不完整"
    except Exception as e:
        logger.warning("工具 %s 执行失败：%s", name, e)
        return f"工具执行错误: {e}"
