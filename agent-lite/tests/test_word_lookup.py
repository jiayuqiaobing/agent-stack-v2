from urllib.error import URLError

from runtime.word_lookup import define_word_sync


class _Body:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def test_missing_word_and_request_failure_differ(monkeypatch):
    monkeypatch.setattr("runtime.word_lookup.urlopen", lambda *args, **kwargs: _Body(b"[]"))
    missing = define_word_sync("zzzznotaword")
    assert missing == "没有查到这个单词"

    def boom(*args, **kwargs):
        raise URLError("nope")

    monkeypatch.setattr("runtime.word_lookup.urlopen", boom)
    failed = define_word_sync("hello")
    assert failed.startswith("错误")
    assert failed != missing
    assert failed != ""
