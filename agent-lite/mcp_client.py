"""
agent-lite/mcp_client.py

MCP 客户端 — 连接本地 stdio + 远程 SSE 服务器，发现工具
在 main.py lifespan 中调用 setup_mcp_connections() 建立连接
"""

import logging
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)


# ============================================================================
# MCP 工具 → OpenAI Function Calling JSON Schema
# ============================================================================


def mcp_to_openai_schema(tool) -> dict:
    """将 MCP Tool 对象转为 OpenAI Function Calling 格式"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": (
                tool.inputSchema
                if isinstance(tool.inputSchema, dict)
                else {"type": "object", "properties": {}}
            ),
        },
    }


# ============================================================================
# MCP 连接配置
# ============================================================================


async def setup_mcp_connections():
    """
    启动时调用 — 建立所有 MCP 连接并发现远程工具。

    返回：
        all_remote_tools:   OpenAI 格式的远程工具列表
        tool_session_map:   工具名 → {"session": ..., "type": "...", "url": ...}
        cleanup:            async 清理函数，在 lifespan 关闭阶段调用
    """
    local_config = {
        "enabled": os.getenv("MCP_LOCAL_ENABLED", "0").strip() == "1",
        # 必须用 sys.executable 而不是裸 "python"：
        # 裸 "python" 会解析到系统/base 解释器，可能没装 mcp 依赖（实测踩过）。
        # 用 sys.executable 保证子进程与当前服务用同一个解释器。
        "command": sys.executable,
        "args": [os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")],
    }

    # 远程 SSE 服务器（从环境变量读取）
    remote_configs: list[dict] = []
    finance_url = os.getenv("MCP_FINANCE_URL")
    if finance_url:
        remote_configs.append({"enabled": True, "url": finance_url, "label": "金融信息"})
    website_url = os.getenv("MCP_WEBSITE_URL")
    if website_url:
        remote_configs.append({"enabled": True, "url": website_url, "label": "网站检测"})

    all_remote_tools = []
    tool_session_map: dict[str, dict] = {}
    _cleanup_stack: list[tuple] = []

    # --- 连接本地 stdio ---
    if local_config["enabled"]:
        try:
            params = StdioServerParameters(
                command=local_config["command"],
                args=local_config["args"],
                env={"PYTHONIOENCODING": "utf-8"},
            )
            cm, session = await _connect_stdio(params)
            _cleanup_stack.append(("stdio", cm, session))

            tools = await session.list_tools()
            for t in tools.tools:
                all_remote_tools.append(mcp_to_openai_schema(t))
                tool_session_map[t.name] = {
                    "session": session,
                    "type": "stdio",
                }
            logger.info("本地 MCP：发现 %d 个工具", len(tools.tools))
        except Exception as e:
            logger.warning("本地 MCP 连接失败：%s", e)

    # --- 连接远程 SSE ---
    for cfg in remote_configs:
        if not cfg.get("enabled"):
            continue
        try:
            cm, session = await _connect_sse(cfg["url"])
            _cleanup_stack.append(("sse", cm, session))

            tools = await session.list_tools()
            for t in tools.tools:
                all_remote_tools.append(mcp_to_openai_schema(t))
                tool_session_map[t.name] = {
                    "session": session,
                    "type": "sse",
                    "url": cfg["url"],
                }
            logger.info("远程 MCP（%s）：发现 %d 个工具", cfg["label"], len(tools.tools))
        except Exception as e:
            logger.warning("远程 MCP 连接失败（%s）：%s", cfg.get("url", ""), e)

    # --- 关闭回调 ---
    async def cleanup():
        """按相反顺序关闭所有 MCP 连接"""
        for label, cm, session in reversed(_cleanup_stack):
            try:
                await session.__aexit__(None, None, None)
            except Exception as e:
                logger.debug("关闭 session 时异常（%s）：%s", label, e)
            try:
                await cm.__aexit__(None, None, None)
            except Exception as e:
                logger.debug("关闭 transport 时异常（%s）：%s", label, e)
        logger.info("MCP 连接已关闭：%d 个", len(_cleanup_stack))

    return all_remote_tools, tool_session_map, cleanup


# ============================================================================
# 底层连接函数
# ============================================================================


async def _connect_stdio(params):
    """建立 stdio 连接 — 返回 (context_manager, session)"""
    cm = stdio_client(params)
    read, write = await cm.__aenter__()
    session = ClientSession(read, write)
    await session.__aenter__()
    await session.initialize()
    return cm, session


async def _connect_sse(url: str):
    """建立 SSE 连接 — 返回 (context_manager, session)"""
    cm = sse_client(url)
    read, write = await cm.__aenter__()
    session = ClientSession(read, write)
    await session.__aenter__()
    await session.initialize()
    return cm, session
