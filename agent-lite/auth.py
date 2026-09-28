"""
agent-lite/auth.py

API Key 鉴权 — 保护 /chat、/sessions 等接口不被裸调用
用法：在路由装饰器里加 dependencies=[Depends(verify_api_key)]

客户端请求需带请求头：Authorization: Bearer <API_KEY>
其中 API_KEY 在 .env 里配置，与 DeepSeek 的 OPENAI_API_KEY 是两回事。
"""

import os
import secrets
from fastapi import Cookie, Header, HTTPException


def verify_api_key(
    authorization: str | None = Header(default=None),
    agent_access: str | None = Cookie(default=None),
) -> None:
    """校验访问令牌。

    - 未配置 API_KEY → 放行
    - 配置了 → 请求头 Bearer，或本机页面自动带上的 cookie，二者有一个对即可
    """
    api_key = os.getenv("API_KEY", "")
    if not api_key:
        return

    token = ""
    if isinstance(authorization, str) and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
    elif isinstance(agent_access, str) and agent_access.strip():
        token = agent_access.strip()
    if not token:
        raise HTTPException(status_code=401, detail="缺少 API Key（Authorization: Bearer <key>）")
    if not secrets.compare_digest(token, api_key):
        raise HTTPException(status_code=401, detail="API Key 无效")
