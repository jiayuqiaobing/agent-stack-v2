---
name: agent-stack-maintainer
description: Maintain and extend this agent-stack project by following its layered architecture, runtime capability boundaries, frozen API contracts, and verification protocol. Use for any feature, refactor, bug fix, or cleanup in agent-lite.
---

# Agent Stack Maintainer

Use `AGENTS.md`, `LESSONS.md`, `docs/5-工作协议.md`, `docs/6-项目结构哲学.md`, and `docs/7-后继项目维护手册.md` before editing.

## Non-negotiable boundaries

- Never modify `agent-lite/tests/`.
- Never read `.env`; use `.env.example` for configuration shape.
- Never push or commit unless explicitly requested.
- Do not add a new capability to `agent.py` or `tools_local.py` when it belongs in `agent-lite/runtime/<capability>.py`.
- Preserve tool-call protocol: every assistant tool call requires exactly one matching tool message.
- Preserve SSE event compatibility unless an interface change is explicitly approved.

## Change workflow

1. Map the request to HTTP, orchestration, capability, memory, observability, or frontend.
2. Add an independent verification under `agent-lite/verify/` before implementation.
3. Implement the smallest layer-local change.
4. Run compileall, the focused verify script, and the normal pytest regression.
5. Inspect `git diff --check` and confirm tests were untouched.

## Failure discipline

Never turn an exception into an empty reply. Record session, trace, phase, capability, and exception type. If a recovery path fails, return a structured fallback marked as fallback or unavailable; never claim the result was reviewed.
