# agent-stack v2

> 手写 AI Agent 的**可观测 / 可评估 / 可路由**版本。
> v1 见 [agent-stack](https://github.com/jiayuqiaobing/agent-stack)（同作者，功能版）。

---

## 这是什么

一个不依赖 LangChain 的手写 Agent 服务，在 v1 已有能力（agent 循环 + 混合记忆 + RAG + MCP + SSE + Docker）之上，
补齐工程成熟度：**链路追踪、评估体系、多上游路由**。

**v2 不是 v1 的延续，是重写。** v1 保留作为对照。

---

## 架构

```
                  ┌──────────────────────────────┐
   HTTP :3000 ───▶│  go-gateway (Go)             │
                  │  路由 · 限流 · trace 注入     │
                  │  多上游 failover (阶段三)     │
                  └──────────────┬───────────────┘
                                 │ X-Trace-Id
                  ┌──────────────▼───────────────┐
   HTTP :8000 ───▶│  agent-lite (Python/FastAPI) │
                  │  手写 agent loop · SSE        │
                  │  HybridMemory ├─ ChromaDB RAG │
                  │               └─ 本地 bge 模型│
                  └──────────────┬───────────────┘
                                 │ span JSONL
                  ┌──────────────▼───────────────┐
                  │  logs/spans-*.jsonl          │
                  │  → GET /metrics 聚合          │
                  │  → eval/ 评估集消费           │
                  └──────────────────────────────┘
```

---

## 文档（**先读文档再读代码**）

| 文档 | 内容 | 给谁看 |
|------|------|--------|
| [docs/1-接口冻结.md](docs/1-接口冻结.md) | 不许变的对外契约 | 所有人 |
| [docs/2-产品规格.md](docs/2-产品规格.md) | 做什么 / 不做什么 / 验收标准 | 所有人 |
| [docs/3-可观测数据模型.md](docs/3-可观测数据模型.md) | trace/span schema | 开发者 |
| docs/4-执行规格.md | 分阶段执行说明 | 执行者（AI agent） |

---

## 快速开始

> **当前状态：骨架阶段，业务代码尚未写入。**

```bash
# 1. 配置
cp .env.example .env
# 编辑 .env，至少填 OPENAI_API_KEY 和 API_KEY

# 2. 安装依赖
pip install -r agent-lite/requirements.txt

# 3. 跑测试（回归安全网）
cd agent-lite && pytest tests/ --ignore=tests/test_eval.py -v
```

---

## 开发规则

| 规则 | 说明 |
|------|------|
| 🔒 **接口冻结** | 改对外契约前先读 `docs/1-接口冻结.md`，变更必须在其中登记 |
| 🧪 **测试是安全网** | `agent-lite/tests/` 下的测试**不得为了让功能通过而修改** |
| 🚫 **禁止改测试凑绿** | 测试失败只能改实现，不能改断言、不能 skip |
| 📝 **P1 不自主决策** | 规格里标 P1 的事项必须由人决定做不做 |
| 🛑 **阶段间停机** | 每阶段完成即停，等人确认 |

---

## 当前进度

- [x] 接口盘点（基线 `b9cd2cc`）
- [x] 规格文档 1–3
- [ ] 仓库骨架 ← **在这里**
- [ ] 阶段一：还债 + 埋点地基
- [ ] 阶段二：可观测 + 评估体系
- [ ] 阶段三：Go 网关重做
