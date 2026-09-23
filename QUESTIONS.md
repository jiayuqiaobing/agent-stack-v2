# QUESTIONS · 待决问题

> 执行者（opencode）**无法交互式提问**（本环境 `question` 权限被 deny）。
> 需要人决策时，把问题追加到本文件，然后停下（或跳过它先做别的任务）。
>
> 格式见 `docs/5-工作协议.md` 第 6 节。
> **人读完会在下方直接给出答复**，执行者下次启动时应当先检查本文件。

---

## 格式模板（照抄，不要改结构）

```markdown
## [任务编号] 一句话说明卡在哪
- **背景**：为什么会遇到这个问题
- **选项 A**：<具体做法> —— 优点 / 缺点
- **选项 B**：<具体做法> —— 优点 / 缺点
- **我的倾向**：<哪个，为什么>（仅供参考，不构成决定）
- **阻塞程度**：完全阻塞（干不下去） / 可绕过（先做别的）
```

---

## 待决

<!-- 执行者在此下方追加。人答复后，把「## 待决」下已解决的部分移到「## 已解决的」 -->

## [已解决 2026-09-23] ~~Docker 冒烟测试被阻塞：daemon 未启动~~

- **背景**：阶段一验收要求 `docker compose up -d && curl localhost:3100/health`
  返回 `agent: connected`。但执行时 Docker daemon 不可用：
  ```
  failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine;
  check if the path is correct and if the daemon is running
  ```
- **选项 A**：**由人启动 Docker Desktop 后重跑验收**（推荐）
  —— 优点：唯一正确做法；缺点：要等人
- **选项 B**：跳过 docker 验收，只保留 `go build` 通过的证据
  —— 优点：不阻塞；缺点：bug #2 的修复**未经端到端验证**
- **我的倾向**：**A**。容器连通性是 bug #2 的核心修复点，
  `go build` 通过不能证明"容器内能连上"。这条不该跳过。
- **阻塞程度**：**可绕过**（不阻塞其他任务，仅这一条验收项挂起）

---

## [阶段一 · 遗留] 服务启动时 MCP stdio 失败会打印 traceback

- **背景**：本地 MCP 连接失败时（例如解释器不对），
  `mcp/client/stdio.py` 会在 anyio cancel scope 上抛
  `RuntimeError: Attempted to exit cancel scope in a different task`。
  **服务本身能正常启动**（异常被 `except` 兜住），但日志里有一段很吓人的 traceback。
- **选项 A**：维持现状（能跑，只是日志难看）
- **选项 B**：把 MCP 连接放进独立 task 并吞掉该异常，让日志干净
- **我的倾向**：**B**，但优先级低 —— 属"日志卫生"问题，不影响功能
- **阻塞程度**：可绕过

---

---

## 已解决的

### [阶段一验收 ③] Docker 端到端冒烟 —— ✅ 已通过（2026-09-23）

启动 Docker Desktop 后完成验收：
```
curl localhost:3100/health
→ {"agent":"connected","agent_url":"http://agent-lite:8000","gateway":"healthy"}
```
`agent_url` 证明容器内服务名解析成功 —— 这正是 v1 写死 `localhost` 时做不到的。

过程中额外解决：
- 容器名/端口与 v1 项目冲突 → v2 改用 `agent-lite-v2` / `go-gateway-v2`，端口 8100/3100，两边并存
- Docker Desktop 配的镜像加速器返回 403 → Dockerfile 改用可用的国内源
