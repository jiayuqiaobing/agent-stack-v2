import asyncio

from runtime.assist import clean_input, prepare_turn, run_assist


def _names(text, mode=None):
    result = prepare_turn(text, [], None, None, mode)
    return [item["function"]["name"] for item in result["tools"]]


def test_chat_can_search_but_does_not_plan():
    names = _names("你好")
    assert "web_search" in names
    assert "open_page" in names
    assert "make_brief" not in names
    assert "run_command" not in names
    assert "search_project" not in names


def test_plan_adds_brief():
    names = _names("怎么写一本科幻小说", "plan")
    assert "make_brief" in names
    assert "web_search" in names
    assert "open_page" in names


def test_stopped_tool_and_long_input():
    assert asyncio.run(run_assist("calculate", {"expression": "1+1"})).startswith("错误")
    cleaned = clean_input("a" * 9000 + "\x00")
    assert len(cleaned) == 8000
    assert "\x00" not in cleaned


def test_shell_and_project_only_when_asked():
    assert "run_command" in _names("帮我运行命令 pytest")
    assert "search_project" in _names("项目里哪个文件定义了 classify")
