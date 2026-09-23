"""
test08/main.py

FastAPI 入口 — 创建 app + lifespan + CORS + 日志配置
"""

import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from router import router
from mcp_client import setup_mcp_connections
from tools_local import LOCAL_TOOLS

# ============================================================================
# 日志配置 — 所有模块的 logger = logging.getLogger(__name__) 自动继承
# ============================================================================

# 日志目录
_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,                # 开发用 DEBUG，上线改 INFO
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),                                        # 控制台
        logging.FileHandler(
            os.path.join(_log_dir, "test08.log"), encoding="utf-8",     # 持久化文件
        ),
    ],
)

# 第三方库日志太吵 → 降到 WARNING
logging.getLogger("mcp.client.sse").setLevel(logging.WARNING)
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ============================================================================
# Lifespan — 启动/关闭时执行
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("test08 启动中...")

    # 加载 .env
    load_dotenv(
        dotenv_path=Path(__file__).resolve().parent.parent / ".env",
        override=True,
    )
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY 未设置，请在 .env 文件中配置")
    else:
        logger.info("OpenAI API Key 已配置（%s...%s）", api_key[:8], api_key[-4:])

    # 建立 MCP 连接，发现远程工具
    logger.info("正在连接 MCP 服务器...")
    remote_tools, tool_session_map, mcp_cleanup = await setup_mcp_connections()
    app.state.all_tools = LOCAL_TOOLS + remote_tools
    app.state.tool_session_map = tool_session_map
    app.state.mcp_cleanup = mcp_cleanup
    logger.info("工具总数：%d（本地 %d + 远程 %d）",
                len(app.state.all_tools), len(LOCAL_TOOLS), len(remote_tools))

    logger.info("test08 启动完成，浏览器打开 http://localhost:8000 开始对话")
    yield  # ← 服务运行期间停在这

    # 关闭 MCP 连接
    logger.info("正在关闭 MCP 连接...")
    await app.state.mcp_cleanup()
    logger.info("test08 已关闭")


# ============================================================================
# App 创建
# ============================================================================

app = FastAPI(
    title="test08 — AI Agent Plus",
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
        "version": "0.1.0",
    }


# 挂载静态文件（聊天界面）—— 放最后，否则覆盖所有 / 请求
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


# ============================================================================
# 直接启动
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
