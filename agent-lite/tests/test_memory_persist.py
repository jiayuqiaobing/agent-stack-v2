import runtime.chat_log as chat_log
from memory import HybridMemory


def test_broken_tool_chain_is_not_sent_back():
    memory = HybridMemory(system_prompt="s", client=None, session_id="mem-safe")
    memory.persist = False
    memory.short_term = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "missing", "type": "function", "function": {"name": "echo", "arguments": "{}"}},
        ]},
        {"role": "tool", "content": "没有对应调用", "tool_call_id": "orphan"},
    ]
    safe = memory._safe_messages()
    assert all("tool_calls" not in item for item in safe)
    assert all(item.get("role") != "tool" for item in safe)
    assert safe[0]["content"] == "你好"


def test_complete_tool_chain_is_kept():
    memory = HybridMemory(system_prompt="s", client=None, session_id="mem-safe-ok")
    memory.persist = False
    memory.short_term = [
        {"role": "assistant", "content": "查一下", "tool_calls": [
            {"id": "ok-1", "type": "function", "function": {"name": "echo", "arguments": "{}"}},
        ]},
        {"role": "tool", "content": "结果", "tool_call_id": "ok-1"},
    ]
    safe = memory._safe_messages()
    assert safe[0]["tool_calls"][0]["id"] == "ok-1"
    assert safe[1]["tool_call_id"] == "ok-1"


def test_persist_flag_and_tool_role(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_log, "_PATH", str(tmp_path / "chat.sqlite"))
    memory = HybridMemory(system_prompt="s", client=None, session_id="mem-1")
    memory.persist = False
    memory.add("user", "不要写入")
    assert chat_log.load_messages("mem-1") == []
    memory.persist = True
    memory.add("user", "要写入")
    memory.add("tool", "工具结果", tool_call_id="t1")
    rows = chat_log.load_messages("mem-1")
    assert [row["text"] for row in rows] == ["要写入"]
    assert rows[0]["role"] == "user"
