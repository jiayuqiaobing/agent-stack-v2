"""
agent-lite/router.py

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
from config import client, MODEL_NAME, make_client
from auth import verify_api_key
from observability import trace
from runtime.chat_log import delete_session as delete_saved_session
from runtime.chat_log import list_sessions as list_saved_sessions
from runtime.chat_log import load_messages

logger = logging.getLogger(__name__)

router = APIRouter()

SYSTEM_PROMPT_BASE = """你是乙方执行人。不卑微，不自大，不自称名字。用户懂模型，但不懂项目细节。你的工作是把需求收成可执行的决定，不替用户写代码。

这个页面从头到尾不输出代码、命令或文件级实现。用户硬要代码时，只说明这里不写代码，并继续把需求收清楚。颜色、库、命名这类细节不要拿来问人；用户提过的线索直接写进默认结果。只有要用户自己申请许可或自己付费时，才单独问。过不去的关卡记成附加信息，不编造。

## 可用工具
{tool_table}

## 工具使用规则

1. **只有这一轮附带了工具时才调用。** 没有附带就直接回答。不要向用户解释为什么调用或不调用。需要查证的事实不要凭记忆编造。
2. **不要承诺"稍后调用"。** 如果需要工具，立即调用；如果不需要，直接回答。不存在"记下来下次调"。
3. **工具结果如实转达。** 工具返回什么就告诉用户什么，不要篡改或美化错误信息。
4. **工具参数必须合法。** 参数必须符合该工具描述的格式要求。

## 回复风格

- 简洁务实，不啰嗦，不写长篇引言和结语
- 计算结果直接给数字，不需要用 LaTeX 格式，也不要用 ** 加粗
- 中文回复
- 如果无法完成用户请求，直接说明原因"""

# ============================================================================
# 工具清单 → 提示词表格
# ============================================================================
#
# 为什么运行时生成而不是写死：
#   MCP 远程工具是在 lifespan 里通过 session.list_tools() **动态发现**的，
#   数量与名称取决于远程服务器。静态提示词必然与运行时不一致。
#   v1 就因此出过 bug：提示词只列了 3 个本地工具，模型不知道还有 weather 和远程工具。
#
# 修复见 docs/2-产品规格.md 阶段一 P0 1.5。


def build_tool_table(tools: list | None) -> str:
    """从 OpenAI 格式的工具列表生成 Markdown 表格，用于注入系统提示词

    验收标准：表格里的工具名集合 == 运行时 tools 里的工具名集合（差集为空）
    """
    if not tools:
        return "（当前无可用工具）"

    lines = ["| 工具 | 用途 |", "|------|------|"]
    for t in tools:
        func = t.get("function", {}) if isinstance(t, dict) else {}
        name = func.get("name", "?")
        desc = (func.get("description") or "").strip().replace("\n", " ")
        if len(desc) > 100:
            desc = desc[:100] + "…"
        lines.append(f"| `{name}` | {desc or '（无描述）'} |")

    return "\n".join(lines)


# ============================================================================
# Session 管理 — session_id → HybridMemory 映射
# ============================================================================

sessions: dict[str, HybridMemory] = {}


def _get_or_create_session(
    session_id: str | None, tools: list | None = None
) -> tuple[str, HybridMemory]:
    """获取已有 session 或创建新的，返回 (id, memory)

    tools: 运行时可用工具列表。用于生成与实际情况一致的工具清单提示词。
    """
    if session_id and session_id in sessions:
        return session_id, sessions[session_id]

    system_prompt = SYSTEM_PROMPT_BASE.format(tool_table=build_tool_table(tools))

    new_id = session_id or uuid4().hex[:8]
    sessions[new_id] = HybridMemory(
        system_prompt=system_prompt, client=client, session_id=new_id
    )
    sessions[new_id].persist = True
    for row in load_messages(new_id):
        sessions[new_id].short_term.append({"role": row["role"], "content": row["text"]})
    logger.info(
        "创建新 session：%s（当前共 %d 个，工具 %d 个）",
        new_id, len(sessions), len(tools or []),
    )
    return new_id, sessions[new_id]


def _request_model(model: str | None) -> str:
    """空字符串视为没选，回落到进程配置。"""
    if model and model.strip():
        return model.strip()
    return MODEL_NAME


def _endpoint(body: ChatRequest):
    """模型、供应商密钥、接口地址绑在同一次请求上。密钥不写进日志。"""
    model = _request_model(body.model)
    return model, make_client(body.api_key, body.base_url)


def _temperature(value: float | None) -> float:
    if value is None:
        return 0
    return value


def _max_tokens(value: int | None) -> int:
    if value and value > 0:
        return value
    return 4096


def _stop(value: str | None) -> str | None:
    if value and value.strip():
        return value.strip()
    return None


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat(body: ChatRequest, request: Request):
    """非流式对话 — 一次性返回完整回复"""
    sid, memory = _get_or_create_session(body.session_id, request.app.state.all_tools)
    memory.extra_system = (body.system or "").strip()
    model, llm = _endpoint(body)
    temperature = _temperature(body.temperature)
    stop = _stop(body.stop)
    max_tokens = _max_tokens(body.max_tokens)
    logger.info("chat request session=%s mode=%s model=%s attachments=%d", sid, body.mode or "chat", model, len(body.attachments or []))

    # 根 span —— 一次完整的 agent 往返（见 docs/3-可观测数据模型.md 第 5 节）
    with trace.start_trace("agent.turn", session_id=sid) as root:
        try:
            reply = await agent_loop(
                user_message=body.message,
                attachments=body.attachments,
                mode=body.mode,
                memory=memory,
                tools=request.app.state.all_tools,
                tool_session_map=request.app.state.tool_session_map,
                model=model,
                llm=llm,
                temperature=temperature,
                stop=stop,
                max_tokens=max_tokens,
            )
            trace.finish_span(root, status="ok")
            root["attributes"]["terminated_by"] = "reply"
            return ChatResponse(reply=reply, status="ok", session_id=sid)
        except Exception as e:
            logger.error("非流式请求失败：%s", e, exc_info=True)
            trace.finish_span(root, status="error", error=e)
            root["attributes"]["terminated_by"] = "error"
            return ChatResponse(reply="", status="error", error=str(e), session_id=sid)
        finally:
            # 可观测是旁路：写 span 失败绝不能影响业务返回
            trace.export_span(root)


@router.post("/chat/stream", dependencies=[Depends(verify_api_key)])
async def chat_stream(body: ChatRequest, request: Request):
    """流式对话 — SSE 逐 token 推送"""

    sid, memory = _get_or_create_session(body.session_id, request.app.state.all_tools)
    memory.extra_system = (body.system or "").strip()
    model, llm = _endpoint(body)
    temperature = _temperature(body.temperature)
    stop = _stop(body.stop)
    max_tokens = _max_tokens(body.max_tokens)
    logger.info("chat stream request session=%s mode=%s model=%s attachments=%d", sid, body.mode or "chat", model, len(body.attachments or []))

    async def event_generator():
        with trace.start_trace("agent.turn", session_id=sid) as root:
            try:
                # 第一条事件：告知前端 session_id
                yield f"data: {json.dumps({'type': 'session', 'session_id': sid}, ensure_ascii=False)}\n\n"

                async for event in agent_loop_stream(
                    user_message=body.message,
                    attachments=body.attachments,
                    mode=body.mode,
                    memory=memory,
                    tools=request.app.state.all_tools,
                    tool_session_map=request.app.state.tool_session_map,
                    model=model,
                    llm=llm,
                    temperature=temperature,
                    stop=stop,
                    max_tokens=max_tokens,
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                trace.finish_span(root, status="ok")
                root["attributes"]["terminated_by"] = "stream_end"
            except Exception as e:
                logger.error("SSE 流异常 session=%s：%s", sid, e, exc_info=True)
                trace.finish_span(root, status="error", error=e)
                root["attributes"]["terminated_by"] = "error"
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            finally:
                trace.export_span(root)

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
    saved = {row["id"]: row for row in list_saved_sessions()}
    for sid, mem in sessions.items():
        row = saved.setdefault(sid, {"id": sid, "title": "", "updated_at": ""})
        row.update(mem.stats())
    rows = list(saved.values())
    return {"count": len(rows), "sessions": rows}


@router.get("/sessions/{session_id}/messages", dependencies=[Depends(verify_api_key)])
async def session_messages(session_id: str):
    """刷新页面时取回已完成的消息。打开着的页面不走这里。"""
    return {"messages": load_messages(session_id)}


@router.delete("/sessions/{session_id}", dependencies=[Depends(verify_api_key)])
async def delete_session(session_id: str):
    """清空并删除指定 session"""
    delete_saved_session(session_id)
    memory = sessions.pop(session_id, None)
    if memory:
        memory.clear()
    logger.info("删除 session：%s（剩余 %d 个）", session_id, len(sessions))
    return {"status": "ok", "remaining": len(sessions)}
