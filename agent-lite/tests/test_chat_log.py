import runtime.chat_log as chat_log


def _use_db(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_log, "_PATH", str(tmp_path / "chat.sqlite"))


def test_roundtrip_is_isolated_and_skips_empty(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    chat_log.append_message("a", "user", "")
    chat_log.append_message("a", "user", "怎么写一本科幻小说")
    chat_log.append_message("a", "assistant", "先查成熟写法")
    chat_log.append_message("b", "user", "制作一个记账软件")
    assert chat_log.load_messages("a")[0]["text"] == "怎么写一本科幻小说"
    assert chat_log.load_messages("b")[0]["text"] == "制作一个记账软件"
    assert all(row["role"] != "tool" for row in chat_log.load_messages("a"))
    titles = {row["id"]: row["title"] for row in chat_log.list_sessions()}
    assert titles["a"] == "怎么写一本科幻小说"
    chat_log.append_message("a", "tool", "不应入库")
    assert [row["role"] for row in chat_log.load_messages("a")] == ["user", "assistant"]


def test_delete_removes_messages(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    chat_log.append_message("gone", "user", "删掉")
    chat_log.delete_session("gone")
    assert chat_log.load_messages("gone") == []
    assert all(row["id"] != "gone" for row in chat_log.list_sessions())
