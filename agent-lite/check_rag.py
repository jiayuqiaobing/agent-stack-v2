"""
check_rag.py — RAG 有效性诊断脚本

作用：确认 agent-lite 的 RAG（ChromaDB + embedding）到底有没有真的工作。

运行方式（在 VS Code 终端里，用 test-env 环境）：
    cd agent-lite
    python check_rag.py

判定标准：
    - 修复前（DeepSeek 不支持 embedding）：[1] 打印 [FAIL] embedding 失败 → RAG 失效
    - 修复后（本地 bge 模型）：三步全部 [OK]，检索能召回"用户的宠物猫叫咪咪"
"""

import sys
from pathlib import Path

# 确保本脚本所在目录（agent-lite/）在 import 路径上，从任意目录运行都能 import 到 config / rag_store
sys.path.insert(0, str(Path(__file__).resolve().parent))

import asyncio


async def main():
    print("=" * 50)
    print("RAG 有效性诊断")
    print("=" * 50)

    from rag_store import RAGStore, EMBED_MODEL

    r = RAGStore()
    print(f"\n当前 embedding 模型：{EMBED_MODEL}")

    # [1] 直接测 embedding（rag_store 内部真正调用的方法）
    print("\n[1] 测试 embedding 调用...")
    try:
        emb = await r._embed("测试文本")
        print(f"    [OK] embedding 成功，返回 {len(emb)} 维向量")
    except Exception as e:
        print(f"    [FAIL] embedding 失败：{type(e).__name__}: {e}")
        print("    -> 结论：embedding 走不通，RAG 当前是失效状态")
        return

    # [2] 测写入 + 检索全链路
    print("\n[2] 测试写入 + 检索全链路...")
    try:
        await r.add("用户的宠物猫叫咪咪")
        print("    [OK] 写入 ChromaDB 成功")
    except Exception as e:
        print(f"    [FAIL] 写入失败：{type(e).__name__}: {e}")
        return

    result = await r.search("我的猫叫什么名字")
    if result:
        print(f"    [OK] 检索成功，召回：{result}")
    else:
        print("    [FAIL] 检索返回空，检索链路有问题")

    # [3] 向量库当前状态
    print(f"\n[3] 当前 ChromaDB 向量总数：{r.collection.count()}")

    print("\n" + "=" * 50)
    print("诊断完成")


if __name__ == "__main__":
    asyncio.run(main())
