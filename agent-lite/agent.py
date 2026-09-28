"""
agent-lite/agent.py

Agent 核心循环 — 非流式 + 流式（SSE）
"""

import json
import logging
from config import aclient, MODEL_NAME
from memory import HybridMemory
from tools_local import LOCAL_TOOLS
from runtime.assist import prepare_turn
from runtime.phase import Phase, phase_hint
from runtime.planner.prompts import build_plan_hint
from runtime.registry import ToolRegistry
from runtime.brief import fallback_brief, recover_brief, review_brief
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
    llm=None,
    temperature: float = 0,
    stop: str | None = None,
    max_tokens: int = 4096,
    max_steps: int = 8,
    attachments: list | None = None,
    mode: str | None = None,
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
    logger.info("agent turn start session=%s mode=%s model=%s", memory.session_id, mode or "chat", model)
    from runtime.ingest import can_see_images, has_image, prepare_attachments
    if has_image(attachments) and not can_see_images(model):
        memory.turn_images = []
        return "当前模型不能看图片，图片没有发送。请换成带视觉的模型，例如 gpt-4o-mini。"
    packed = prepare_attachments(attachments)
    if packed["text"]:
        user_message = (user_message or "").rstrip() + "\n\n" + packed["text"]
    memory.turn_images = packed["images"] if can_see_images(model) else []
    plan = prepare_turn(user_message, tools, tool_session_map, memory, mode)
    user_message = plan["text"]
    if not user_message:
        return "没有收到内容。"
    if plan["note"]:
        memory.extra_system = ((getattr(memory, "extra_system", "") or "") + "\n\n" + plan["note"]).strip()
    if mode == "plan":
        memory.extra_system = ((getattr(memory, "extra_system", "") or "") + "\n\n" + build_plan_hint(user_message, "计划拆解")).strip()

    memory.add("user", user_message)
    await memory.maybe_summarize()

    phase = Phase.RECEIVE
    logger.info("阶段 %s session=%s tools=%d", phase.value, memory.session_id, len(plan["tools"]))
    registry = ToolRegistry(plan["tools"], tool_session_map, _call_mcp_tool)
    plan_mode = "make_brief" in [item["function"]["name"] for item in plan["tools"]]
    logger.info("阶段 %s：信息够，进入工具 session=%s", Phase.TOOL.value, memory.session_id)
    phase = Phase.TOOL

    total_prompt = 0
    total_completion = 0
    executed_names: set[str] = set()

    for step in range(1, max_steps + 1):
        logger.debug("Step %d/%d 阶段 %s", step, max_steps, phase.value)

        memory.phase_hint = phase_hint(phase, plan_mode)
        context = await memory.build_context()
        _attach_images(context, getattr(memory, "turn_images", None))

        # LLM span —— cache_hit_tokens 验证 v1 的前缀缓存设计是否真的生效
        llm_span = trace.make_span("llm.chat", "llm", session_id=memory.session_id,
                                   attributes={"model": model})
        try:
            response = await (llm or aclient).chat.completions.create(
                model=model,
                messages=context,
                tools=registry.exposed() or None,
                tool_choice="auto",
                max_tokens=max_tokens,
                temperature=temperature,
                **({"stop": stop} if stop else {}),
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

        msg = _message_or_none(response)
        if msg is None:
            logger.warning("模型返回没有 choices session=%s", memory.session_id)
            fallback = "模型没有返回内容，请重试。"
            memory.add("assistant", fallback)
            return fallback

        if response.usage:
            total_prompt += response.usage.prompt_tokens
            total_completion += response.usage.completion_tokens

        # 模型直接回复（无工具调用）
        if not msg.tool_calls:
            phase = Phase.ANSWER
            memory.phase_hint = phase_hint(phase, False)
            logger.info("阶段 %s session=%s", phase.value, memory.session_id)
            content = _strip_code(msg.content or "")
            token_line = _format_token_line(total_prompt, total_completion)
            memory.add("assistant", content)
            return content + token_line

        # 模型发起工具调用
        memory.add_assistant_with_tool_calls(msg)

        for tc in msg.tool_calls:
            func_name = tc.function.name
            duplicate_tool = plan_mode and func_name in executed_names
            executed_names.add(func_name)
            try:
                func_args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                func_args = {}
            if not isinstance(func_args, dict):
                func_args = {}

            logger.info("阶段 %s 工具 %s 来源 %s", Phase.TOOL.value, func_name, registry.source_of(func_name))

            # 工具 span —— name 用低基数形式 tool.{名}，参数只记长度不记内容
            source = registry.source_of(func_name)
            tool_span = trace.make_span(
                f"tool.{func_name}", "tool",
                attributes={
                    "tool_name": func_name,
                    "source": source,
                    "phase": Phase.TOOL.value,
                    "args_size": len(str(func_args)),
                },
            )

            try:
                result = (
                    "信息: 该轮已调用过此类工具，跳过重复执行。"
                    if duplicate_tool
                    else await registry.call(func_name, func_args)
                )
                ok = not str(result).startswith("错误") and not str(result).startswith("远程工具")
                if not ok:
                    memory.reflections.append(f"{func_name} 失败：{str(result)[:120]}")
                    logger.warning("工具失败 %s session=%s", func_name, memory.session_id)
                else:
                    logger.info("工具成功 %s session=%s", func_name, memory.session_id)
                tool_span["attributes"]["success"] = ok
                tool_span["attributes"]["error_type"] = None if ok else "tool_error"
                trace.finish_span(tool_span, status="ok" if ok else "error")
            except Exception as e:
                result = f"错误: 工具 '{func_name}' 执行失败: {type(e).__name__}"
                memory.reflections.append(f"{func_name} 失败：{type(e).__name__}")
                logger.warning("工具异常 %s session=%s err=%s", func_name, memory.session_id, type(e).__name__)
                tool_span["attributes"]["success"] = False
                tool_span["attributes"]["error_type"] = type(e).__name__
                trace.finish_span(tool_span, status="error", error=e)
            finally:
                trace.export_span(tool_span)

            logger.debug("工具结果 %s duplicate=%s：%s", func_name, duplicate_tool, str(result)[:200])
            memory.add("tool", str(result), tool_call_id=tc.id)
            phase = Phase.ANSWER
            if func_name == "make_brief" and str(result).startswith("错误"):
                try:
                    recovered = await recover_brief(memory.short_term, llm or aclient, model)
                except Exception as exc:
                    logger.warning("计划恢复失败：%s", type(exc).__name__)
                    recovered = str(result)
                if recovered.startswith("BRIEF_FORM"):
                    try:
                        recovered = await review_brief(recovered, memory.short_term, llm or aclient, model)
                    except Exception as exc:
                        logger.warning("计划复核失败，使用恢复结果：%s", type(exc).__name__)
                    memory.add("assistant", recovered)
                    return recovered + _format_token_line(total_prompt, total_completion)
                recovered = fallback_brief(user_message)
                memory.add("assistant", recovered)
                return recovered + _format_token_line(total_prompt, total_completion)
            if func_name == "make_brief" and str(result).startswith("BRIEF_FORM"):
                try:
                    reviewed = await review_brief(str(result), memory.short_term, llm or aclient, model)
                except Exception as exc:
                    logger.warning("计划复核失败，使用原始结构：%s", type(exc).__name__)
                    reviewed = str(result)
                memory.add("assistant", reviewed)
                return reviewed + _format_token_line(total_prompt, total_completion)

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
    llm=None,
    temperature: float = 0,
    stop: str | None = None,
    max_tokens: int = 4096,
    max_steps: int = 8,
    attachments: list | None = None,
    mode: str | None = None,
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
    logger.info("agent stream start session=%s mode=%s model=%s", memory.session_id, mode or "chat", model)
    from runtime.ingest import can_see_images, has_image, prepare_attachments
    if has_image(attachments) and not can_see_images(model):
        memory.turn_images = []
        notice = "当前模型不能看图片，图片没有发送。请换成带视觉的模型，例如 gpt-4o-mini。"
        yield {"type": "error", "message": notice}
        return
    packed = prepare_attachments(attachments)
    if packed["text"]:
        user_message = (user_message or "").rstrip() + "\n\n" + packed["text"]
    memory.turn_images = packed["images"] if can_see_images(model) else []
    plan = prepare_turn(user_message, tools, tool_session_map, memory, mode)
    user_message = plan["text"]
    if not user_message:
        yield {"type": "error", "message": "没有收到内容。"}
        return
    if plan["note"]:
        memory.extra_system = ((getattr(memory, "extra_system", "") or "") + "\n\n" + plan["note"]).strip()

    memory.add("user", user_message)
    await memory.maybe_summarize()

    phase = Phase.RECEIVE
    logger.info("阶段 %s session=%s tools=%d", phase.value, memory.session_id, len(plan["tools"]))
    yield {"type": "status", "phase": "receive", "text": "正在接收"}
    registry = ToolRegistry(plan["tools"], tool_session_map, _call_mcp_tool)
    plan_mode = "make_brief" in [item["function"]["name"] for item in plan["tools"]]
    logger.info("阶段 %s：信息够，进入工具 session=%s", Phase.TOOL.value, memory.session_id)
    phase = Phase.TOOL
    yield {"type": "status", "phase": "tool", "text": "正在查资料"}

    total_prompt = 0
    total_completion = 0
    executed_names: set[str] = set()

    for step in range(1, max_steps + 1):
        logger.debug("Step %d/%d（流式）阶段 %s", step, max_steps, phase.value)

        memory.phase_hint = phase_hint(phase, plan_mode)
        context = await memory.build_context()
        _attach_images(context, getattr(memory, "turn_images", None))

        # LLM span（流式路径）—— 与非流式保持同一契约
        llm_span = trace.make_span("llm.chat", "llm", session_id=memory.session_id,
                                   attributes={"model": model})
        try:
            stream = await (llm or aclient).chat.completions.create(
                model=model,
                messages=context,
                tools=registry.exposed() or None,
                tool_choice="auto",
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                **({"stop": stop} if stop else {}),
                stream_options={"include_usage": True},
            )
            trace.finish_span(llm_span, status="ok")
        except Exception as e:
            trace.finish_span(llm_span, status="error", error=e)
            trace.export_span(llm_span)
            raise

        # 流式收集 — 跟 test06 同逻辑，但用 async for + 逐 chunk yield
        collected_content = ""
        collected_reasoning = ""
        collected_tool_calls: list[dict] = []
        stream_usage = None

        try:
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    stream_usage = chunk.usage

                if not getattr(chunk, "choices", None):
                    continue

                delta = chunk.choices[0].delta
                if delta is None:
                    continue

                reasoning = getattr(delta, "reasoning_content", None) or ""
                if reasoning:
                    collected_reasoning += reasoning

                if delta.content:
                    collected_content += delta.content
                    yield {"type": "delta", "content": delta.content}

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
        except Exception as e:
            logger.warning("流式中断 session=%s err=%s", memory.session_id, type(e).__name__)
            yield {"type": "error", "message": "回复中断，请重试。"}
            return

        if stream_usage:
            total_prompt += stream_usage.prompt_tokens or 0
            total_completion += stream_usage.completion_tokens or 0
            yield {
                "type": "usage",
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
            }

        # 流结束 —— 补齐 llm span 的 token 数据
        _details = getattr(stream_usage, "prompt_tokens_details", None) if stream_usage else None
        llm_span["attributes"].update({
            "prompt_tokens": getattr(stream_usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(stream_usage, "completion_tokens", 0) or 0,
            "cache_hit_tokens": getattr(_details, "cached_tokens", 0) or 0,
            "has_tool_calls": bool(collected_tool_calls and collected_tool_calls[0]["function"]["name"]),
        })
        trace.export_span(llm_span)

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
            if collected_reasoning:
                assistant_msg["reasoning_content"] = collected_reasoning
            memory.short_term.append(assistant_msg)

            for tc in collected_tool_calls:
                func_name = tc["function"]["name"]
                duplicate_tool = plan_mode and func_name in executed_names
                executed_names.add(func_name)
                try:
                    func_args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    func_args = {}
                if not isinstance(func_args, dict):
                    func_args = {}

                logger.info("阶段 %s 工具 %s 来源 %s duplicate=%s", Phase.TOOL.value, func_name, registry.source_of(func_name), duplicate_tool)
                if not duplicate_tool:
                    yield {"type": "tool_call", "name": func_name, "args": tc["function"]["arguments"]}

                # 工具 span（流式路径）—— 与非流式保持同一契约
                source = registry.source_of(func_name)
                tool_span = trace.make_span(
                    f"tool.{func_name}", "tool", session_id=memory.session_id,
                    attributes={
                        "tool_name": func_name,
                        "source": source,
                        "phase": Phase.TOOL.value,
                        "args_size": len(tc["function"]["arguments"] or ""),
                    },
                )
                try:
                    result = (
                        "信息: 该轮已调用过此类工具，跳过重复执行。"
                        if duplicate_tool
                        else await registry.call(func_name, func_args)
                    )
                    ok = not str(result).startswith("错误") and not str(result).startswith("远程工具")
                    if not ok:
                        memory.reflections.append(f"{func_name} 失败：{str(result)[:120]}")
                        logger.warning("工具失败 %s session=%s", func_name, memory.session_id)
                    else:
                        logger.info("工具成功 %s session=%s", func_name, memory.session_id)
                    tool_span["attributes"]["success"] = ok
                    tool_span["attributes"]["error_type"] = None if ok else "tool_error"
                    trace.finish_span(tool_span, status="ok" if ok else "error")
                except Exception as e:
                    result = f"错误: 工具 '{func_name}' 执行失败: {type(e).__name__}"
                    memory.reflections.append(f"{func_name} 失败：{type(e).__name__}")
                    logger.warning("工具异常 %s session=%s err=%s", func_name, memory.session_id, type(e).__name__)
                    tool_span["attributes"]["success"] = False
                    tool_span["attributes"]["error_type"] = type(e).__name__
                    trace.finish_span(tool_span, status="error", error=e)
                finally:
                    trace.export_span(tool_span)

                memory.add("tool", str(result), tool_call_id=tc["id"])
                phase = Phase.ANSWER
                if func_name == "make_brief" and str(result).startswith("错误"):
                    try:
                        recovered = await recover_brief(memory.short_term, llm or aclient, model)
                    except Exception as exc:
                        logger.warning("计划恢复失败：%s", type(exc).__name__)
                        recovered = str(result)
                    if recovered.startswith("BRIEF_FORM"):
                        try:
                            recovered = await review_brief(recovered, memory.short_term, llm or aclient, model)
                        except Exception as exc:
                            logger.warning("计划复核失败，使用恢复结果：%s", type(exc).__name__)
                        memory.add("assistant", recovered)
                        yield {"type": "status", "phase": "answer", "text": "结构已恢复并复核"}
                        yield {"type": "delta", "content": recovered}
                        yield {"type": "done", "reply": recovered}
                        return
                    recovered = fallback_brief(user_message)
                    memory.add("assistant", recovered)
                    yield {"type": "delta", "content": recovered}
                    yield {"type": "done", "reply": recovered}
                    return
                if func_name == "make_brief" and str(result).startswith("BRIEF_FORM"):
                    try:
                        reviewed = await review_brief(str(result), memory.short_term, llm or aclient, model)
                    except Exception as exc:
                        logger.warning("计划复核失败，使用原始结构：%s", type(exc).__name__)
                        reviewed = str(result)
                    memory.add("assistant", reviewed)
                    yield {"type": "status", "phase": "answer", "text": "结构已写出"}
                    yield {"type": "delta", "content": reviewed}
                    yield {"type": "done", "reply": reviewed}
                    return

            # 本轮结束，继续循环（模型看到工具结果再回答）
        else:
            phase = Phase.ANSWER
            memory.phase_hint = phase_hint(phase, False)
            logger.info("阶段 %s session=%s", phase.value, memory.session_id)
            if not collected_content and collected_reasoning:
                collected_content = collected_reasoning
            collected_content = _strip_code(collected_content)
            if collected_content:
                memory.add("assistant", collected_content)
                yield {"type": "delta", "content": collected_content}
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

def _attach_images(context: list, images: list | None) -> None:
    if not images:
        return
    for msg in reversed(context):
        if msg.get("role") != "user":
            continue
        text = msg.get("content") or ""
        if not isinstance(text, str):
            return
        msg["content"] = [{"type": "text", "text": text}] + [
            {"type": "image_url", "image_url": {"url": url}} for url in images[:4]
        ]
        return


def _strip_code(text: str) -> str:
    lines = []
    inside = False
    replaced = False
    for line in (text or "").splitlines():
        if line.strip().startswith("```"):
            inside = not inside
            if not replaced:
                lines.append("这里不写代码。")
                replaced = True
            continue
        if inside:
            continue
        if line.strip().startswith(("def ", "class ", "import ", "function ", "const ", "let ")):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _message_or_none(response):
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    return getattr(choices[0], "message", None)


async def _call_mcp_tool(info: dict, func_name: str, func_args: dict) -> str:
    """调用 MCP 工具，SSE 连接断开时自动重连一次"""
    try:
        result_obj = await info["session"].call_tool(func_name, func_args)
        content = getattr(result_obj, "content", None) or []
        if not content:
            return f"错误: 远程工具 '{func_name}' 没有返回内容"
        return getattr(content[0], "text", None) or str(content[0])
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
