"""verify_trace_http.py — 验证 trace 中间件的 HTTP 行为

验收 docs/3-可观测数据模型.md 第 6.1 节：
    - X-Trace-Id 透传、非法丢弃、缺失时生成、响应头回写
用最小 app 测中间件本身，避免拉起真实 agent 时去连 MCP 服务器。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from observability import trace

app = FastAPI()


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    incoming = trace.trace_id_from_headers(request.headers)
    trace_id, root_span_id, ctx = trace.begin_trace(incoming)
    with ctx:
        request.state.trace_id = trace_id
        request.state.span_id = root_span_id
        response = await call_next(request)
    response.headers[trace.TRACE_ID_HEADER] = trace_id
    return response


@app.get("/probe")
async def probe(request: Request):
    """回显中间件写进 request.state 的 trace 信息"""
    return {
        "trace_id": getattr(request.state, "trace_id", None),
        "span_id": getattr(request.state, "span_id", None),
        "ctx_trace_id": trace.get_trace_id(),
    }


results = []


def check(label, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'OK' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail and not cond else ""))


client = TestClient(app)

# --- 1. 不带 header：服务端生成 ---
r = client.get("/probe")
body = r.json()
resp_tid = r.headers.get("X-Trace-Id")
check("无 header 时，响应头仍有 X-Trace-Id", bool(resp_tid))
check("生成的 trace_id 符合 W3C 格式", trace.is_valid_trace_id(resp_tid))
check("request.state 与响应头的 trace_id 一致", body["trace_id"] == resp_tid)
check("request.state 带上了根 span_id", trace.is_valid_trace_id(body["span_id"].ljust(32, "0")))

# --- 2. 带合法 header：透传 ---
given = "4bf92f3577b34da6a3ce929d0e0e4736"
r2 = client.get("/probe", headers={"X-Trace-Id": given})
check("合法 X-Trace-Id 被透传", r2.headers.get("X-Trace-Id") == given)
check("业务代码能看到同一个 trace_id", r2.json()["trace_id"] == given)

# --- 3. 带非法 header：丢弃并重新生成 ---
r3 = client.get("/probe", headers={"X-Trace-Id": "not-a-valid-trace-id"})
new_tid = r3.headers.get("X-Trace-Id")
check("非法 X-Trace-Id 被丢弃", new_tid != "not-a-valid-trace-id")
check("非法值被替换为合法的新 id", trace.is_valid_trace_id(new_tid))

# --- 4. 大写 hex 也应被拒（W3C 要求小写）---
r4 = client.get("/probe", headers={"X-Trace-Id": given.upper()})
check("大写 hex 被视为非法并重新生成",
      r4.headers.get("X-Trace-Id") != given.upper()
      and trace.is_valid_trace_id(r4.headers.get("X-Trace-Id")))

# --- 5. 每次请求是独立的 trace ---
a = client.get("/probe").headers.get("X-Trace-Id")
b = client.get("/probe").headers.get("X-Trace-Id")
check("不同请求产生不同 trace_id", a != b)

# --- 6. 中间件不得影响业务响应体 ---
check("业务响应体正常返回（旁路不影响主路）", r.json().get("trace_id") is not None)

print()
if all(results):
    print(f"[OK] verify_trace_http 全部通过（{len(results)}/{len(results)}）")
    raise SystemExit(0)
print(f"[FAIL] {results.count(False)}/{len(results)} 项未通过")
raise SystemExit(1)
