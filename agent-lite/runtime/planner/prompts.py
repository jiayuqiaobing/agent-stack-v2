"""按项目类型、阶段和用户意图组装短提示。"""

import re

from runtime.planner.templates import template_for


def is_plan_refinement(text: str) -> bool:
    """识别对当前计划的二次拆解要求，不把它当成新项目目标。"""
    value = re.sub(r"\s+", "", text or "").lower()
    patterns = (
        r"拆(?:解)?(?:得|的)?更细",
        r"继续拆",
        r"再拆(?:一下|一遍|细)?",
        r"回问自己",
        r"细化(?:任务|计划)?",
        r"补充(?:任务|计划)?细节",
    )
    return any(re.search(pattern, value) for pattern in patterns)


def build_plan_hint(user_text: str, phase: str) -> str:
    template = template_for(user_text)
    goal = (user_text or "").strip() or "当前问题"
    if template["name"] == "unmatched":
        return (
            f"项目类型：未匹配。用户原话：{goal}。当前阶段：{phase}。"
            "没有命中网页、网页游戏、爬虫、软件或课表，禁止套用这些类型的章节。"
            "先用 web_search 和 open_page 查这句原话的成熟做法，再写只属于这句话的计划。"
            "查不到就把来源标为 pending，不要编网址，也不要借用其他任务的章节名来充数。"
            "可见标题和默认句必须写出这句原话，不能和其他问题共用。"
        )
    sections = "、".join(template["required_sections"])
    checks = "；".join(template["checks"])
    specific = ""
    if template["name"] in ("web", "web_game"):
        specific += "网页任务必须区分静态检查与真实浏览器验收。"
    if template["name"] == "web_game":
        specific += "游戏任务必须写坐标系、状态机、不变量、规则数据和可重复测试步骤。"
    return (
        f"项目类型：{template['label']}（{template['name']}）。"
        f"用户原话：{goal}。当前阶段：{phase}。"
        f"隐藏检查：{sections}。重点检查：{checks}。"
        "这些检查放进隐藏细节，不要把章节名抄成可见标题。"
        "可见项只写会改变这句原话路线的选择，默认句必须包含原话里的对象。"
        "用户已明确的偏好直接成为默认，不再询问；只有改变整体路线或需要许可/付费才列为可见决策。"
        + specific
    )


def build_refinement_hint() -> str:
    return (
        "用户正在要求细化当前会话已有计划，不是在提出新项目。"
        "读取历史中最近的计划结构，保留原目标和用户已选项；"
        "只把隐藏细节继续拆成更小、可执行、可验收的步骤。"
        "不要把‘拆得更细’当作 goal，不要回退到通用兜底模板。"
    )


def build_turn_plan_context(user_text: str) -> str:
    """生成一轮计划模式的完整提示，供流式和非流式路径共同调用。"""
    hint = build_plan_hint(user_text, "计划拆解")
    if is_plan_refinement(user_text):
        hint += "\n\n" + build_refinement_hint()
    return hint
