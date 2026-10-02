import time

from observability.metrics import build_report


def test_success_and_failure_are_counted():
    now = time.time()
    spans = [
        {"kind": "agent", "status": "ok", "duration_ms": 10, "start_time": now, "error": None},
        {
            "kind": "agent",
            "status": "error",
            "duration_ms": 20,
            "start_time": now,
            "error": {"type": "ValueError", "message": "x"},
        },
    ]
    report = build_report("1h", spans)
    assert report["requests"]["total"] == 2
    assert report["requests"]["ok"] == 1
    assert report["requests"]["error"] == 1
    assert report["errors_by_type"]["ValueError"] == 1


def test_empty_window_is_a_report_not_an_exception():
    report = build_report("1h", [])
    assert report["requests"]["total"] == 0
    assert report["errors_by_type"] == {}
