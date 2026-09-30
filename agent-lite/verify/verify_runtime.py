"""不调模型：追问 JSON、统一工具、会话失败记录互不串。"""

import asyncio
import ast
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from runtime.assist import prepare_turn
from runtime.phase import Phase
from runtime.registry import ToolRegistry
from tools_local import FETCH_URL_TOOL, READ_FILE_TOOL, LOCAL_TOOLS
import memory as memory_mod


def main() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    for name in ("runtime/phase.py", "runtime/registry.py", "runtime/assist.py", "agent.py", "memory.py"):
        ast.parse((root / name).read_text(encoding="utf-8"))

    chat = prepare_turn("你好", LOCAL_TOOLS, None)
    assert [item["function"]["name"] for item in chat["tools"]][:2] == ["web_search", "open_page"]
    page = prepare_turn("看一下 https://example.com", [FETCH_URL_TOOL, READ_FILE_TOOL], None)
    assert "fetch_url" in [item["function"]["name"] for item in page["tools"]]
    assert "web_search" in [item["function"]["name"] for item in page["tools"]]
    located = prepare_turn("prepare_turn 在哪个文件", [READ_FILE_TOOL], None)
    assert "search_project" in [item["function"]["name"] for item in located["tools"]]
    span = prepare_turn("看 agent.py 第12行", [READ_FILE_TOOL], None)
    assert "read_span" in [item["function"]["name"] for item in span["tools"]]
    remembered = prepare_turn("刚才我说了什么", [], None, memory=type("M", (), {"short_term": [{"role": "user", "content": "我喜欢蓝色"}]})())
    assert "search_session" in [item["function"]["name"] for item in remembered["tools"]]
    defined = prepare_turn("error 这个单词什么意思", [], None)
    assert "define_word" in [item["function"]["name"] for item in defined["tools"]]
    chat_only = prepare_turn("制作一个网页需要什么", [], None)
    assert "make_brief" not in [item["function"]["name"] for item in chat_only["tools"]]
    brief = prepare_turn("你好", [], None, mode="plan")
    brief_names = [item["function"]["name"] for item in brief["tools"]]
    assert brief_names[:3] == ["web_search", "open_page", "make_brief"], brief_names
    shell = prepare_turn("运行命令 pytest", [], None)
    assert "run_command" in [item["function"]["name"] for item in shell["tools"]]
    page_tool = prepare_turn("用浏览器打开网页", [], None)
    assert "open_page" in [item["function"]["name"] for item in page_tool["tools"]]
    from runtime.brief import fallback_brief, render_brief
    from runtime.planner.prompts import build_plan_hint, build_refinement_hint, build_turn_plan_context, is_plan_refinement
    from runtime.planner.templates import classify
    from runtime.planner.coverage import coverage_for
    wide = render_brief({"goal": "网站", "items": [{"id": "1", "need": "页面", "options": ["一种", "两种"]}]})
    assert wide.startswith("错误"), wide
    asks = [{"id": str(i), "need": "项" + str(i), "options": ["页面上先放一个能点的入口，点开进入下一步", "另一项"]} for i in range(12)]
    done = render_brief({"goal": "扫雷", "items": asks})
    assert done.startswith("BRIEF_FORM"), done[:40]
    complete_asks = [
        {"id": "1", "need": "棋盘页面", "options": ["棋盘页显示9x9方格，每格可以翻开或插旗", "其他棋盘"]},
        {"id": "2", "need": "难度选择", "options": ["开始页可选初级9x9中级16x16高级16x30", "其他难度"]},
        {"id": "3", "need": "首次点击", "options": ["首次点击后再布雷并保证点击格及相邻格安全", "随机布雷"]},
        {"id": "4", "need": "插旗操作", "options": ["桌面端右键和手机端长按均可插旗", "其他操作"]},
        {"id": "5", "need": "数字提示", "options": ["翻开的格子显示相邻八格地雷数量", "其他提示"]},
        {"id": "6", "need": "胜负判断", "options": ["翻到地雷立即失败且揭示全部地雷", "其他结果"]},
        {"id": "7", "need": "胜利判断", "options": ["所有非雷格翻开后显示胜利状态", "其他规则"]},
        {"id": "8", "need": "计时器", "options": ["首次翻格开始秒表并在结束时停止", "不显示时间"]},
        {"id": "9", "need": "剩余地雷", "options": ["顶部显示剩余雷数并随插旗变化", "其他显示"]},
        {"id": "10", "need": "重新开始", "options": ["重开按钮清空棋盘计时并开始新局", "不提供重开"]},
        {"id": "11", "need": "窄屏布局", "options": ["窄屏下棋盘可缩放且操作按钮不溢出", "只支持桌面"]},
        {"id": "12", "need": "启动方式", "options": ["交付可直接用浏览器打开的HTML文件", "其他交付"]},
    ]
    quality = render_brief({"goal": "扫雷网页", "items": complete_asks})
    assert quality.startswith("BRIEF_FORM"), quality[:120]

    class FakeMessage:
        content = ""

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                FakeMessage.content = json.dumps({
                    "score": 91,
                    "issues": [],
                    "items": complete_asks,
                    "notes": [],
                }, ensure_ascii=False)
            else:
                FakeMessage.content = '{"score": 91, "issues": []}'
            return FakeResponse()

    fake_completions = FakeCompletions()

    class FakeLLM:
        chat = type("Chat", (), {"completions": fake_completions})()

    from runtime.brief import review_brief
    reviewed = asyncio.run(review_brief(quality, [], FakeLLM(), "test"))
    assert reviewed.startswith("BRIEF_FORM"), reviewed[:80]
    assert '"score": 91' in reviewed, reviewed

    class FailingCompletions:
        async def create(self, **kwargs):
            raise ValueError("review unavailable")

    failing_llm = type("LLM", (), {
        "chat": type("Chat", (), {"completions": FailingCompletions()})()
    })()
    preserved = asyncio.run(review_brief(quality, [], failing_llm, "test"))
    assert preserved.startswith("BRIEF_FORM"), preserved[:80]
    assert "未复核草稿" in preserved, preserved
    assert fallback_brief("网页").startswith("BRIEF_FORM")
    assert classify("制作俄罗斯方块网页") == "web_game"
    assert classify("爬取学校课表") == "crawler"
    assert classify("制作大学课表软件") == "timetable"
    assert "状态机" in build_plan_hint("制作俄罗斯方块网页", "拆解")
    assert "坐标约定" in build_plan_hint("制作俄罗斯方块网页", "拆解")
    assert "真实浏览器验收" in build_plan_hint("制作俄罗斯方块网页", "拆解")
    assert is_plan_refinement("把刚才的任务再拆得更细一点")
    assert is_plan_refinement("回问自己，把已有步骤拆解得更细")
    assert not is_plan_refinement("怎么创建一个新网页")
    assert "不是在提出新项目" in build_refinement_hint()
    assert "项目类型" in build_turn_plan_context("制作俄罗斯方块网页")
    coverage = coverage_for("web_game")
    assert "task_facts" in coverage["core"]
    assert "state_machine" in coverage["specialized"]
    cooking = json.loads(fallback_brief("怎样做一道番茄炒蛋")[len("BRIEF_FORM"):])
    assert len(cooking["visible_decisions"]) == 12
    assert "准备食材" in cooking["visible_decisions"][0]["question"]
    web_fallback = json.loads(fallback_brief("创建一个扫雷网页")[len("BRIEF_FORM"):])
    assert len(web_fallback["visible_decisions"]) == 6
    structured = json.loads(done[len("BRIEF_FORM"):]) if done.startswith("BRIEF_FORM") else {}
    assert {"visible_decisions", "hidden_details", "query_requests", "resource_requests", "acceptance", "review"}.issubset(structured)
    assert all(2 <= len(item["options"]) <= 3 for item in structured["visible_decisions"])
    assert all(item["default_index"] == 0 for item in structured["visible_decisions"])

    class TCFunction:
        def __init__(self, name):
            self.name = name
            self.arguments = "{}"

    class TC:
        def __init__(self, ident, name):
            self.id = ident
            self.function = TCFunction(name)

    class ToolMessage:
        content = None
        tool_calls = [TC("call-a", "web_search"), TC("call-b", "web_search")]

    class MemoryProbe:
        def __init__(self):
            self.short_term = []
        def add_assistant_with_tool_calls(self, msg):
            self.short_term.append({"role": "assistant", "tool_calls": [{"id": tc.id} for tc in msg.tool_calls]})
        def add(self, role, content, **extra):
            self.short_term.append({"role": role, "content": content, **extra})

    probe = MemoryProbe()
    probe.add_assistant_with_tool_calls(ToolMessage())
    probe.add("tool", "one", tool_call_id="call-a")
    probe.add("tool", "two", tool_call_id="call-b")
    assert {item["tool_call_id"] for item in probe.short_term if item["role"] == "tool"} == {"call-a", "call-b"}

    from memory import HybridMemory
    sanitized = object.__new__(HybridMemory)
    sanitized.session_id = "sanitize-test"
    sanitized.short_term = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "orphan", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "user", "content": "继续"},
    ]
    safe = sanitized._safe_messages()
    assert safe == [{"role": "user", "content": "继续"}], safe
    assist_src = (root / "runtime" / "assist.py").read_text(encoding="utf-8")
    assert "urllib" not in assist_src
    assert "from runtime.web_lookup import WEB_SEARCH" in assist_src
    site = prepare_turn("怎么做一个网站", [FETCH_URL_TOOL], None)
    assert "不写代码" in site["note"]
    stopped = prepare_turn("现在几点了", LOCAL_TOOLS, None)
    assert all(item["function"]["name"] not in {"calculate", "get_time", "get_weather"} for item in stopped["tools"])

    async def check_tool():
        registry = ToolRegistry([READ_FILE_TOOL], None, None)
        missing = await registry.call("calculate", {"expression": "1+1"})
        assert "已停用" in missing, missing
        unknown = await registry.call("no_such_tool", {})
        assert unknown.startswith("错误"), unknown

    asyncio.run(check_tool())

    src = pathlib.Path(memory_mod.__file__).read_text(encoding="utf-8")
    assert "self.reflections" in src and "self.pending_questions" in src
    assert "本会话工具失败记录" in src
    assert Phase.CLARIFY.value == "clarify"
    print("[OK] runtime")


if __name__ == "__main__":
    main()
