"""
test_auth.py — API Key 鉴权回归测试

验证 verify_api_key 依赖的行为：
- 未配置 API_KEY（开发模式）→ 放行
- 配置了 → 无 key / 错 key / 非 Bearer → 401，对 key → 通过

运行方式：pytest tests/test_auth.py -v
"""

import pytest
from fastapi import HTTPException

from auth import verify_api_key


def test_no_api_key_configured_allows_all(monkeypatch):
    """未配置 API_KEY → 开发模式，任何请求放行（不抛异常即通过）"""
    monkeypatch.delenv("API_KEY", raising=False)
    verify_api_key(authorization=None)
    verify_api_key(authorization="Bearer whatever")


def test_missing_header_rejected(monkeypatch):
    """配置了 key，但没带 Authorization 头 → 401"""
    monkeypatch.setenv("API_KEY", "secret-key")
    with pytest.raises(HTTPException) as e:
        verify_api_key(authorization=None)
    assert e.value.status_code == 401


def test_wrong_key_rejected(monkeypatch):
    """带错 key → 401"""
    monkeypatch.setenv("API_KEY", "secret-key")
    with pytest.raises(HTTPException) as e:
        verify_api_key(authorization="Bearer wrong-key")
    assert e.value.status_code == 401


def test_non_bearer_rejected(monkeypatch):
    """非 Bearer 格式（如 Basic）→ 401"""
    monkeypatch.setenv("API_KEY", "secret-key")
    with pytest.raises(HTTPException) as e:
        verify_api_key(authorization="Basic abc")
    assert e.value.status_code == 401


def test_correct_key_accepted(monkeypatch):
    """带对 key → 通过（不抛异常）"""
    monkeypatch.setenv("API_KEY", "secret-key")
    verify_api_key(authorization="Bearer secret-key")
