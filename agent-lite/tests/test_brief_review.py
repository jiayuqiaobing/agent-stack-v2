import asyncio
import json

from runtime.brief import _parse_review, _parse_score, fallback_brief, review_brief


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, texts):
        self.texts = list(texts)

    async def create(self, **kwargs):
        if not self.texts:
            raise ValueError("no more replies")
        return _Response(self.texts.pop(0))


def _llm(texts):
    return type("LLM", (), {"chat": type("Chat", (), {"completions": _Completions(texts)})()})()


def test_unparseable_review_does_not_invent_a_score():
    assert _parse_review("不是 json") is None
    assert _parse_score("nope") is None


def test_review_failure_keeps_the_original_form():
    draft = fallback_brief("怎么写一本科幻小说")

    class Boom:
        async def create(self, **kwargs):
            raise ValueError("down")

    llm = type("LLM", (), {"chat": type("Chat", (), {"completions": Boom()})()})()
    result = asyncio.run(review_brief(draft, [], llm, "m"))
    assert result.startswith("BRIEF_FORM")
    assert "未复核草稿" in result
    assert "结构里没有条目" not in result


def test_review_writes_the_score():
    draft = fallback_brief("怎么写一本科幻小说")
    items = [
        {"id": "1", "need": "冲突", "ask": "先写什么冲突", "options": ["先写一个能推动情节的具体冲突", "另一种做法"]},
        {"id": "2", "need": "限制", "ask": "人物受什么限制", "options": ["给主角一个不能违反的具体限制", "另一种做法"]},
    ]
    first = json.dumps({"score": 90, "issues": [], "items": items, "notes": []}, ensure_ascii=False)
    second = json.dumps({"score": 91, "issues": []}, ensure_ascii=False)
    result = asyncio.run(review_brief(draft, [], _llm([first, second]), "m"))
    data = json.loads(result[len("BRIEF_FORM"):])
    assert data["review"]["score"] == 91
