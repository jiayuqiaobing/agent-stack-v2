"""
agent-lite/models.py

存放 Pydantic 模型，供 FastAPI 调用
"""


from pydantic import BaseModel


class ChatRequest(BaseModel):
    """客户端发送的请求体"""
    message: str
    session_id: str | None = None  # 不传则自动分配新 session


class ChatResponse(BaseModel):
    """非流式接口的返回体"""
    reply: str
    status: str = "ok"  # "ok" 或 "error"
    error: str | None = None
    session_id: str | None = None  # 让前端记住，后续请求带上