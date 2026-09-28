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
    temperature: float | None = None  # 不传则保持原来的 0
    stop: str | None = None  # 遇到这个词就停止生成，不传则不限制
    system: str | None = None  # 补充的系统说明，接在原提示后面
    max_tokens: int | None = None  # 不传则 4096；简短回答可用 50
    attachments: list[dict] | None = None  # 可选。每项含 name、mime、data_base64
    mode: str | None = None  # chat 正常聊天；plan 才拆题


class ChatResponse(BaseModel):
    """非流式接口的返回体"""
    reply: str
    status: str = "ok"  # "ok" 或 "error"
    error: str | None = None
    session_id: str | None = None  # 让前端记住，后续请求带上