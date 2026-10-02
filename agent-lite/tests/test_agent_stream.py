import asyncio

import router as router_mod
from agent import agent_loop_stream
from fastapi import FastAPI
from fastapi.testclient import TestClient
from memory import HybridMemory


class _Delta:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None
        self.reasoning_content = None


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content=None, usage=None):
        self.usage = usage
        self.choices = [] if content is None else [_Choice(content)]


class _Usage:
    prompt_tokens = 2
    completion_tokens = 1
    prompt_tokens_details = None


class _Completions:
    def __init__(self, factory):
        self.factory = factory
        self.kwargs = []

    async def create(self, **kwargs):
        self.kwargs.append(kwargs)
        return self.factory()


def _llm(factory):
    completions = _Completions(factory)
    llm = type("LLM", (), {"chat": type("Chat", (), {"completions": completions})()})()
    return llm, completions


def test_stream_contains_user_sentence_and_done():
    async def chunks():
        yield _Chunk("你好")
        yield _Chunk(None, _Usage())

    llm, completions = _llm(chunks)
    memory = HybridMemory(system_prompt="s", client=None, session_id="agent-stream")
    memory.persist = False

    async def collect():
        return [
            event
            async for event in agent_loop_stream(
                "怎么写一本科幻小说", memory, tools=[], llm=llm, mode="plan"
            )
        ]

    events = asyncio.run(collect())
    kinds = [event["type"] for event in events]
    assert "delta" in kinds
    assert kinds[-1] == "done"
    blob = "\n".join(
        item.get("content") or ""
        for item in completions.kwargs[0]["messages"]
        if item.get("role") == "system"
    )
    assert "用户原话：怎么写一本科幻小说" in blob


def test_stream_interruption_is_an_error_event():
    async def broken():
        raise RuntimeError("断了")
        yield _Chunk("不会到")

    llm, _completions = _llm(broken)
    memory = HybridMemory(system_prompt="s", client=None, session_id="agent-stream-err")
    memory.persist = False

    async def collect():
        return [event async for event in agent_loop_stream("你好", memory, tools=[], llm=llm)]

    events = asyncio.run(collect())
    assert events[-1]["type"] == "error"
    assert events[-1]["message"]
    assert all(event["type"] != "done" for event in events)


def test_http_stream_starts_with_session(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)

    async def fake_stream(**kwargs):
        yield {"type": "delta", "content": "正文"}
        yield {"type": "done", "reply": "正文"}

    monkeypatch.setattr(router_mod, "agent_loop_stream", fake_stream)
    app = FastAPI()
    app.state.all_tools = []
    app.state.tool_session_map = {}
    app.include_router(router_mod.router)
    response = TestClient(app).post("/chat/stream", json={"message": "你好", "session_id": "http-1"})
    assert response.status_code == 200
    body = response.text
    assert '"type": "session"' in body
    assert body.index('"type": "session"') < body.index('"type": "delta"')
    assert '"type": "done"' in body
    router_mod.sessions.pop("http-1", None)
