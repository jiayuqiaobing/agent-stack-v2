"""按项目类型和阶段组装短提示，避免把所有模板全文塞入每一轮。"""

from runtime.planner.templates import template_for


def build_plan_hint(user_text: str, phase: str) -> str:
    template = template_for(user_text)
    sections = "、".join(template["required_sections"])
    checks = "；".join(template["checks"])
    return (
        f"项目类型：{template['label']}（{template['name']}）。"
        f"当前阶段：{phase}。"
        f"必须覆盖：{sections}。"
        f"重点检查：{checks}。"
        "用户已明确的偏好直接成为默认，不再询问；只有改变整体路线或需要许可/付费才列为可见决策。"
        "网页任务必须区分静态检查与真实浏览器验收；游戏任务必须写坐标系、状态机、不变量、规则数据和可重复测试步骤。"
    )
