"""
agent-lite/auth.py

API Key 鉴权 — 保护 /chat、/sessions 等接口不被裸调用
用法：在路由装饰器里加 dependencies=[Depends(verify_api_key)]

客户端请求需带请求头：Authorization: Bearer <API_KEY>
其中 API_KEY 在 .env 里配置，与 DeepSeek 的 OPENAI_API_KEY 是两回事。
"""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Header, HTTPException

# 跟 config.py 一样，import 时就加载 .env，保证独立 import 也能读到
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")


def verify_api_key(authorization: str | None = Header(default=None)) -> None:
    """校验 Bearer Token 依赖。

    - 未配置 API_KEY → 放行（开发模式，本地照常用）
    - 配置了 API_KEY → 必须带对 key，否则 401
    """
    api_key = os.getenv("API_KEY", "")
    if not api_key:
        return  # 开发模式，未启用鉴权

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 API Key（Authorization: Bearer <key>）")

    token = authorization[len("Bearer "):].strip()
    # 用 compare_digest 比较，防时序侧信道
    if not secrets.compare_digest(token, api_key):
        raise HTTPException(status_code=401, detail="API Key 无效")
