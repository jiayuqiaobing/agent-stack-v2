---
name: agent-stack-debugger
description: Debug agent-stack Python, SSE, tool-call, memory, and provider failures using trace/span logs and the exact request lifecycle. Use when the UI shows empty replies, HTTP 400 tool errors, missing tools, broken streaming, or session inconsistencies.
---

# Agent Stack Debugger

## Trace the request

1. Capture the visible timestamp and session id.
2. Find the matching `trace_id` in `agent-lite/logs/agent-lite.log` and `spans-YYYY-MM-DD.jsonl`.
3. Follow `agent.turn -> llm.chat -> tool.* -> llm.chat -> answer`.
4. For provider 400 errors, inspect the exact message sequence, especially `assistant.tool_calls` and matching `tool_call_id` values.
5. For empty UI replies, compare streamed `delta`, `done`, `usage`, and frontend append behavior.

## Known failure classes

- Missing tool response: sanitize or repair the history before sending it upstream; do not skip tool messages merely to deduplicate UI output.
- Incomplete plan arguments: recover once from the current session, then return a deterministic structured fallback.
- Provider configuration errors: log model/base URL presence without logging secrets.
- Stream exceptions: emit one SSE `error`, finish/export the root span, and restore the UI send state.
- Session deletion: delete browser snapshot before opening a new empty view; never let an empty snapshot overwrite the deleted session.

## Verification

Run:

```powershell
cd agent-lite
& "D:\Miniconda3\envs\my-agent-env\python.exe" -m compileall -q .
& "D:\Miniconda3\envs\my-agent-env\python.exe" verify\verify_runtime.py
& "D:\Miniconda3\envs\my-agent-env\python.exe" -m pytest tests/ --ignore=tests/test_eval.py -q
```
