"""对话阶段。追问没结束之前，不进入工具和回答。"""

from enum import Enum
from runtime.planner.prompts import build_plan_hint


class Phase(str, Enum):
    RECEIVE = "receive"
    CLARIFY = "clarify"
    TOOL = "tool"
    ANSWER = "answer"
    DONE = "done"


PHASE_HINTS = {
    Phase.RECEIVE: "当前是接收。只听需求和方向，不写代码，不展开技术细节。",
    Phase.TOOL: "当前是查资料。先查网上已有做法，再决定。",
    Phase.ANSWER: "当前是回答。只给方向和已确定的决定，不写代码。",
    Phase.DONE: "当前已结束。不要再生成新的工具调用。",
}


def phase_hint(phase: Phase, plan: bool = False) -> str:
    if plan and phase == Phase.TOOL:
        return "当前是计划。" + build_plan_hint("", "查资料") + "先看本会话已经说过的需求，再用 web_search 查现成流程。查完必须调用 make_brief。"
    if plan and phase == Phase.ANSWER:
        return "当前是计划的结果。不要改写选项，不要补代码。"
    if not plan and phase == Phase.TOOL:
        return "当前是聊天里的查资料。事实和网上做法用 web_search，具体页面用 open_page。不写代码。"
    if not plan and phase == Phase.ANSWER:
        return "当前是聊天。只讨论方向和需求。不给代码，不给未经计划的技术细节。用户硬要代码，就说明这里不写代码。"
    return PHASE_HINTS[phase]
