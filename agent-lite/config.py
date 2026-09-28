"""
agent-lite/config.py

OpenAI 客户端初始化，其他文件调用使用   from config import client/aclient
"""

import os
from openai import OpenAI, AsyncOpenAI

#  非流式客户端实体
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY") or "not-configured",
    base_url=os.getenv("OPENAI_BASE_URL","https://api.openai.com/v1")
)

#  流式客户端实体
aclient = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY") or "not-configured",
    base_url=os.getenv("OPENAI_BASE_URL","https://api.openai.com/v1")
)

#  模型名 —— 业务代码中禁止硬编码，一律读这里（见 docs/2-产品规格.md 阶段一 P0 1.3）
#  改这里即可整体切换模型，不需要改任何业务代码
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-v4-pro")


def make_client(api_key: str | None, base_url: str | None) -> AsyncOpenAI:
    """按这一次请求的渠道建客户端。密钥和地址都空时，用进程里原来的客户端。"""
    key = (api_key or "").strip()
    url = (base_url or "").strip()
    if not key and not url:
        return aclient
    return AsyncOpenAI(
        api_key=key or os.getenv("OPENAI_API_KEY") or "not-configured",
        base_url=url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
    )
