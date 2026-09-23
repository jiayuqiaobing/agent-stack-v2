"""verify_span_emission.py — 验证埋点真的把 span 写进了 JSONL

不依赖真实模型：用假 key 触发真实的失败路径，验证错误 span 也能正确落盘。
验收 docs/3-可观测数据模型.md 第 7.1 节的五个采集点。
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("OPENAI_API_KEY", "sk-dummy-for-verify")
os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com/v1")

from observability import trace as T

results = []
LOG_PATH = T._daily_log_path()


def read_new_spans(before_lines: int) -> list[dict]:
    """读取文件里第 before_lines 行之后的所有 span"""
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines[before_lines:]]


def count_lines() -> int:
    if not os.path.exists(LOG_PATH):
        return 0
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        return len([ln for ln in f if ln.strip()])


def check(label, cond):
    results.append(bool(cond))
    print(f"[{'OK' if cond else 'FAIL'}] {label}")


# ---------------------------------------------------------------- 1. 工具 span（成功）
before = count_lines()
from tools_local import execute_tool

tid, sid_, ctx = T.begin_trace()
with ctx:
    asyncio.run(execute_tool("calculate", {"expression": "2+3"}))

# 工具自身不打 span（那是 agent 的职责），所以这里手动模拟 agent 的埋点写法
before2 = count_lines()
tool_span = T.make_span("tool.calculate", "tool",
                        attributes={"tool_name": "calculate", "source": "local",
                                    "success": True, "error_type": None, "args_size": 10})
T.finish_span(tool_span, status="ok")
T.export_span(tool_span)

spans = read_new_spans(before2)
check("工具 span 已落盘", len(spans) == 1)
if spans:
    s = spans[0]
    check("工具 span 是 tool 类型", s["kind"] == "tool")
    check("工具 span 含 success", s["attributes"].get("success") is True)
    check("工具 span 含 source", s["attributes"].get("source") == "local")
    check("工具 span name 用低基数形式", s["name"] == "tool.calculate")

# ---------------------------------------------------------------- 2. LLM span 的错误路径
# agent_loop 内部会为每次 LLM 调用建 span；用假 key 触发真实的失败
from config import client
from memory import HybridMemory
from agent import agent_loop


async def drive_llm_error():
    mem = HybridMemory(system_prompt="test", client=client, session_id="verify-span")
    try:
        await agent_loop(user_message="hi", memory=mem)
    except Exception:
        pass        # 期望失败——假 key


before3 = count_lines()
asyncio.run(drive_llm_error())
spans = read_new_spans(before3)

llm_spans = [s for s in spans if s["kind"] == "llm"]
check("LLM 调用失败时仍然产生 span", len(llm_spans) >= 1)
if llm_spans:
    s = llm_spans[0]
    check("失败的 LLM span 状态为 error", s["status"] == "error")
    check("失败的 LLM span 记录 error.type", (s.get("error") or {}).get("type") is not None)
    check("LLM span 记录 model 名", s["attributes"].get("model") is not None)
    check("LLM span 已计算耗时", s.get("duration_ms") is not None)

# ---------------------------------------------------------------- 3. 上下文串联
before4 = count_lines()
with T.start_trace(session_id="verify-tree") as root:
    # 子 span 在上下文内创建，应自动挂到根 span
    child1 = T.finish_span(T.make_span("llm.chat", "llm"))
    child2 = T.finish_span(T.make_span("tool.calculate", "tool"))
T.finish_span(root)
for s in (root, child1, child2):
    T.export_span(s)

group = read_new_spans(before4)
check("一次 trace 产生 3 个 span", len(group) == 3)
if len(group) == 3:
    root_out = next(s for s in group if s["kind"] == "agent")
    children = [s for s in group if s["kind"] != "agent"]
    check("三个 span 共享同一 trace_id", len({s["trace_id"] for s in group}) == 1)
    check("根 span 的 parent 为 None", root_out["parent_span_id"] is None)
    check("根 span 的 id 等于 start_trace 返回的根 id", root_out["span_id"] == root["span_id"])
    check("子 span 的 parent 都指向根 span",
          all(s["parent_span_id"] == root_out["span_id"] for s in children))
    check("session_id 透传到全部 span",
          all(s["session_id"] == "verify-tree" for s in group))

# ---------------------------------------------------------------- 4. 落盘格式
check("落盘是 JSONL（一行一个 span）", count_lines() > before)
with open(LOG_PATH, "r", encoding="utf-8") as f:
    last = f.readlines()[-1]
check("最后一行是合法 JSON", bool(json.loads(last)))

print()
if all(results):
    print(f"[OK] verify_span_emission 全部通过（{len(results)}/{len(results)}）")
    raise SystemExit(0)
print(f"[FAIL] {results.count(False)}/{len(results)} 项未通过")
raise SystemExit(1)
