"""
测试 agent.py 中的格式化辅助函数
纯函数，不依赖任何外部资源，测试最简单
"""

import pytest
from agent import _format_tokens, _format_token_line


# ============================================================================
# _format_tokens 测试
# ============================================================================


def test_format_tokens_small():
    """小于 1000，原样显示"""
    assert _format_tokens(0) == "0"
    assert _format_tokens(500) == "500"
    assert _format_tokens(999) == "999"


def test_format_tokens_k():
    """1000 到 999999，用 k 单位，保留一位小数"""
    assert _format_tokens(1000) == "1.0k"
    assert _format_tokens(1500) == "1.5k"
    assert _format_tokens(9999) == "10.0k"


def test_format_tokens_m():
    """1000000 以上，用 M 单位"""
    assert _format_tokens(1000000) == "1.0M"
    assert _format_tokens(1500000) == "1.5M"


# ============================================================================
# _format_token_line 测试
# ============================================================================


def test_format_token_line():
    """返回的字符串包含分隔符、标签、格式化后的数字"""
    line = _format_token_line(1500, 500)
    assert "---" in line           # 有分隔线
    assert "[Token]" in line       # 有标签
    assert "2.0k" in line          # 总数 1500+500=2000 → 2.0k
    assert "输入" in line
    assert "1.5k" in line          # prompt 1500 → 1.5k
    assert "输出" in line
    assert "500" in line           # completion 500 → <1000，原样
