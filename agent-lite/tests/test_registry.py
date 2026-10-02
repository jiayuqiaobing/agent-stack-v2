import asyncio

from runtime.registry import ToolRegistry


def test_duplicate_schema_is_exposed_once():
    item = {"type": "function", "function": {"name": "echo", "description": "d", "parameters": {}}}
    registry = ToolRegistry([item, dict(item)])
    assert [tool["function"]["name"] for tool in registry.exposed()] == ["echo"]


def test_unknown_tool_is_an_explicit_error():
    registry = ToolRegistry([])
    result = asyncio.run(registry.call("missing", {"a": 1}))
    assert result.startswith("错误")
    assert "missing" in result
    assert result != ""


def test_call_passes_arguments_through():
    seen = {}

    async def mcp(info, name, args):
        seen["info"] = info
        seen["name"] = name
        seen["args"] = args
        return "ok"

    registry = ToolRegistry([], {"remote_tool": {"session": "s"}}, mcp)
    result = asyncio.run(registry.call("remote_tool", {"q": "原样"}))
    assert result == "ok"
    assert seen["args"] == {"q": "原样"}
    assert seen["name"] == "remote_tool"
