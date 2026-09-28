"""把一个复杂要求拆到不能再分，最后给出固定结构。

模型先自己填。某一项答不好时，才让用户在给定选项里选，或自己写。
结构给别的项目用，所以字段名不能随口改。
"""

import json
import logging
from runtime.planner.prompts import build_plan_hint
from runtime.planner.templates import template_for

logger = logging.getLogger(__name__)

BRIEF = {
    "type": "function",
    "function": {
        "name": "make_brief",
        "description": "先读本会话里用户已经说过的话，再在一次调用中完整提供 goal 和 items。至少 12 条；每条都必须有 need、ask 和至少两个 options，options 第一项是结合用户偏好的可直接执行默认项，不能只写「需要」或「经典」。不能省略 items。",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "need": {"type": "string"},
                            "value": {"type": "string"},
                            "ask": {"type": "string"},
                            "options": {"type": "array", "items": {"type": "string"}},
                            "visible": {"type": "boolean"},
                            "area": {"type": "string"},
                            "hidden_detail": {"type": "string"},
                            "acceptance": {"type": "string"},
                            "query_needed": {"type": "string"},
                        },
                        "required": ["id", "need"],
                    },
                },
                "notes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需要用户自己申请许可或付费、这里过不去的关卡。每条写在哪一步、要做什么。",
                },
                "query_requests": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需要后续查询端寻找真实网页资源的事项；当前只标记待查询，不要伪造网址。",
                },
            },
            "required": ["goal", "items"],
        },
    },
}


def _leaf_too_wide(text: str) -> bool:
    raw = text or ""
    return ("和" in raw and "以及" in raw) or raw.count("，") >= 4


def _is_simple_life_task(goal: str) -> bool:
    return any(word in (goal or "") for word in ("怎么做", "怎样做", "怎么煮", "怎么炒", "食谱", "做菜", "教程")) and not any(
        word in (goal or "") for word in ("网页", "网站", "项目", "软件", "系统")
    )


def render_brief(data: dict) -> str:
    goal = str(data.get("goal") or "").strip() or "未命名"
    template = template_for(goal)
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if not items:
        return "错误: 结构里没有条目"
    visible_decisions = []
    hidden_details = []
    query_requests = [str(item).strip() for item in (data.get("query_requests") or []) if str(item).strip()]
    resource_requests = [item for item in (data.get("resource_requests") or []) if isinstance(item, dict)]
    acceptance_cases = []
    legacy_asks = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        need = str(item.get("need") or "").strip()
        value = str(item.get("value") or "").strip()
        ask = str(item.get("ask") or "").strip()
        options = [str(x).strip() for x in (item.get("options") or []) if str(x).strip()][:3]
        if value and _leaf_too_wide(value):
            return f"错误: 第 {index} 条还能再拆。一条只写一件事，例如「页面1需要登录」。"
        if len(options) < 2:
            return f"错误: 第 {index} 条至少给两个选项，第一项是默认"
        if not ask:
            ask = need
        if len(options[0]) < 8:
            return f"错误: 第 {index} 条的默认项太短。要写成照着做不会停住的一步，例如「页面1先显示9乘9的格子，点开会翻开，长按插旗」。"
        area = str(item.get("area") or "未分类").strip()
        detail = str(item.get("hidden_detail") or value or ask).strip()
        acceptance_text = str(item.get("acceptance") or "完成后能观察到该结果，并能按步骤复核").strip()
        query_needed = str(item.get("query_needed") or "").strip()
        if query_needed:
            query_requests.append(query_needed)
            resource_requests.append({
                "id": f"resource-{index}",
                "topic": query_needed,
                "why": "需要外部真实资料确认该步骤",
                "search_keywords": [query_needed],
                "resource_types": ["成熟网站", "官方文档", "实际案例"],
                "compare": [acceptance_text],
                "return": ["真实网址", "可借鉴内容", "访问状态"],
                "status": "pending",
            })
        visible_limit = 12 if _is_simple_life_task(goal) else 6
        visible = item.get("visible") if isinstance(item.get("visible"), bool) else index <= visible_limit
        record = {"id": str(item.get("id") or f"item-{index}"), "question": ask, "options": options, "default_index": 0}
        legacy_asks.append({"ask": ask, "options": options})
        if visible:
            visible_decisions.append(record)
        else:
            hidden_details.append({
                "id": record["id"],
                "area": area,
                "decision": detail,
                "reason": str(item.get("reason") or "根据会话需求和默认方案自动确定").strip(),
                "acceptance": acceptance_text,
            })
        acceptance_cases.append({
            "id": f"accept-{index}",
            "for": record["id"],
            "type": "functional",
            "test": acceptance_text,
            "expected": acceptance_text,
            "method": "manual_or_browser",
            "severity": "must_pass",
        })
    if len(legacy_asks) < 12:
        return "错误: 至少 12 条。页面结构、每页做什么、外观、操作、输赢、重来、不会做的地方，都要分开。默认项要能直接做。"
    notes = [str(item).strip() for item in (data.get("notes") or []) if str(item).strip()]
    query_requests = list(dict.fromkeys(query_requests))
    payload = json.dumps({
        "version": "2.0",
        "goal": goal,
        "task_type": template["name"],
        "visible_decisions": visible_decisions,
        "hidden_details": hidden_details,
        "query_requests": [{"request": item, "status": "pending"} for item in query_requests],
        "resource_requests": resource_requests,
        "acceptance": acceptance_cases,
        "assumptions": ["未明确的视觉、命名和实现细节采用默认方案"],
        "asks": legacy_asks,
        "notes": notes,
        "review": data.get("review", {"status": "pending", "score": None, "issues": []}),
    }, ensure_ascii=False)
    return "BRIEF_FORM\n" + payload


def make_brief(args: dict | None) -> str:
    data = args if isinstance(args, dict) else {}
    if not isinstance(data.get("items"), list):
        return "错误: make_brief 参数不完整。请在同一次工具调用中提供 goal 和 items 数组；items 至少12条，每条含 need、ask、options，options第一项是具体默认步骤。不要直接回答用户。"
    try:
        if isinstance(data.get("items"), str):
            data["items"] = json.loads(data["items"])
    except json.JSONDecodeError:
        return "错误: items 不是合法 JSON"
    return render_brief(data)


def fallback_brief(goal: str) -> str:
    """恢复模型也失败时的确定性结构，保证计划模式不以工具错误结束。"""
    subject = (goal or "当前任务").strip()[:120] or "当前任务"
    if _is_simple_life_task(subject):
        topics = [
            ("准备食材", f"准备{subject}需要的主要食材，并按人数估算用量"),
            ("处理食材", "把需要清洗和切配的食材处理成适合下锅的大小"),
            ("开火准备", "先把锅烧热并准备好油、调味料和盛菜容器"),
            ("先处理主料", "先把需要更久才能熟的食材下锅，炒到合适的熟度"),
            ("控制火候", "根据食材状态调整火力，避免外面焦了而里面没熟"),
            ("分批下锅", "按熟成时间分批加入食材，不把所有材料同时倒入"),
            ("调味时机", "在主要食材基本熟透后加入调味料，先少量再按口味补充"),
            ("判断完成", "通过颜色、气味、软硬度和中心温度判断是否熟透"),
            ("摆盘装盘", "关火后立即装盘，保留适合食用的温度和形态"),
            ("安全提醒", "处理生食后清洁刀具、案板和手，避免交叉污染"),
            ("失败处理", "如果过咸、过生或过焦，分别采用稀释、继续加热或重新制作"),
            ("最终检查", "确认分量、熟度、味道和摆盘都符合这次用餐需求"),
        ]
    else:
        topics = [
        ("目标范围", f"先明确{subject}要解决的核心问题、服务对象和完成边界"),
        ("页面结构", "先确定入口页、主要内容页和结果页，并规定页面之间的进入顺序"),
        ("核心功能", "先实现用户完成主要任务所需的最小功能，再处理扩展功能"),
        ("主要操作", "为每个核心功能规定用户点击、输入、返回和失败后的下一步"),
        ("状态反馈", "每个耗时操作显示进行中、成功和失败三种状态，并保留可理解的错误原因"),
        ("视觉层级", "用一个主色、一个强调色和中性背景区分主要操作、次要操作和内容区域"),
        ("响应布局", "桌面端保持主内容清晰，窄屏时内容缩放并保证主要按钮仍可操作"),
        ("空状态", "没有数据或首次进入时显示下一步说明，不显示空白页面"),
        ("错误恢复", "失败时保留用户输入和当前状态，提供重试或返回上一步"),
        ("数据边界", "明确哪些数据必须保存、哪些只在当前操作中使用，并限制不必要的输入"),
        ("验收路径", "按正常流程、空输入、错误输入、重复操作和窄屏场景逐项检查"),
        ("交付结果", "最后整理页面清单、功能清单、默认选择和未解决附加信息"),
        ]
    asks = [{
        "id": str(index + 1),
        "need": name,
        "ask": name,
        "area": "兜底",
        "hidden_detail": detail,
        "acceptance": detail,
        "visible": index < (12 if _is_simple_life_task(subject) else 6),
        "options": [detail, "由用户改成其他做法"],
    } for index, (name, detail) in enumerate(topics)]
    visible = []
    hidden = []
    for item in asks:
        record = {
            "id": item["id"],
            "question": item["ask"],
            "options": item["options"],
            "default_index": 0,
        }
        if item["visible"]:
            visible.append(record)
        else:
            hidden.append({
                "id": item["id"],
                "area": item["area"],
                "decision": item["hidden_detail"],
                "reason": "确定性兜底方案",
                "acceptance": item["acceptance"],
            })
    payload = {
        "version": "2.0",
        "goal": subject,
        "visible_decisions": visible,
        "hidden_details": hidden,
        "query_requests": [],
        "assumptions": ["未明确的细节采用保守默认"],
        "asks": asks,
        "notes": ["计划恢复模型不可用，以上为保守兜底结构；需要外部许可或付费的事项尚未确认。"],
        "review": {"status": "fallback", "score": None, "issues": ["未完成模型复核"]},
    }
    return "BRIEF_FORM\n" + json.dumps(payload, ensure_ascii=False)


def _parse_review(text: str) -> dict | None:
    raw = (text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        result = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(result, dict):
        return None
    try:
        score = int(result.get("score"))
    except (TypeError, ValueError):
        return None
    items = result.get("items")
    if not isinstance(items, list):
        return None
    return {
        "score": max(0, min(100, score)),
        "issues": [str(issue) for issue in result.get("issues", []) if str(issue).strip()],
        "items": items,
        "notes": result.get("notes", []),
    }


def _parse_score(text: str) -> dict | None:
    raw = (text or "").strip().strip("`")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(raw[start:end + 1])
        score = max(0, min(100, int(payload.get("score"))))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return {
        "score": score,
        "issues": [str(issue) for issue in payload.get("issues", []) if str(issue).strip()],
    }


async def review_brief(draft_text: str, history: list, llm, model: str) -> str:
    """独立审查并重写一次，再独立评分；复核不可用时不伪造分数。"""
    prefix, _, raw = (draft_text or "").partition("\n")
    if prefix != "BRIEF_FORM":
        return draft_text
    try:
        draft = json.loads(raw)
    except json.JSONDecodeError:
        return draft_text

    conversation = [
        {"role": msg.get("role"), "content": str(msg.get("content") or "")}
        for msg in history[-24:]
        if isinstance(msg, dict) and msg.get("role") in {"user", "assistant"}
        and isinstance(msg.get("content"), str) and msg.get("content")
    ]
    system = (
        "你是独立的需求计划审查员。先读会话，尤其是用户已经表达的偏好和目标；不得把已明确的信息再次设为问题。"
        "检查页面/功能覆盖、顺序、单项是否可执行、默认是否合理、选项是否有帮助、是否遗漏关键障碍。"
        "合并重复项，补足缺项；第一选项必须是结合会话线索后最适合直接实施的默认。"
        "只输出 JSON：{\"score\":0到100整数,\"issues\":[\"具体缺口\"],\"items\":[{\"id\":\"1\",\"need\":\"...\",\"ask\":\"...\",\"options\":[\"默认，具体可执行\",\"替代项\"]}],\"notes\":[\"仅列必须用户自行申请许可或付费的关卡\"]}。"
        "至少12项。禁止代码。"
    )
    current = draft
    review = None
    try:
        messages = [{"role": "system", "content": system}]
        messages.extend(conversation)
        messages.append({"role": "user", "content": json.dumps(draft, ensure_ascii=False)})
        response = await llm.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            max_tokens=5000,
        )
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise ValueError("复核模型未返回 choices")
        review = _parse_review(getattr(choices[0].message, "content", ""))
        if review is None:
            raise ValueError("复核模型返回格式无效")
        current = {
            "version": 1,
            "goal": str(draft.get("goal") or "未命名"),
            "items": review["items"],
            "notes": review["notes"],
        }
    except Exception as exc:
        logger.warning("计划复核失败，保留原始草稿：%s", type(exc).__name__)
        # draft_text 已经是合法 BRIEF_FORM；不能再把 asks 当 items 重渲染。
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return draft_text
        data["review"] = {
            "status": "unavailable",
            "score": None,
            "issues": ["自动复核暂不可用，以上为未复核草稿"],
        }
        return "BRIEF_FORM\n" + json.dumps(data, ensure_ascii=False)

    checked = render_brief(current)
    if not checked.startswith("BRIEF_FORM"):
        return checked
    final_data = json.loads(checked[len("BRIEF_FORM"):])
    score_system = (
        "你是计划质量评分员。结合完整会话和计划，按五项各20分评分：需求覆盖、默认可执行、条目单一明确、实施顺序完整、阻碍与许可识别。"
        "只输出 JSON：{\"score\":整数0到100,\"issues\":[\"具体遗漏或障碍\"]}。不要重写计划。"
    )
    score_messages = [{"role": "system", "content": score_system}]
    score_messages.extend(conversation)
    score_messages.append({"role": "user", "content": json.dumps(final_data, ensure_ascii=False)})
    score_result = {"score": None, "issues": ["最终质量评分不可用"]}
    try:
        response = await llm.chat.completions.create(
            model=model,
            messages=score_messages,
            temperature=0,
            max_tokens=800,
        )
        choices = getattr(response, "choices", None) or []
        if choices:
            parsed = _parse_score(getattr(choices[0].message, "content", ""))
            if parsed:
                score_result = parsed
    except Exception as exc:
        logger.warning("计划最终评分失败：%s", type(exc).__name__)
        score_result = {"score": None, "issues": ["最终质量评分不可用"]}
    final_data["review"] = {
        "status": "reviewed" if score_result["score"] is not None and score_result["score"] >= 85 else "needs_attention",
        "score": score_result["score"],
        "issues": score_result["issues"],
        "passes": 2,
    }
    return "BRIEF_FORM\n" + json.dumps(final_data, ensure_ascii=False)


async def recover_brief(history: list, llm, model: str) -> str:
    """工具参数损坏时的单次恢复，不再依赖模型再次正确发起工具调用。"""
    messages = [
        {
            "role": "system",
            "content": (
                "你是计划结构恢复器。根据会话内容生成完整 JSON，不要解释，不要代码。"
                "必须包含 goal、items、notes。items 至少12条；每条含 id、need、ask、options，"
                "options 至少两项，第一项是具体可执行默认。只输出 JSON。"
            ),
        }
    ]
    messages.extend(
        {"role": msg.get("role"), "content": str(msg.get("content") or "")}
        for msg in history[-24:]
        if isinstance(msg, dict) and msg.get("role") in {"user", "assistant"}
        and msg.get("content")
    )
    response = await llm.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=5000,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        return "错误: 计划恢复失败，模型没有返回内容"
    raw = getattr(choices[0].message, "content", "") or ""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return "错误: 计划恢复失败，模型返回格式无效"
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return "错误: 计划恢复失败，模型返回格式无效"
    return make_brief(data)
