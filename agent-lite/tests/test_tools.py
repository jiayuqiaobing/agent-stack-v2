"""
测试 tools_local.py —— 工具函数层
每个 test_ 函数测一个具体场景，assert 判断结果是否符合预期
"""

import pytest
import asyncio
from tools_local import safe_calculate, get_current_time


# ============================================================================
# safe_calculate 测试
# ============================================================================


def test_calculate_add():
    """加法"""
    result = asyncio.run(safe_calculate("2 + 3"))
    assert "5" in result


def test_calculate_subtract():
    """减法"""
    result = asyncio.run(safe_calculate("10 - 4"))
    assert "6" in result


def test_calculate_multiply():
    """乘法"""
    result = asyncio.run(safe_calculate("6 * 7"))
    assert "42" in result


def test_calculate_divide():
    """除法"""
    result = asyncio.run(safe_calculate("10 / 4"))
    assert "2.5" in result


def test_calculate_power():
    """幂运算"""
    result = asyncio.run(safe_calculate("2 ** 3"))
    assert "8" in result


def test_calculate_parentheses():
    """括号优先级"""
    result = asyncio.run(safe_calculate("(2 + 3) * 4"))
    assert "20" in result


def test_calculate_malicious_input():
    """恶意输入——拒绝执行，返回错误信息"""
    result = asyncio.run(safe_calculate("__import__('os').system('dir')"))
    assert "错误" in result


# ============================================================================
# get_current_time 测试
# ============================================================================


def test_get_current_time_format():
    """返回 YYYY-MM-DD HH:MM:SS 格式的字符串"""
    result = asyncio.run(get_current_time())
    # 拆开检查：应该有日期和时间部分，用空格连接
    parts = result.split(" ")
    assert len(parts) == 2
    date_part, time_part = parts
    # 日期：4位-2位-2位
    assert len(date_part.split("-")) == 3
    # 时间：2位:2位:2位
    assert len(time_part.split(":")) == 3
