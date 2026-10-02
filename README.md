# agent-stack v2

> **v1 证明"能跑通"，v2 证明"能运营"。**
>
> 一个 AI 系统上线后，你怎么知道它**好不好**、**贵不贵**、**坏了怎么办**？
> 这个项目用 **可观测 / 可评估 / 可路由** 三件事来回答。

不依赖 LangChain 的手写 Agent 服务：**链路追踪 + 评估体系 + 多上游容错**。

> v1 见 [agent-stack](https://github.com/jiayuqiaobing/agent-stack)（功能版，作者同）。
> v2 是重写，不是迭代 —— v1 保留作对照。

---

## 为什么重写

v1 已经把功能跑通了：手写 agent 循环、混合记忆、RAG、MCP 工具、SSE 流式、Docker。

但它只是**能跑**。上线之后真正的问题一个都没回答：

| 问题 | v1 | v2 |
|------|----|----|
| 这次请求慢在哪？ | 只有一行 token 汇总 | 端到端 trace，逐层 span |
| 改动之后是变好还是变坏？ | 说不清 | 40 条评估集 + 基线对比 |
| 上游挂了怎么办？ | 整个服务不可用 | 多上游路由 + 自动切换 |

---

## 架构

```
                  ┌──────────────────────────────────┐
   HTTP :3100 ───▶│  go-gateway  (Go / Gin)          │
                  │  反向代理 · 限流 · 日志           │
                  │  多上游路由 + failover           │
                  └───────────────┬──────────────────┘
                                  │  X-Trace-Id
                  ┌───────────────▼──────────────────┐
   HTTP :8100 ───▶│  agent-lite  (Python / FastAPI)  │
                  │  ┌────────────────────────────┐  │
                  │  │ 手写 agent loop（无框架）   │  │
                  │  │   ├─ llm.chat span         │  │
                  │  │   ├─ tool.*   span         │  │
                  │  │   └─ rag.search span       │  │
                  │  └────────────────────────────┘  │
                  │  HybridMemory                    │
                  │   ├─ 短期：messages              │
                  │   └─ 长期：ChromaDB + 本地 bge   │
                  │  MCP 工具（本地 stdio + 远程 SSE）│
                  └───────────────┬──────────────────┘
                                  │  span（JSONL 追加写）
                  ┌───────────────▼──────────────────┐
                  │  logs/spans-YYYY-MM-DD.jsonl     │
                  │    ├─▶ GET /metrics   聚合指标    │
                  │    └─▶ eval/          离线评估    │
                  └──────────────────────────────────┘
```

**为什么用 JSONL 存 span**：零依赖、可 `grep` / `jq` 直接查、追加写所以进程崩溃也不丢已落盘数据。
没有引入 Prometheus / OpenTelemetry —— 那会给"手写"的项目带来无谓的重依赖。

---

## 三个能力

### 1. 可观测 —— 「好不好、贵不贵」

`GET /metrics?window=24h` 返回聚合指标：

```json
{
  "requests": {"total": 120, "error_rate": 0.025},
  "latency_ms": {"p50": 1200, "p95": 4300, "p99": 8100},
  "llm": {"calls": 245, "cache_hit_rate": 0.818},
  "tools": {"calls": 88, "success_rate": 0.943,
            "by_name": {"calculate": 40, "read_file": 32}},
  "rag": {"searches": 60, "avg_hit_count": 2.4, "degraded_count": 0},
  "hints": []
}
```

**`cache_hit_rate` 是本项目最关键的一个数字** —— 长会话里大部分 token 是重复发送的上下文，
命中率直接决定账单。v1 特意把 system prompt 放在上下文最前面（为了缓存前缀命中），
这个指标就是验证那个设计到底有没有生效。

**`hints` 会自动把异常信号捞出来**，比如：

> `"缓存命中率 31.2% 偏低（<50%）—— v1 的 system prompt 前置设计可能已失效，输入成本会显著上升"`

trace 用 **W3C Trace Context 格式**（32 位 trace_id / 16 位 span_id），
将来接 OpenTelemetry、Jaeger 不用改。

### 2. 可评估 —— 「改动之后是变好还是变坏」

40 条用例，覆盖五类：工具调用正确性、记忆召回、多轮一致性、错误兜底、基础能力。

```bash
python -m eval.run --dry-run     # 零成本校验数据集
python -m eval.run -v            # 真跑并打印未通过详情
```

跑完自动与基线对比：

```
  基线得分 75.0%  ↑  本次 80.0%   （+5.0%）

  [REGRESSION] 回归（基线过、本次不过）1 条： tool-calc-04
  [FIXED]      修复（基线不过、本次过）1 条： memory-05
```

> **数据集里刻意包含"必须失败"的用例** —— 读不存在的文件、除零、越权读 `/etc/passwd`、
> 执行 `rm -rf /`。一个只会说"好的"的 agent 在这套题上拿不到高分。这是设计意图。

### 3. 可路由 —— 「坏了怎么办」（阶段三）

Go 网关支持**多上游路由 + 429/5xx 自动 failover**：

```bash
go test ./go-gateway/proxy/ -v     # 10 个测试覆盖 failover 各路径
```

上游列表写在 `go-gateway/upstreams.json`，按 `priority` 顺序尝试；
主上游返回 429/5xx 或连接被拒时**自动切到下一个，调用方无感**。

> 这不是纸面需求 —— 开发过程中用的中转站**真实发生过间歇性断流**，
> 这就是为什么它排在路线图里。

---

## 安装

需要 Python 3.11 或更高。密钥只放在你自己的 `.env` 里，不要提交。

```bash
git clone https://github.com/jiayuqiaobing/agent-stack-v2.git
cd agent-stack-v2
python -m venv .venv
```

Windows：

```powershell
.\.venv\Scripts\python -m pip install -r agent-lite/requirements.txt
copy .env.example .env
.\.venv\Scripts\python agent-lite\main.py
```

macOS / Linux：

```bash
.venv/bin/python -m pip install -r agent-lite/requirements.txt
cp .env.example .env
.venv/bin/python agent-lite/main.py
```

浏览器打开 http://localhost:8000 。至少在 `.env` 里填写 `OPENAI_API_KEY`。模型名用 `MODEL_NAME`，不要改代码。

检查是否起来：

```bash
curl http://localhost:8000/health
```

期望包含 `"status": "healthy"` 和 `"version": "0.2.0"`。

回归测试（不调用真实模型）：

```bash
cd agent-lite
python -m pytest tests/ --ignore=tests/test_eval.py -q
```

**Docker 一键部署：**
```bash
docker compose up -d --build
curl localhost:3100/health     # 期望 {"gateway":"healthy","agent":"connected"}
```

---

## 目录

| 路径 | 说明 |
|------|------|
| `agent-lite/` | Python Agent 服务 |
| `agent-lite/observability/` | trace/span 数据模型与指标聚合 |
| `agent-lite/verify/` | **独立验证脚本** —— 不碰 `tests/`，每个能力一份 |
| `agent-lite/tests/` | 回归测试（从 v1 迁移，重写过程的安全网） |
| `go-gateway/` | Go 网关 |
| `eval/` | 评估集与跑分脚本 |
| `docs/` | 规格与契约 |
| `LESSONS.md` | 踩坑库 —— **每个任务开工前必读** |

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/1-接口冻结.md](docs/1-接口冻结.md) | 哪些对外契约不许变 |
| [docs/2-产品规格.md](docs/2-产品规格.md) | 做什么、**不做什么**、验收标准 |
| [docs/3-可观测数据模型.md](docs/3-可观测数据模型.md) | trace/span 数据契约 |
| [docs/4-执行规格.md](docs/4-执行规格.md) | 分阶段执行说明 |
| [docs/5-工作协议.md](docs/5-工作协议.md) | 工作方式（含铁律与失败处理） |
| [LESSONS.md](LESSONS.md) | 踩过的坑 |
| [QUESTIONS.md](QUESTIONS.md) | 待决问题 |

---

## 开发规则

| 规则 | 说明 |
|------|------|
| 🔒 **接口冻结** | 改对外契约前先读 `docs/1-接口冻结.md` 并登记变更 |
| 🧪 **测试是安全网** | 失败只能改实现，不得把 `agent-lite/tests/` 的断言改松 |
| 🚫 **禁止改测试凑绿** | 测试失败只能改实现，不能改断言、不能 skip |
| 📏 **验收即命令** | 每条需求配一条可执行的验收命令，不写"实现了 XX" |
| 🌙 **可观测是旁路** | 任何埋点不得改变业务逻辑的行为与结果 |

---

## 已知限制

- **评估判定基于文本匹配**，不是语义判断（见 `eval/README.md`）
- **暂不检查工具调用本身**，目前从最终回复推断
- **多 Agent 编排未做** —— 它天然要并行，而并行会打爆额度；
  等网关的限流与路由做完再考虑受控实现
- **额度控制与缓存统计未做** —— 阶段三只做了 failover（见 `docs/2-产品规格.md` 第 7 节）

---

## 当前进度

- [x] 阶段一：还债 + 埋点地基（5 个 P0 全部验证通过）
- [x] 阶段二：可观测 + 评估体系（埋点 / `/metrics` / 40 条评估集 / 基线对比）
- [x] 阶段三：Go 网关多上游 failover（10 个测试覆盖）
- [ ] P1：受控两级子代理
