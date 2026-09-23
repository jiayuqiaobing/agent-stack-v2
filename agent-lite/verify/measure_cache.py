"""measure_cache.py — 缓存命中率的对照测量

用途：验证"上下文结构改动"对 prompt cache 命中率的影响。

为什么需要它：
    缓存命中率是长会话成本的命门，但凭感觉猜"该怎么排布上下文"不可靠。
    这个脚本跑一个固定的多轮会话，把每次调用的命中率打出来，作为改动前后的对照。

用法：
    # 改动前先跑一次，存基线
    python verify/measure_cache.py --label before

    # 改动后再跑，对比
    python verify/measure_cache.py --label after

注意：会真实调用模型（约 6 次）。请先确认 .env 里的 key 可用。
"""

import argparse
import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 固定的多轮问题 —— 内容不重要，重要的是"多轮"这个结构
TURNS = [
    "你好，请用一句话介绍你自己",
    "刚才你说的是什么？简单复述一下",
    "1 加 1 等于几",
    "再帮我算一下 2 加 2",
    "现在几点了",
    "总结一下我们刚才聊了什么",
]


async def main(label: str):
    from config import client, MODEL_NAME
    from memory import HybridMemory
    from router import SYSTEM_PROMPT_BASE, build_tool_table
    from tools_local import LOCAL_TOOLS, TOOL_REGISTRY
    from agent import agent_loop
    from observability import trace

    # 先记录当前 span 文件行数，只统计本次新产生的
    log_path = trace._daily_log_path()
    before_lines = 0
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            before_lines = len([ln for ln in f if ln.strip()])

    system_prompt = SYSTEM_PROMPT_BASE.format(tool_table=build_tool_table(LOCAL_TOOLS))
    memory = HybridMemory(system_prompt=system_prompt, client=client,
                          session_id=f"cache-measure-{label}")

    print(f"模型：{MODEL_NAME}")
    print(f"开始 {len(TURNS)} 轮对话（label={label}）……\n")

    for i, turn in enumerate(TURNS, 1):
        try:
            await agent_loop(user_message=turn, memory=memory,
                             tools=LOCAL_TOOLS, tool_session_map=None)
        except Exception as e:
            print(f"  第 {i} 轮失败：{type(e).__name__}: {str(e)[:80]}")

    # 统计本次新增的 llm span
    with open(log_path, "r", encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip()][before_lines:]

    llm = []
    for ln in lines:
        try:
            s = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if s.get("kind") == "llm" and s.get("attributes", {}).get("prompt_tokens"):
            llm.append(s)

    print(f"{'轮次':<6}{'输入':>8}{'缓存命中':>10}{'命中率':>9}")
    print("-" * 36)
    total_p, total_c = 0, 0
    for i, s in enumerate(llm, 1):
        a = s["attributes"]
        p, c = a.get("prompt_tokens", 0), a.get("cache_hit_tokens", 0)
        total_p += p
        total_c += c
        rate = f"{c/p:.0%}" if p else "-"
        print(f"{i:<6}{p:>8}{c:>10}{rate:>9}")

    print("-" * 36)
    overall = total_c / total_p if total_p else 0
    print(f"{'合计':<6}{total_p:>8}{total_c:>10}{overall:>8.1%}")

    # 存一份结果，便于前后对比
    out = pathlib.Path(__file__).parent / f"cache-{label}.json"
    out.write_text(json.dumps({
        "label": label, "model": MODEL_NAME,
        "calls": len(llm), "prompt_tokens": total_p,
        "cache_hits": total_c, "hit_rate": round(overall, 4),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已存：{out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run", help="这次测量的标签（before/after）")
    args = ap.parse_args()
    asyncio.run(main(args.label))
