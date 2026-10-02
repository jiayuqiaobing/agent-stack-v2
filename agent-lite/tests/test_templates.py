import pytest

from runtime.planner.templates import TEMPLATES, classify, template_for


def test_minesweeper_is_web_game_not_plain_web():
    assert classify("制作扫雷网页") == "web_game"
    assert classify("做一个普通网页") == "web"


def test_timetable_phrase_beats_crawler_and_software():
    assert classify("爬取学校课表") == "crawler"
    assert classify("制作大学课表软件") == "timetable"
    assert classify("制作一个记账软件") == "software"


def test_novel_is_unmatched_and_general_is_gone():
    assert classify("怎么写一本科幻小说") == "unmatched"
    assert "general" not in TEMPLATES
    assert template_for("怎么写一本科幻小说")["required_sections"] == ()


def test_software_word_does_not_override_timetable_phrase():
    assert "软件" in "课表软件"
    assert classify("做一门课表软件") == "timetable"
