import json

from runtime.brief import fallback_brief


def _load(goal):
    text = fallback_brief(goal)
    assert text.startswith("BRIEF_FORM"), text[:40]
    return json.loads(text[len("BRIEF_FORM"):])


def test_four_goals_do_not_share_visible_text():
    goals = ["怎么写一本科幻小说", "制作一个记账软件", "制作扫雷网页", "爬取学校课表"]
    parsed = [_load(goal) for goal in goals]
    pairs = [(left, right) for index, left in enumerate(parsed) for right in parsed[index + 1:]]
    for left, right in pairs:
        left_titles = [item["question"] for item in left["visible_decisions"]]
        right_titles = [item["question"] for item in right["visible_decisions"]]
        assert not (set(left_titles) & set(right_titles))
        for sentence in [item["options"][0] for item in left["visible_decisions"]]:
            for other in [item["options"][0] for item in right["visible_decisions"]]:
                assert sentence not in other and other not in sentence


def test_novel_fallback_is_not_a_web_or_software_card():
    text = fallback_brief("怎么写一本科幻小说")
    for word in ("页面结构", "视觉层级", "核心功能", "模块", "权限", "安装"):
        assert word not in text
    data = _load("怎么写一本科幻小说")
    assert data["resource_requests"][0]["status"] == "pending"
    assert "http://" not in text and "https://" not in text


def test_minesweeper_fallback_keeps_game_checks_hidden():
    data = _load("制作扫雷网页")
    hidden = "\n".join(item["decision"] for item in data["hidden_details"])
    assert "坐标" in hidden
    assert "状态机" in hidden
    assert all(item["question"] != "页面结构" for item in data["visible_decisions"])


def test_crawler_fallback_is_not_a_web_template():
    data = _load("爬取学校课表")
    assert data["task_type"] == "crawler"
    assert "页面结构" not in fallback_brief("爬取学校课表")


def test_cooking_fallback_stays_twelve_steps():
    data = _load("怎样做一道番茄炒蛋")
    assert len(data["visible_decisions"]) == 12
    assert "准备食材" in data["visible_decisions"][0]["question"]
