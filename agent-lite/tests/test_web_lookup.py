from urllib.error import URLError

from runtime.web_lookup import web_search_sync


def test_search_failure_is_explicit(monkeypatch):
    def boom(url):
        raise URLError("down")

    monkeypatch.setattr("runtime.web_lookup._get_json", boom)
    result = web_search_sync("科幻小说")
    assert result.startswith("错误")
    assert result != ""
    assert "down" in result


def test_search_success_returns_the_summary(monkeypatch):
    monkeypatch.setattr(
        "runtime.web_lookup._get_json",
        lambda url: {"AbstractText": "一段可以引用的摘要", "RelatedTopics": []},
    )
    assert web_search_sync("科幻") == "一段可以引用的摘要"


def test_empty_query_is_rejected():
    assert web_search_sync("  ").startswith("错误")
