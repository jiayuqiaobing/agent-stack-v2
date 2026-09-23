"""
test08/config.py

OpenAI 客户端初始化，其他文件调用使用   from config import client/aclient
"""

import os
from pathlib import Path
from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv


load_dotenv(
    dotenv_path=Path(__file__).resolve().parent.parent / ".env"
)  # 自动读取 agent-stack/.env 文件

#  非流式客户端实体
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL","https://api.openai.com/v1")
)

#  流式客户端实体
aclient = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL","https://api.openai.com/v1")
)
