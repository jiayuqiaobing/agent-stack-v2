from runtime.project_lookup import read_span_sync, search_project_sync


def test_search_finds_project_text():
    found = search_project_sync("def classify")
    assert "templates.py" in found
    assert "错误" not in found.splitlines()[0]


def test_short_query_is_rejected_and_span_reads_a_real_line():
    assert search_project_sync("a").startswith("错误")
    text = read_span_sync("runtime/planner/templates.py", 70)
    assert "def classify" in text
    assert text.startswith("错误") is False


def test_span_rejects_path_escape():
    assert read_span_sync("..", 1).startswith("错误")
    assert read_span_sync("../outside.txt", 1).startswith("错误")
