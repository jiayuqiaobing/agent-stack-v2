"""
test_rag_isolation.py — RAG 多会话隔离回归测试

验证：不同 session 的 RAG 记忆互不串味。
机制：写入时打 session_id 元数据，检索/恢复/计数都按 session_id 过滤。

不调用真实 embedding 模型（fastembed 需要下载模型，CI 环境没有）：
用 patch 把 RAGStore._embed 替换成固定向量，专注测"隔离逻辑"本身。

运行方式：pytest tests/test_rag_isolation.py -v
"""

import asyncio
from unittest.mock import patch

from rag_store import RAGStore


def test_session_isolation():
    """A/B 两个 session 的记忆互不串味"""

    async def fake_embed(self, text):
        # 固定向量即可——本测试只关心 where 过滤是否隔离，不关心向量相似度
        return [0.1] * 512

    async def run():
        with patch.object(RAGStore, "_embed", fake_embed):
            a = RAGStore(session_id="iso-test-A")
            b = RAGStore(session_id="iso-test-B")
            try:
                await a.add("A 用户的名字是张三")
                await b.add("B 用户的名字是李四")

                # 检索：A 只返回 A 的记忆，B 只返回 B 的记忆
                assert await a.search("谁的名字") == ["A 用户的名字是张三"]
                assert await b.search("谁的名字") == ["B 用户的名字是李四"]

                # 恢复：同样按 session 隔离
                assert a.restore() == ["A 用户的名字是张三"]
                assert b.restore() == ["B 用户的名字是李四"]

                # 计数：各自为 1，互不影响
                assert a.count() == 1
                assert b.count() == 1
            finally:
                # 清理测试数据，避免污染真实 chroma_db
                a.collection.delete(where={"session_id": "iso-test-A"})
                b.collection.delete(where={"session_id": "iso-test-B"})

    asyncio.run(run())
