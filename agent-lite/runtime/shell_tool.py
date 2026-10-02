"""在项目目录里跑一条命令。只在用户明确要看命令结果时才导入。

有超时。不接受空命令。工作目录锁在项目内。
"""

import asyncio
import os

SHELL = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": "在项目目录执行一条只读或短命令，最多 20 秒。不要用它改系统设置。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "一条命令"},
            },
            "required": ["command"],
        },
    },
}

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BLOCK = ("rm ", "rm\t", "del ", "format ", "shutdown", "mkfs", "reg delete", "Remove-Item")


async def run_command(command: str) -> str:
    text = (command or "").strip()
    if not text:
        return "错误: 没有命令"
    lowered = text.lower()
    if any(flag in lowered for flag in _BLOCK) or ".." in text or lowered.startswith("cd ") or " cd " in lowered:
        return "错误: 这条命令不允许执行"
    try:
        proc = await asyncio.create_subprocess_shell(
            text,
            cwd=_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        return "错误: 命令超过 20 秒，已停止"
    except OSError as e:
        return f"错误: 命令无法启动: {e}"
    body = (out or b"").decode("utf-8", errors="replace").strip()
    if len(body) > 4000:
        body = body[:4000] + "\n...(已截断)"
    return body or "（命令没有输出）"
