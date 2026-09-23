"""ab_cache_layout.py — 上下文布局对缓存命中率影响的 A/B 对照实验

背景：
    memory.build_context() 里 RAG 检索块的**位置**会影响 KV-Cache 命中率 ——
    它插得越靠前，后面的内容越容易因为它的变化而失效。

    但直接改完测一次不够：实测发现中转站的缓存波动极大（同代码两次跑
    相差 60.7% vs 37.6%），单次测量无法区分"真实改进"和"噪声"。

这个脚本做的事：
    1. 先往目标 session 灌入种子记忆，让 RAG **必然命中**（否则两种布局
       的上下文结构完全一样，等于没测）
    2. 让 A（老布局：RAG 插在第 1 位）和 B（新布局：RAG 放最后）**交替**跑 ——
       而不是先跑完 A 再跑 B，这样能抵消"上游状态随时间漂移"的干扰
    3. 统计各自的缓存命中率，给出结论

用法：
    python verify/ab_cache_layout.py --trials 5
"""

import argparse
import asyncio
import json
import os
import pathlib
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEED_MEMORIES = [
    "用户的服务器端口是 8080",
    "用户偏好用 Python 写后端",
    "用户的项目叫 agent-stack",
    "用户的数据库是 ChromaDB",
    "用户平时用 PowerShell 不用 cmd",
]

TURNS = [
    "我的服务器端口是多少",
    "我用什么语言写后端",
    "我的项目叫什么名字",
]


async def seed_memory(session_id: str):
    """往该 session 的 RAG 里灌入种子记忆，保证后续检索能命中"""
    from rag_store import RAGStore
    store = RAGStore(session_id=session_id)
    for text in SEED_MEMORIES:
        await store.add(text)


async def run_one_trial(tag: str, trial: int) -> dict:
    """跑一轮（多轮对话），返回这轮的缓存统计"""
    from config import client
    from memory import HybridMemory
    from router import SYSTEM_PROMPT_BASE, build_tool_table
    from tools_local import LOCAL_TOOLS
    from agent import agent_loop
    from observability import trace

    session_id = f"ab-{tag}-{trial}"
    await seed_memory(session_id)

    log_path = trace._daily_log_path()
    before = 0
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            before = len([ln for ln in f if ln.strip()])

    sp = SYSTEM_PROMPT_BASE.format(tool_table=build_tool_table(LOCAL_TOOLS))
    mem = HybridMemory(system_prompt=sp, client=client, session_id=session_id)

    for turn in TURNS:
        try:
            await agent_loop(user_message=turn, memory=mem,
                             tools=LOCAL_TOOLS, tool_session_map=None)
        except Exception as e:
            print(f"    [{tag}#{trial}] 调用失败：{type(e).__name__}: {str(e)[:60]}")

    with open(log_path, "r", encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip()][before:]

    llm, rag_hits = [], []
    for ln in lines:
        try:
            s = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if s.get("kind") == "llm" and s.get("attributes", {}).get("prompt_tokens"):
            llm.append(s)
        if s.get("kind") == "rag" and s.get("name") == "rag.search":
            rag_hits.append(s["attributes"].get("hit_count", 0))

    p = sum(s["attributes"]["prompt_tokens"] for s in llm)
    c = sum(s["attributes"].get("cache_hit_tokens", 0) for s in llm)
    return {
        "tag": tag, "trial": trial, "calls": len(llm),
        "prompt_tokens": p, "cache_hits": c,
        "hit_rate": (c / p) if p else 0.0,
        "rag_hits": rag_hits,
        "rag_effective": sum(1 for h in rag_hits if h > 0),
    }


async def main(trials: int):
    results = []
    print(f"A/B 对照：{trials} 轮 × 每轮 {len(TURNS)} 次调用")
    print("A = RAG 块插在 system_prompt 之后（老布局）")
    print("B = RAG 块放最后（新布局）")
    print("两种布局交替跑，抵消上游状态漂移\n")

    for i in range(trials):
        for tag, env in (("A", "1"), ("B", "0")):
            os.environ["AGENT_LITE_LEGACY_CTX_ORDER"] = env
            r = await run_one_trial(tag, i)
            results.append(r)
            eff = f"RAG命中{r['rag_effective']}/{len(r['rag_hits'])}"
            print(f"  第{i+1}轮 {tag}: 调用{r['calls']}次  输入{r['prompt_tokens']:>5}  "
                  f"缓存{r['cache_hits']:>5}  命中率 {r['hit_rate']:>6.1%}  {eff}")
        os.environ.pop("AGENT_LITE_LEGACY_CTX_ORDER", None)

    a = [r["hit_rate"] for r in results if r["tag"] == "A"]
    b = [r["hit_rate"] for r in results if r["tag"] == "B"]

    print()
    print("=" * 56)
    print(f"  A（RAG 靠前）  平均 {statistics.mean(a):.1%}   "
          f"范围 {min(a):.0%}~{max(a):.0%}   n={len(a)}")
    print(f"  B（RAG 靠后）  平均 {statistics.mean(b):.1%}   "
          f"范围 {min(b):.0%}~{max(b):.0%}   n={len(b)}")
    if len(a) > 1 and len(b) > 1:
        print(f"  标准差：A {statistics.stdev(a):.1%}  B {statistics.stdev(b):.1%}")
    diff = statistics.mean(b) - statistics.mean(a)
    print(f"  差值（B-A）：{diff:+.1%}")
    print()

    # 判断是否有意义 —— 差值必须明显大于波动
    noise = max(statistics.stdev(a or [0]), statistics.stdev(b or [0])) if len(a) > 1 else 0
    if abs(diff) > noise and abs(diff) > 0.05:
        winner = "B（RAG 靠后）" if diff > 0 else "A（RAG 靠前）"
        print(f"  结论：差异 {abs(diff):.1%} > 波动 {noise:.1%}，**{winner} 更优**")
    else:
        print(f"  结论：差异 {abs(diff):.1%} 未超过波动 {noise:.1%} ——")
        print(f"        **在本实验的样本量下无法区分**。上游波动主导了结果。")

    out = pathlib.Path(__file__).parent / "ab-cache-result.json"
    out.write_text(json.dumps({"trials": trials, "results": results,
                               "mean_A": statistics.mean(a) if a else 0,
                               "mean_B": statistics.mean(b) if b else 0},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已存：{out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=5)
    args = ap.parse_args()
    asyncio.run(main(args.trials))
