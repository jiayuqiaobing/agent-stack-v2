from observability import trace


def test_invalid_trace_id_is_rejected():
    assert trace.is_valid_trace_id("0" * 32) is False
    assert trace.is_valid_trace_id("gg" * 16) is False
    assert trace.is_valid_trace_id("ab" * 16) is True


def test_child_span_points_at_the_root():
    with trace.start_trace("agent.turn", session_id="s1") as root:
        child = trace.make_span("llm.chat", "llm")
        assert child["trace_id"] == root["trace_id"]
        assert child["parent_span_id"] == root["span_id"]
        assert child["parent_span_id"] != child["span_id"]
    trace.finish_span(root, status="error", error=RuntimeError("x"))
    assert root["status"] == "error"
    assert root["error"]["type"] == "RuntimeError"


def test_export_failure_does_not_escape(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk")

    monkeypatch.setattr(trace.os, "makedirs", boom)
    trace.export_span({"trace_id": "t", "span_id": "s"})
