from runtime.phase import Phase, phase_hint


def test_plan_tool_hint_carries_the_user_sentence():
    hint = phase_hint(Phase.TOOL, True, "怎么写一本科幻小说")
    assert "怎么写一本科幻小说" in hint
    assert "页面结构" not in hint


def test_chat_answer_does_not_use_plan_sections():
    hint = phase_hint(Phase.ANSWER, False, "怎么写一本科幻小说")
    assert "项目类型" not in hint
    assert "隐藏检查" not in hint
    assert "make_brief" not in hint
