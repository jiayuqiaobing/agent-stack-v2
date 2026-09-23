"""
test08/router.py

FastAPI 路由 — /chat（非流式）+ /chat/stream（SSE 流式）
"""

import json
import logging
from uuid import uuid4
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from models import ChatRequest, ChatResponse
from agent import agent_loop, agent_loop_stream
from memory import HybridMemory
from config import client
from auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter()

SYSTEM_PROMPT = """你是一个实用的 AI 助手，具备调用工具解决实际问题的能力。你的职责是准确、高效地帮助用户完成任务。

## 可用工具

| 工具 | 用途 | 何时使用 |
|------|------|---------|
| `calculate` | 数学计算（+ - * / ** 幂运算 括号） | 任何需要精确数字答案的问题 |
| `read_file` | 读取项目文件或列出目录 | 用户要求查看代码、文件内容或目录结构 |
| `get_time` | 查询当前日期和时间 | 用户问"现在几点""今天几号" |

## 工具使用规则

1. **主动调用工具，不要猜。** 能用工具回答的问题，不要凭记忆。计算结果、当前时间必须通过工具获取，不要编造。
2. **不要承诺"稍后调用"。** 如果需要工具，立即调用；如果不需要，直接回答。不存在"记下来下次调"。
3. **工具结果如实转达。** 工具返回什么就告诉用户什么，不要篡改或美化错误信息。
4. **工具参数必须合法。** `calculate` 的表达式只能是纯数学式子；`read_file` 的路径必须在项目目录内。

## 回复风格

- 简洁务实，不啰嗦，不写长篇引言和结语
- 计算结果直接给数字，不需要用 LaTeX 格式，也不要用 ** 加粗
- 中文回复
- 如果无法完成用户请求，直接说明原因"""

# ============================================================================
# Session 管理 — session_id → HybridMemory 映射
# ============================================================================

sessions: dict[str, HybridMemory] = {}


def _get_or_create_session(session_id: str | None) -> tuple[str, HybridMemory]:
    """获取已有 session 或创建新的，返回 (id, memory)"""
    if session_id and session_id in sessions:
        return session_id, sessions[session_id]

    new_id = session_id or uuid4().hex[:8]
    sessions[new_id] = HybridMemory(system_prompt=SYSTEM_PROMPT, client=client, session_id=new_id)
    logger.info("创建新 session：%s（当前共 %d 个）", new_id, len(sessions))
    return new_id, sessions[new_id]


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat(body: ChatRequest, request: Request):
    """非流式对话 — 一次性返回完整回复"""
    sid, memory = _get_or_create_session(body.session_id)
    try:
        reply = await agent_loop(
            user_message=body.message,
            memory=memory,
            tools=request.app.state.all_tools,
            tool_session_map=request.app.state.tool_session_map,
        )
        return ChatResponse(reply=reply, status="ok", session_id=sid)
    except Exception as e:
        logger.error("非流式请求失败：%s", e, exc_info=True)
        return ChatResponse(reply="", status="error", error=str(e), session_id=sid)


@router.post("/chat/stream", dependencies=[Depends(verify_api_key)])
async def chat_stream(body: ChatRequest, request: Request):
    """流式对话 — SSE 逐 token 推送"""

    sid, memory = _get_or_create_session(body.session_id)

    async def event_generator():
        try:
            # 第一条事件：告知前端 session_id
            yield f"data: {json.dumps({'type': 'session', 'session_id': sid}, ensure_ascii=False)}\n\n"

            async for event in agent_loop_stream(
                user_message=body.message,
                memory=memory,
                tools=request.app.state.all_tools,
                tool_session_map=request.app.state.tool_session_map,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("SSE 流异常：%s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲（如有）
        },
    )


# ============================================================================
# Session 管理端点（开发者调试用）
# ============================================================================


@router.get("/sessions", dependencies=[Depends(verify_api_key)])
async def list_sessions():
    """列出所有活跃 session 及统计信息"""
    return {
        "count": len(sessions),
        "sessions": [
            {"id": sid, **mem.stats()} for sid, mem in sessions.items()
        ],
    }


@router.delete("/sessions/{session_id}", dependencies=[Depends(verify_api_key)])
async def delete_session(session_id: str):
    """清空并删除指定 session"""
    if session_id not in sessions:
        return {"error": "session 不存在"}
    sessions[session_id].clear()
    del sessions[session_id]
    logger.info("删除 session：%s（剩余 %d 个）", session_id, len(sessions))
    return {"status": "ok", "remaining": len(sessions)}