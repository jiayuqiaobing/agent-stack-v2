---
name: agent-stack-observability
description: Improve logging, tracing, metrics, and verification in this agent-stack project without leaking secrets or changing business behavior. Use when adding diagnostics, error handling, telemetry, or operational safeguards.
---

# Agent Stack Observability

- Text logs live under `agent-lite/logs/agent-lite.log` and rotate daily.
- Structured spans live under `agent-lite/logs/spans-YYYY-MM-DD.jsonl`.
- Every request must be correlatable by `trace_id`, `span_id`, and `session_id`.
- Every tool span records tool name, source, argument length, success, error type, and duration.
- Never log API keys, complete attachments, raw credentials, or full sensitive tool arguments.
- Observability is a side channel: export failures must never change the response.
- Add a focused `verify/` check for every new log field or error path.
- Report real command output; do not summarize a failing check as passing.
