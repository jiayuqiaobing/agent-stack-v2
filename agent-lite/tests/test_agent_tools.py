import asyncio

from agent import agent_loop
from memory import HybridMemory


class _Fn:
    def __init__(self, name, arguments="{}"):
        self.name = name
        self.arguments = arguments


class _Call:
    def __init__(self, ident, name):
        self.id = ident
        self.function = _Fn(name)


class _Message:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message):
        self.message = message


class _Usage:
    prompt_tokens = 2
    completion_tokens = 1
    prompt_tokens_details = None


class _Response:
    def __init__(self, message):
        self.choices = [_Choice(message)]
        self.usage = _Usage()


class _Completions:
    def __init__(self, messages):
        self.messages = list(messages)

    async def create(self, **kwargs):
        return _Response(self.messages.pop(0))


def _llm(messages):
    return type("LLM", (), {"chat": type("Chat", (), {"completions": _Completions(messages)})()})()


def test_failed_plan_is_not_shown_as_a_tool_error():
    class _Completions:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return _Response(_Message("", [_Call("brief-1", "make_brief")]))
            return _Response(_Message("不是计划"))

    llm = type("LLM", (), {"chat": type("Chat", (), {"completions": _Completions()})()})()
    memory = HybridMemory(system_prompt="s", client=None, session_id="agent-fallback")
    memory.persist = False
    reply = asyncio.run(agent_loop("怎么写一本科幻小说", memory, tools=[], llm=llm, mode="plan"))
    assert reply.startswith("BRIEF_FORM")
    assert "页面结构" not in reply
    assert not reply.startswith("错误")


def test_duplicate_tool_still_gets_both_ids_and_code_is_removed():
    memory = HybridMemory(system_prompt="s", client=None, session_id="agent-tools")
    memory.persist = False
    first = _Message("", [_Call("call-1", "echo"), _Call("call-2", "echo")])
    second = _Message("说明\n```\nprint(1)\n```")
    reply = asyncio.run(agent_loop("你好", memory, tools=[], llm=_llm([first, second]), mode="plan"))
    tools = [item for item in memory.short_term if item.get("role") == "tool"]
    assert [item.get("tool_call_id") for item in tools] == ["call-1", "call-2"]
    assert any("跳过重复" in item.get("content", "") for item in tools)
    assert "print(1)" not in reply
    assert "这里不写代码" in reply
