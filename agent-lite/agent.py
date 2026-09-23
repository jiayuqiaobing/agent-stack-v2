"""
agent-lite/agent.py

Agent 核心循环 — 非流式 + 流式（SSE）
"""

import json
import logging
from config import client, aclient, MODEL_NAME
from memory import HybridMemory
from tools_local import TOOL_REGISTRY, LOCAL_TOOLS, execute_tool
from mcp import ClientSession
from mcp.client.sse import sse_client
from observability import trace

logger = logging.getLogger(__name__)


def _format_tokens(n: int) -> str:
    """格式化 token 数：1000+ → 1.2k，1000000+ → 1.5M"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1000:
        return f"{n / 1000:.1f}k"
    else:
        return str(n)


def _format_token_line(prompt: int, completion: int) -> str:
    """生成 token 消耗汇总行"""
    total = prompt + completion
    return (
        f"\n\n---\n"
        f"[Token] 本次消耗 {_format_tokens(total)}"
        f"（输入 {_format_tokens(prompt)} 输出 {_format_tokens(completion)}）"
    )


async def agent_loop(
    user_message: str,
    memory: HybridMemory,
    tools: list | None = None,
    tool_session_map: dict | None = None,
    model: str = MODEL_NAME,
    max_steps: int = 8,
) -> str:
    """
    非流式 Agent 循环 — POST /chat 使用

    参数：
        user_message: 用户输入文本
        memory: HybridMemory 实例（含短期/长期/向量记忆）
        tools: OpenAI 工具定义列表，默认用 LOCAL_TOOLS
        tool_session_map: MCP 工具名 → session info 映射
        model: 模型名
        max_steps: 最大循环步数（防止死循环）

    返回：模型最终回复文本（或错误描述）
    """
    if tools is None:
        tools = LOCAL_TOOLS

    memory.add("user", user_message)
    await memory.maybe_summarize()

    total_prompt = 0
    total_completion = 0

    for step in range(1, max_steps + 1):
        logger.debug("Step %d/%d", step, max_steps)

        context = await memory.build_context()

        # LLM span —— cache_hit_tokens 验证 v1 的前缀缓存设计是否真的生效
        llm_span = trace.make_span("llm.chat", "llm", session_id=memory.session_id,
                                   attributes={"model": model})
        try:
            response = await aclient.chat.completions.create(
                model=model,
                messages=context,
                tools=tools or None,
                max_tokens=4096,
                temperature=0,
            )
            _usage = getattr(response, "usage", None)
            _details = getattr(_usage, "prompt_tokens_details", None) if _usage else None
            llm_span["attributes"].update({
                "prompt_tokens": getattr(_usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(_usage, "completion_tokens", 0) or 0,
                "cache_hit_tokens": getattr(_details, "cached_tokens", 0) or 0,
                "has_tool_calls": bool(response.choices[0].message.tool_calls),
            })
            trace.finish_span(llm_span, status="ok")
        except Exception as e:
            trace.finish_span(llm_span, status="error", error=e)
            raise
        finally:
            trace.export_span(llm_span)

        msg = response.choices[0].message

        if response.usage:
            total_prompt += response.usage.prompt_tokens
            total_completion += response.usage.completion_tokens

        # 模型直接回复（无工具调用）
        if not msg.tool_calls:
            content = msg.content or ""
            token_line = _format_token_line(total_prompt, total_completion)
            memory.add("assistant", content)
            return content + token_line

        # 模型发起工具调用
        memory.add_assistant_with_tool_calls(msg)

        for tc in msg.tool_calls:
            func_name = tc.function.name
            try:
                func_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                func_args = {}

            logger.info("工具调用：%s", func_name)

            # 工具 span —— name 用低基数形式 tool.{名}，参数只记长度不记内容
            is_local = func_name in TOOL_REGISTRY
            tool_span = trace.make_span(
                f"tool.{func_name}", "tool",
                attributes={
                    "tool_name": func_name,
                    "source": "local" if is_local else ("mcp" if tool_session_map else "unknown"),
                    "args_size": len(str(func_args)),
                },
            )

            # 路由：本地工具 > MCP 远程工具
            try:
                if is_local:
                    result = await execute_tool(func_name, func_args)
                elif tool_session_map and func_name in tool_session_map:
                    result = await _call_mcp_tool(tool_session_map[func_name], func_name, func_args)
                else:
                    result = f"错误: 未知工具 '{func_name}'"
                ok = not str(result).startswith("错误") and not str(result).startswith("远程工具")
                tool_span["attributes"]["success"] = ok
                tool_span["attributes"]["error_type"] = None if ok else "tool_error"
                trace.finish_span(tool_span, status="ok" if ok else "error")
            except Exception as e:
                tool_span["attributes"]["success"] = False
                tool_span["attributes"]["error_type"] = type(e).__name__
                trace.finish_span(tool_span, status="error", error=e)
                raise
            finally:
                trace.export_span(tool_span)

            logger.debug("工具结果 %s：%s", func_name, str(result)[:200])
            memory.add("tool", str(result), tool_call_id=tc.id)

        # 本轮结束，继续循环（模型看到工具结果后再决策）

    # 达到最大步数
    fallback = "达到最大步数限制，请简化问题后重试。"
    token_line = _format_token_line(total_prompt, total_completion)
    memory.add("assistant", fallback)
    return fallback + token_line


async def agent_loop_stream(
    user_message: str,
    memory: HybridMemory,
    tools: list | None = None,
    tool_session_map: dict | None = None,
    model: str = MODEL_NAME,
    max_steps: int = 8,
):
    """
    流式 Agent 循环 — POST /chat/stream 使用（SSE）

    返回类型：AsyncGenerator[dict, None]
    每次 yield 的字典结构：
        {"type": "delta", "content": "..."}          — 文本片段
        {"type": "tool_call", "name": "...", "args": "..."}  — 工具调用
        {"type": "done", "reply": "..."}             — 完成
        {"type": "error", "message": "..."}          — 错误
    """
    if tools is None:
        tools = LOCAL_TOOLS

    memory.add("user", user_message)
    await memory.maybe_summarize()

    total_prompt = 0
    total_completion = 0

    for step in range(1, max_steps + 1):
        logger.debug("Step %d/%d（流式）", step, max_steps)

        context = await memory.build_context()

        stream = await aclient.chat.completions.create(
            model=model,
            messages=context,
            tools=tools or None,
            max_tokens=4096,
            temperature=0,
            stream=True,
            stream_options={"include_usage": True},
        )

        # 流式收集 — 跟 test06 同逻辑，但用 async for + 逐 chunk yield
        collected_content = ""
        collected_tool_calls: list[dict] = []
        stream_usage = None

        async for chunk in stream:
            if chunk.usage:
                stream_usage = chunk.usage

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if delta is None:
                continue

            # 文本 delta → 即时推送
            if delta.content:
                collected_content += delta.content
                yield {"type": "delta", "content": delta.content}

            # 工具调用 delta → 按 index 拼接
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    while len(collected_tool_calls) <= idx:
                        collected_tool_calls.append(
                            {"id": "", "function": {"name": "", "arguments": ""}}
                        )
                    tc = collected_tool_calls[idx]
                    if tc_delta.id:
                        tc["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc["function"]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc["function"]["arguments"] += tc_delta.function.arguments

        if stream_usage:
            total_prompt += stream_usage.prompt_tokens
            total_completion += stream_usage.completion_tokens

        # 流式收集完毕 — 判断是否工具调用
        if collected_tool_calls and collected_tool_calls[0]["function"]["name"]:
            # 工具调用轮次
            assistant_msg = {
                "role": "assistant",
                "content": collected_content or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": tc["function"],
                    }
                    for tc in collected_tool_calls
                ],
            }
            memory.short_term.append(assistant_msg)

            for tc in collected_tool_calls:
                func_name = tc["function"]["name"]
                try:
                    func_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    func_args = {}

                yield {"type": "tool_call", "name": func_name, "args": tc["function"]["arguments"]}

                # 工具 span（流式路径）—— 与非流式保持同一契约
                is_local = func_name in TOOL_REGISTRY
                tool_span = trace.make_span(
                    f"tool.{func_name}", "tool", session_id=memory.session_id,
                    attributes={
                        "tool_name": func_name,
                        "source": "local" if is_local else ("mcp" if tool_session_map else "unknown"),
                        "args_size": len(tc["function"]["arguments"] or ""),
                    },
                )
                try:
                    if is_local:
                        result = await execute_tool(func_name, func_args)
                    elif tool_session_map and func_name in tool_session_map:
                        result = await _call_mcp_tool(tool_session_map[func_name], func_name, func_args)
                    else:
                        result = f"错误: 未知工具 '{func_name}'"
                    ok = not str(result).startswith("错误") and not str(result).startswith("远程工具")
                    tool_span["attributes"]["success"] = ok
                    tool_span["attributes"]["error_type"] = None if ok else "tool_error"
                    trace.finish_span(tool_span, status="ok" if ok else "error")
                except Exception as e:
                    tool_span["attributes"]["success"] = False
                    tool_span["attributes"]["error_type"] = type(e).__name__
                    trace.finish_span(tool_span, status="error", error=e)
                    raise
                finally:
                    trace.export_span(tool_span)

                memory.add("tool", str(result), tool_call_id=tc["id"])

            # 本轮结束，继续循环（模型看到工具结果再回答）
        else:
            # 模型直接回复
            if collected_content:
                memory.add("assistant", collected_content)
            token_line = _format_token_line(total_prompt, total_completion)
            yield {"type": "delta", "content": token_line}
            yield {"type": "done", "reply": collected_content}
            return

    # 达到最大步数
    fallback = "达到最大步数限制，请简化问题后重试。"
    token_line = _format_token_line(total_prompt, total_completion)
    memory.add("assistant", fallback)
    yield {"type": "delta", "content": token_line}
    yield {"type": "done", "reply": fallback}


# ============================================================================
# MCP 工具调用（从 test06 搬）
# ============================================================================

async def _call_mcp_tool(info: dict, func_name: str, func_args: dict) -> str:
    """调用 MCP 工具，SSE 连接断开时自动重连一次"""
    try:
        result_obj = await info["session"].call_tool(func_name, func_args)
        return result_obj.content[0].text
    except Exception as e:
        if info.get("type") != "sse":
            return f"远程工具 '{func_name}' 调用失败: {type(e).__name__} {e}".strip()

        # SSE 断线重连
        logger.warning("MCP SSE 断线，尝试重连：%s", info["url"])
        try:
            async with sse_client(info["url"]) as (r, w):
                async with ClientSession(r, w) as new_session:
                    await new_session.initialize()
                    result_obj = await new_session.call_tool(func_name, func_args)
                    info["session"] = new_session
                    return result_obj.content[0].text
        except Exception as e2:
            return f"远程工具 '{func_name}' 重连后仍失败: {type(e2).__name__} {e2}".strip()
