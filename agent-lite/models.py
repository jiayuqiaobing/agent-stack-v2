"""
agent-lite/models.py

存放 Pydantic 模型，供 FastAPI 调用
"""


from pydantic import BaseModel


class ChatRequest(BaseModel):
    """客户端发送的请求体"""
    message: str
    session_id: str | None = None  # 不传则自动分配新 session
    model: str | None = None  # 不传则用 MODEL_NAME
    api_key: str | None = None  # 这一条渠道的供应商密钥，不是本服务令牌
    base_url: str | None = None  # 这一条渠道的接口地址，例如 https://xxx/v1


class ChatResponse(BaseModel):
    """非流式接口的返回体"""
    reply: str
    status: str = "ok"  # "ok" 或 "error"
    error: str | None = None
    session_id: str | None = None  # 让前端记住，后续请求带上