"""
test08/rag_store.py

向量存储模块 — 文本 → Embedding → ChromaDB 持久化
Embedding 使用本地 bge-small-zh-v1.5 模型（fastembed 加载），不依赖外部 API
每个 RAGStore 绑定一个 session_id，通过 ChromaDB 元数据过滤实现多会话隔离（防串味）
"""

import asyncio
import os
import logging
import threading
import uuid
import chromadb

# 国内直连 HuggingFace 常超时，默认走 hf-mirror 镜像；可用环境变量 HF_ENDPOINT 覆盖。
# 注意：必须在 import fastembed 之前设置，因为 fastembed 会触发 import huggingface_hub，
# 而后者在 import 时就读取 HF_ENDPOINT 环境变量。
os.environ["HF_ENDPOINT"] = os.getenv("HF_ENDPOINT") or "https://hf-mirror.com"
# 禁用 Xet 存储后端：hf-mirror 不支持 Xet 的 CAS 服务器（会报 401），改走普通 HTTP 下载
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_XET_DISABLE"] = "1"

from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

# 本地 embedding 模型（中文，512 维）
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"

# 模型缓存目录 — 放项目里，跟 chroma_db 一样可挂载，Docker 部署不依赖网络
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")

# 全局单例：模型只加载一次，避免每个 session（HybridMemory → RAGStore）重复加载 100MB 模型
_embed_model = None
_embed_model_lock = threading.Lock()


def _get_embed_model() -> TextEmbedding:
    """懒加载本地 embedding 模型，全局共享一份"""
    global _embed_model
    if _embed_model is None:
        with _embed_model_lock:
            if _embed_model is None:
                logger.info("加载本地 embedding 模型：%s", EMBED_MODEL)
                _embed_model = TextEmbedding(
                    model_name=EMBED_MODEL,
                    cache_dir=MODEL_DIR,
                )
    return _embed_model


def _embed_sync(model: TextEmbedding, text: str) -> list[float]:
    """同步 embedding（fastembed 是同步的，交给线程池执行）"""
    embedding = list(model.embed([text]))[0]
    return embedding.tolist()


class RAGStore:
    """ChromaDB 向量存储，负责摘要的 Embedding 写入和语义检索

    通过元数据 session_id 实现多会话隔离：写入时打标，检索/恢复时按 session_id 过滤。
    """

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.chroma = chromadb.PersistentClient(
            path=os.path.join(os.path.dirname(__file__), "chroma_db")
        )
        self.collection = self.chroma.get_or_create_collection("agent_memory")
        logger.debug("RAGStore 初始化完成（session=%s）", self.session_id)

    async def add(self, text: str) -> None:
        """将文本转为 Embedding 写入 ChromaDB，并打上 session_id 元数据"""
        try:
            embedding = await self._embed(text)
            # ChromaDB 无原生 async API → 扔到线程池，不阻塞事件循环
            await asyncio.to_thread(
                self.collection.add,
                ids=[uuid.uuid4().hex],
                embeddings=[embedding],
                documents=[text],
                metadatas=[{"session_id": self.session_id}],
            )
        except Exception:
            logger.warning("RAGStore 写入失败", exc_info=True)
            raise

    async def search(self, query: str, k: int = 5) -> list[str]:
        """语义检索 — 只检索本 session 的记忆（where 过滤），返回最相关的 k 条"""
        try:
            count = await asyncio.to_thread(self.collection.count)
            if count == 0:
                return []
            query_emb = await self._embed(query)
            results = await asyncio.to_thread(
                self.collection.query,
                query_embeddings=[query_emb],
                n_results=min(k, count),
                where={"session_id": self.session_id},
            )
            return results["documents"][0] if results["documents"] else []
        except Exception:
            logger.warning("RAGStore 检索失败", exc_info=True)
            return []

    def restore(self) -> list[str]:
        """恢复本 session 的历史摘要（按 session_id 隔离，其他 session 的不返回）"""
        try:
            existing = self.collection.get(where={"session_id": self.session_id})
            return list(existing.get("documents") or [])
        except Exception:
            logger.warning("RAGStore 恢复失败", exc_info=True)
            return []

    def count(self) -> int:
        """本 session 的向量数（按 session_id 过滤）"""
        try:
            existing = self.collection.get(where={"session_id": self.session_id})
            return len(existing.get("ids") or [])
        except Exception:
            logger.warning("RAGStore 计数失败", exc_info=True)
            return -1

    async def _embed(self, text: str) -> list[float]:
        """本地 bge 模型 embedding（同步 → 线程池，不阻塞事件循环）"""
        model = _get_embed_model()
        return await asyncio.to_thread(_embed_sync, model, text)
