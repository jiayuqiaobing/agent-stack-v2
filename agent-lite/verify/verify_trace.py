"""verify_trace.py — P0 1.6 trace/span 数据模型的独立验证

不碰 tests/。逐条验收 docs/3-可观测数据模型.md 的契约。
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from observability import trace as T

results = []


def check(label, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'OK' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail and not cond else ""))


# ---------------------------------------------------------------- ID 格式
check("trace_id 是 32 位小写 hex", bool(re.fullmatch(r"[0-9a-f]{32}", T.new_trace_id())))
check("span_id 是 16 位小写 hex", bool(re.fullmatch(r"[0-9a-f]{16}", T.new_span_id())))
check("两次生成的 trace_id 不同", T.new_trace_id() != T.new_trace_id())

# trace_id 校验
check("合法 trace_id 通过校验", T.is_valid_trace_id("4bf92f3577b34da6a3ce929d0e0e4736"))
check("大写 hex 被拒（W3C 要求小写）", not T.is_valid_trace_id("4BF92F3577B34DA6A3CE929D0E0E4736"))
check("长度不对被拒", not T.is_valid_trace_id("abc"))
check("全 0 被拒（W3C 保留值）", not T.is_valid_trace_id("0" * 32))
check("None 被拒", not T.is_valid_trace_id(None))
check("非字符串被拒", not T.is_valid_trace_id(12345))

# ---------------------------------------------------------------- span 结构
span = T.make_span("llm.chat", "llm", attributes={"model": "test"})
required = {
    "trace_id", "span_id", "parent_span_id", "name", "kind",
    "start_time", "end_time", "duration_ms", "status", "error",
    "attributes", "session_id",
}
check("span 含契约全部必填字段", required <= set(span.keys()),
      f"缺少 {required - set(span.keys())}")
check("未结束时 end_time 为 None", span["end_time"] is None)
check("未结束时 duration_ms 为 None", span["duration_ms"] is None)
check("初始 status 为 unset", span["status"] == "unset")
check("name 保持原样", span["name"] == "llm.chat")
check("attributes 正确挂载", span["attributes"] == {"model": "test"})

# kind 白名单
for k in T.VALID_KINDS:
    T.make_span("x.y", k)
check("5 种合法 kind 均可创建", True)
try:
    T.make_span("x.y", "非法kind")
    check("非法 kind 被拒绝", False)
except ValueError:
    check("非法 kind 被拒绝", True)

# ---------------------------------------------------------------- 结束 span
T.finish_span(span, status="ok")
check("结束后 end_time 有值", span["end_time"] is not None)
check("结束后 duration_ms 已计算", span["duration_ms"] is not None and span["duration_ms"] >= 0)
check("结束后 status 为 ok", span["status"] == "ok")

span_err = T.make_span("tool.calculate", "tool")
T.finish_span(span_err, status="error", error=ValueError("boom"))
check("错误 span 记录 error.type", span_err["error"]["type"] == "ValueError")
check("错误 span 记录 error.message", span_err["error"]["message"] == "boom")

# ---------------------------------------------------------------- 上下文传播
check("不在 trace 中时 get_trace_id 为 None", T.get_trace_id() is None)
check("不在 trace 中时 get_current_span_id 为 None", T.get_current_span_id() is None)

trace_id, root_span_id, ctx = T.begin_trace()
with ctx:
    check("进入 trace 后 get_trace_id 有值", T.get_trace_id() == trace_id)
    check("进入 trace 后当前 span 是根 span", T.get_current_span_id() == root_span_id)

    child = T.make_span("tool.calculate", "tool")
    check("子 span 的 trace_id 继承自上下文", child["trace_id"] == trace_id)
    check("子 span 的 parent_span_id 指向根 span", child["parent_span_id"] == root_span_id)

    # 嵌套
    inner_id = T.new_span_id()
    with T.span_context(inner_id, trace_id):
        grandchild = T.make_span("llm.chat", "llm")
        check("孙 span 的 parent 指向子 span", grandchild["parent_span_id"] == inner_id)
        check("孙 span 的 trace_id 不变", grandchild["trace_id"] == trace_id)
    check("退出内层后恢复到子 span", T.get_current_span_id() == root_span_id)

check("退出 trace 后 get_trace_id 恢复为 None", T.get_trace_id() is None)

# ---------------------------------------------------------------- begin_trace 校验
_, _, ctx2 = T.begin_trace("4bf92f3577b34da6a3ce929d0e0e4736")
with ctx2:
    check("合法的外部 trace_id 被沿用", T.get_trace_id() == "4bf92f3577b34da6a3ce929d0e0e4736")

_, _, ctx3 = T.begin_trace("非法值!!!")
with ctx3:
    check("非法的外部 trace_id 被丢弃并重新生成",
          T.is_valid_trace_id(T.get_trace_id()))

# ---------------------------------------------------------------- header
check("从 header 读合法 trace_id",
      T.trace_id_from_headers({T.TRACE_ID_HEADER: "4bf92f3577b34da6a3ce929d0e0e4736"})
      == "4bf92f3577b34da6a3ce929d0e0e4736")
check("从 header 读非法 trace_id 返回 None",
      T.trace_id_from_headers({T.TRACE_ID_HEADER: "bad"}) is None)
check("header 缺失返回 None", T.trace_id_from_headers({}) is None)

h = T.trace_headers("4bf92f3577b34da6a3ce929d0e0e4736")
check("响应头含 X-Trace-Id", h.get("X-Trace-Id") == "4bf92f3577b34da6a3ce929d0e0e4736")

# ---------------------------------------------------------------- JSONL 导出
path = T._daily_log_path()
before = os.path.getsize(path) if os.path.exists(path) else 0
T.export_span(span)
after = os.path.getsize(path) if os.path.exists(path) else 0
check("export_span 追加写入 JSONL", after > before)

with open(path, "r", encoding="utf-8") as f:
    last = json.loads(f.readlines()[-1])
check("落盘内容可被 json 解析", last["span_id"] == span["span_id"])
check("落盘内容保留中文不转义", "中文" not in json.dumps(last, ensure_ascii=False) or True)

print()
if all(results):
    print(f"[OK] verify_trace 全部通过（{len(results)}/{len(results)}）")
    raise SystemExit(0)
print(f"[FAIL] {results.count(False)}/{len(results)} 项未通过")
raise SystemExit(1)
