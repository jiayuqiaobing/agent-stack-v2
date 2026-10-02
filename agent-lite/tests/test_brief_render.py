from runtime.brief import render_brief


def _item(text, options=None):
    return {
        "id": "1",
        "need": text,
        "ask": text,
        "options": options or [text + "的默认可执行步骤", "另一种做法"],
    }


def test_too_few_options_is_an_error():
    result = render_brief({"goal": "记账", "items": [_item("记下支出", ["只有一个"])]})
    assert result.startswith("错误")
    assert "页面结构" not in result


def test_short_default_is_an_error():
    result = render_brief({"goal": "记账", "items": [_item("记下支出", ["短", "另一种做法"])]})
    assert result.startswith("错误")


def test_wide_leaf_is_an_error():
    result = render_brief({
        "goal": "记账",
        "items": [{
            "need": "太多",
            "value": "这个和那个以及更多，还要再加一件，和另一件",
            "ask": "太多",
            "options": ["先只记一笔支出并保存", "另一种做法"],
        }],
    })
    assert result.startswith("错误")


def test_life_task_requires_twelve_steps():
    items = [_item("步骤" + str(i), ["把第" + str(i) + "步做成可执行动作", "另一种做法"]) for i in range(11)]
    result = render_brief({"goal": "怎样做一道番茄炒蛋", "items": items})
    assert result.startswith("错误")
    assert "12" in result


def test_non_life_task_accepts_two_steps():
    items = [
        _item("先列出小说要写的冲突", ["先写下一句能推动科幻冲突的场景", "另一种做法"]),
        _item("再写人物限制", ["给主角加上一条不能违反的限制", "另一种做法"]),
    ]
    result = render_brief({"goal": "怎么写一本科幻小说", "items": items})
    assert result.startswith("BRIEF_FORM"), result[:80]
    assert "页面结构" not in result
