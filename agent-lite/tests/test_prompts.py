from runtime.planner.prompts import (
    build_plan_hint,
    build_refinement_hint,
    build_turn_plan_context,
    is_plan_refinement,
)


def test_empty_text_is_not_forced_into_web():
    hint = build_plan_hint("", "查资料")
    assert "未匹配" in hint
    assert "页面结构" not in hint


def test_novel_hint_does_not_borrow_other_types():
    hint = build_plan_hint("怎么写一本科幻小说", "拆解")
    for word in ("页面结构", "视觉层级", "模块", "权限", "安装"):
        assert word not in hint


def test_minesweeper_hint_keeps_game_checks():
    hint = build_plan_hint("制作扫雷网页", "拆解")
    for word in ("坐标", "状态机", "不变量", "规则数据", "真实浏览器验收"):
        assert word in hint


def test_software_hint_has_no_game_state_machine():
    assert "状态机" not in build_plan_hint("制作一个记账软件", "拆解")


def test_refinement_detects_meta_but_not_a_new_web_task():
    assert is_plan_refinement("回问自己，把已有步骤再拆一下")
    assert not is_plan_refinement("做一个新网页")
    assert "不是在提出新项目" in build_refinement_hint()
    assert "未匹配" in build_turn_plan_context("怎么写一本科幻小说")
    assert "不是在提出新项目" in build_turn_plan_context("把刚才的任务再拆得更细一点")
