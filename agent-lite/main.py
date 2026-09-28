"""
agent-lite/main.py

FastAPI 入口 — 创建 app + lifespan + CORS + 日志配置
"""

import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv

# 必须在 router/config 导入前加载环境配置，避免客户端在 lifespan 之前使用空配置初始化。
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=True)

from observability import metrics, trace
from observability.logging_setup import setup_logging
from router import router
from mcp_client import setup_mcp_connections
from tools_local import FETCH_URL_TOOL, READ_FILE_TOOL

# ============================================================================
# 日志配置 — 所有模块的 logger = logging.getLogger(__name__) 自动继承
# ============================================================================

setup_logging(os.path.join(os.path.dirname(__file__), "logs"))

logger = logging.getLogger(__name__)

# ============================================================================
# Lifespan — 启动/关闭时执行
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("agent-lite 启动中...")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY 未设置，请在 .env 文件中配置")
    else:
        logger.info("OpenAI API Key 已配置（%s...%s）", api_key[:8], api_key[-4:])

    # 建立 MCP 连接，发现远程工具
    logger.info("正在连接 MCP 服务器...")
    remote_tools, tool_session_map, mcp_cleanup = await setup_mcp_connections()
    app.state.all_tools = [FETCH_URL_TOOL, READ_FILE_TOOL] + remote_tools
    app.state.tool_session_map = tool_session_map
    app.state.mcp_cleanup = mcp_cleanup
    logger.info(
        "能力初始化完成：本地辅助=%d，远程 MCP=%d，MCP 本地进程=%s，远程地址=%s",
        2,
        len(remote_tools),
        "启用" if os.getenv("MCP_LOCAL_ENABLED", "0").strip() == "1" else "关闭",
        len([name for name in ("MCP_FINANCE_URL", "MCP_WEBSITE_URL") if os.getenv(name)]),
    )

    logger.info("agent-lite 启动完成，浏览器打开 http://localhost:8000 开始对话")
    yield  # ← 服务运行期间停在这

    # 关闭 MCP 连接
    logger.info("正在关闭 MCP 连接...")
    await app.state.mcp_cleanup()
    logger.info("agent-lite 已关闭")


# ============================================================================
# App 创建
# ============================================================================

app = FastAPI(
    title="agent-lite — AI Agent",
    description="手写 Agent 循环 + HybridMemory + ChromaDB RAG + SSE 流式输出",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)

# CORS — 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# trace 中间件 — X-Trace-Id 的读写（见 docs/3-可观测数据模型.md 第 6.1 节）
# ============================================================================
#
# 契约要求：
#   1. 客户端可自带 X-Trace-Id（便于跨系统串联）—— 但必须校验格式，非法值丢弃重新生成
#   2. agent **必须**在响应头回写 X-Trace-Id，便于调用方对账
#
# 可观测是旁路：本中间件不得改变任何业务行为。


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    incoming = trace.trace_id_from_headers(request.headers)
    trace_id, root_span_id, ctx = trace.begin_trace(incoming)

    with ctx:
        request.state.trace_id = trace_id
        request.state.span_id = root_span_id
        response = await call_next(request)

    response.headers[trace.TRACE_ID_HEADER] = trace_id
    return response


# 注册路由
app.include_router(router)


# ============================================================================
# 根端点 — 必须在 mount 之前注册，否则被静态文件拦截
# ============================================================================


@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "version": "0.2.0",
        "auth_required": bool(os.getenv("API_KEY", "").strip()),
    }


# ============================================================================
# 指标接口（见 docs/3-可观测数据模型.md 第 8 节）
# ============================================================================
#
# 只读聚合，不改任何既有接口。数据源是 trace 写的 span JSONL。
# 窗口可选 1h / 6h / 24h / 7d，默认 24h。


@app.get("/metrics")
async def get_metrics(window: str = "24h"):
    """聚合指标 —— 请求量、延迟分位、token 与缓存命中率、工具成功率、RAG 指标"""
    if window not in metrics.WINDOW_HOURS:
        return {
            "error": f"不支持的 window: {window!r}",
            "supported": sorted(metrics.WINDOW_HOURS),
        }
    return metrics.build_report(window)


# 挂载静态文件（聊天界面）—— 放最后，否则覆盖所有 / 请求
static_dir = os.path.join(os.path.dirname(__file__), "static")
class _PageCookieMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        key = os.getenv("API_KEY", "").strip()
        if key:
            response.set_cookie("agent_access", key, httponly=True, samesite="lax", path="/")
        return response


app.add_middleware(_PageCookieMiddleware)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


# ============================================================================
# 直接启动
# ============================================================================

def main():
    import uvicorn

    port = int(os.getenv("AGENT_LITE_PORT", "8000"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
