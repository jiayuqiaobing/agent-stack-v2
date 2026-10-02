import asyncio

import runtime.chat_log as chat_log
import router as router_mod
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _prepare(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_log, "_PATH", str(tmp_path / "chat.sqlite"))
    monkeypatch.delenv("API_KEY", raising=False)
    router_mod.sessions.clear()


def _app():
    app = FastAPI()
    app.state.all_tools = []
    app.state.tool_session_map = {}
    app.include_router(router_mod.router)
    return app


def test_sqlite_survives_memory_reset_without_duplicating(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    try:
        sid, memory = router_mod._get_or_create_session("keep-1", [])
        memory.add("user", "只写一次的原话")
        assert len(chat_log.load_messages(sid)) == 1
        router_mod.sessions.pop(sid)
        sid2, restored = router_mod._get_or_create_session(sid, [])
        assert sid2 == sid
        assert [item.get("content") for item in restored.short_term] == ["只写一次的原话"]
        assert len(chat_log.load_messages(sid)) == 1
    finally:
        router_mod.sessions.pop("keep-1", None)


def test_list_and_delete_clear_memory_and_sqlite(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    try:
        sid, memory = router_mod._get_or_create_session("listed", [])
        memory.add("user", "列出来")
        client = TestClient(_app())
        listed = client.get("/sessions")
        assert listed.status_code == 200
        ids = [item["id"] for item in listed.json()["sessions"]]
        assert "listed" in ids
        messages = client.get("/sessions/listed/messages")
        assert messages.json()["messages"][0]["text"] == "列出来"
        deleted = asyncio.run(router_mod.delete_session("listed"))
        assert deleted["status"] == "ok"
        assert chat_log.load_messages("listed") == []
        assert "listed" not in router_mod.sessions
    finally:
        router_mod.sessions.pop("listed", None)
