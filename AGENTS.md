# agent-stack v2 · 执行守则

> 本文件是 opencode 的项目级指令，每次启动自动注入。
> **开工前请按顺序读 `docs/` 下的规格文档**（opencode 不会自动解析文件引用，需显式读取）。

---

## 项目性质

这是 **agent-stack 的重写版（v2）**：手写 AI Agent 服务，在 v1 已有能力（agent 循环 + 混合记忆 + RAG + MCP + SSE + Docker）之上，
补齐**可观测 / 可评估 / 可路由**三层工程成熟度。

**v1 在 `../agent-stack`，只作对照，不要修改它。**（v1 当前在 `add-dockerfiles` 分支，那是它们的全部资产所在）

---

## 必读文档（按顺序）

| 顺序 | 文件 | 作用 |
|------|------|------|
| 1 | `docs/1-接口冻结.md` | 哪些对外契约**不许变** |
| 2 | `docs/2-产品规格.md` | 做什么、**不做什么**、验收标准 |
| 3 | `docs/3-可观测数据模型.md` | trace/span 数据契约 |
| 4 | `docs/4-执行规格.md` | 当前阶段的具体任务与命令 |

---

## 🚫 硬性禁止（违反即视为任务失败）

| 禁止项 | 原因 |
|--------|------|
| **修改 `agent-lite/tests/` 下任何文件** | 测试是重写过程的回归安全网。失败只能改实现，**不能改断言、不能 skip**。（唯一例外：任务名明确写了「编写测试」） |
| **读取或修改 `.env`** | 真实密钥所在。需要环境变量时只看 `.env.example` |
| **执行 `git push`** | 可以 `git add` / `git commit`（本地），**推送由人来做** |
| **修改 `docs/` 下任何文档** | 契约由人维护 |
| **回退、删除或修改 `../agent-stack`（v1）** | 它是对照物，不是工作区 |
| **自行决定做 P1 项** | 规格里标 P1 的必须由人决定做不做 |

---

## ✅ 必须遵守

- **接口变更前先查 `docs/1-接口冻结.md`**；变更必须在该文档登记
- **做完必须运行验证命令**，并**贴出真实输出** —— 不允许只描述"已完成"
- **遇到需要架构决策的问题 → 停下来报告**，不要自行决定
- **只做当前阶段 P0 清单里的事**，不要顺手做别的
- **每完成一个任务即停**，等人确认后再继续（阶段间 checkpoint 策略）

### ⚠️ 怎么"问人"（重要）

**你无法向人提问** —— 本环境把 `question` 权限设为 `deny`，交互式提问会被直接拒绝。
所以需要人决策时，**不要试图提问，也不要自己硬做决定**，改为写入文件：

**新建或追加到 `QUESTIONS.md`（项目根目录）**，格式：

```markdown
## [任务编号] 一句话说明卡在哪
- **背景**：为什么会遇到这个问题
- **选项 A**：<具体做法> —— 优点 / 缺点
- **选项 B**：<具体做法> —— 优点 / 缺点
- **我的倾向**：<哪个，为什么>（仅供参考，不构成决定）
- **阻塞程度**：完全阻塞（干不下去） / 可绕过（先做别的）
```

写完后：
1. **在该任务上停下**，不要继续往下做
2. 如果问题是"可绕过"的，跳过它继续做**不依赖它**的其他任务
3. 在最终汇报里**显著提示** `QUESTIONS.md` 有待决项

> 人会在方便时读 `QUESTIONS.md` 并给出答复。你下次启动时会看到答复。
> **阶段二开工前，先检查 `QUESTIONS.md` 是否有未答复项。**

---

## 常用命令

```bash
# 跑测试（test_eval.py 会真调 LLM，不纳入常规回归）
cd agent-lite && pytest tests/ --ignore=tests/test_eval.py -v

# 手动起服务
cd agent-lite && python main.py
```

**Python 解释器**：`D:\Miniconda3\envs\test-env\python.exe`
> ⚠️ 用 `my-agent-env` 会报 `ModuleNotFoundError: chromadb`，依赖不全。

---

## 项目特定的坑（v1 踩过，v2 别再踩）

| 坑 | 应对 |
|----|------|
| **DeepSeek 不支持 embedding**（`text-embedding-3-small` 返 404） | RAG 必须用本地模型 `BAAI/bge-small-zh-v1.5`（fastembed） |
| 国内下 HF 模型超时 | `HF_ENDPOINT=https://hf-mirror.com` + `HF_HUB_DISABLE_XET=1` + `HF_XET_DISABLE=1`，**必须在 `import fastembed` 之前设置**（`huggingface_hub` 在 import 时就读取） |
| Windows GBK 控制台打不了 emoji | 脚本输出用 `[OK]` / `[FAIL]`，不要用 ✅❌ |
| ChromaDB 多会话串味 | 写入时打 `metadatas=[{"session_id": ...}]`，查询用 `where` 过滤 |
| 模型名写错 | 必须是 `provider/model` 格式；DeepSeek 可用 `deepseek-v4-pro` / `deepseek-flash`，**没有 `deepseek-chat`** |

---

## 汇报格式

每个任务完成后，按这个格式汇报：

```
任务：<编号与名称>
改动文件：<列表>
验证命令：<原样命令>
真实输出：<粘贴，不要概括>
遗留问题：<有就写，没有写"无">
```
