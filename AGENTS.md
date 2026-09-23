# agent-stack v2

手写 AI Agent 服务（重写版）。目标：证明作者能独立写出这样一个东西。
**v1 在 `../agent-stack`（分支 `add-dockerfiles`），只作对照，不要修改。**

**详细规则见 `docs/5-工作协议.md`；踩坑见 `LESSONS.md`（每个任务开工前必读）。**

---

## 六条铁律（违反即停）

| # | 铁律 | 怎么判断 |
|---|------|----------|
| 1 | 禁止修改 `agent-lite/tests/` | `git diff --stat` 不得出现该目录 |
| 2 | 禁止谎报结果 | 必须贴**真实命令输出**，不许写"测试通过"了事 |
| 3 | 禁止回避失败 | 失败只能改实现；不得 skip / xfail / 改断言 |
| 4 | 禁止读 `.env` | 需要环境变量时看 `.env.example` |
| 5 | 禁止 `git push` | 只能本地 `git commit` |
| 6 | 禁止自行决定 P1 项 | 只做当前阶段 P0 清单里的 |

---

## 每个任务的固定节奏

```
0. 读 LESSONS.md
1. 先写独立验证脚本（放 agent-lite/verify/，不要碰 tests/）
2. 写实现
3. 跑验证脚本 → 必须通过
4. 跑回归测试 → 必须仍全绿
5. 自查（见下）
6. git commit  ← 存档点
7. 按「汇报格式」报告
```

**先测试后实现**：没验证脚本就下手 = 边写边猜，猜错要重写 —— **返工最烧钱**。

**自查清单**：硬编码模型名/路径/key？接口变更登记了吗？有 `except: pass` 吞异常吗（v1 因此 RAG 静默失效）？新依赖进 `requirements.txt` 了吗？留了调试 `print` 吗？

**⚠️ 写入/复制源码文件后，必须验证它能被解释器解析**（不能只看"文件存在 + 大小合理"）：
```bash
python -c "import ast,pathlib; ast.parse(pathlib.Path('<文件>').read_text(encoding='utf-8'))"
```
> 踩过的坑：**PowerShell 的 `>` 重定向默认写 UTF-16**，复制出来的 .py 文件看着大小正常但 Python 根本读不了。复制源码优先用 **Git Bash** 而不是 PowerShell。详见 `LESSONS.md`。

---

## 上游断线怎么办（实测发生过）

报错 `模型服务暂时不可用，请稍后重试`：

1. 等 **10 秒**，原样重试
2. 仍失败 → 等 **30 秒**，再试
3. 仍失败 → 换 `cheapai/grok-4.6`
4. 仍失败 → 写 `QUESTIONS.md` 后停下

❌ 不许快速连试、不许默默跳过、不许假装无事发生。

---

## 怎么"问人"（你无法交互式提问）

本环境 `question` 权限被 deny —— 问了会被拒。需要人决策时，**追加到 `QUESTIONS.md`**：

```markdown
## [任务号] 一句话说明卡在哪
- 背景 / 选项 A（优缺点）/ 选项 B（优缺点）/ 我的倾向 / 阻塞程度(完全阻塞|可绕过)
```

**可绕过** → 跳过它先做别的；**完全阻塞** → 停下等人。

> 写进 `QUESTIONS.md` 不是回避，是承认信息不够。**假装解决才是回避。**

---

## 命令

```powershell
# 回归测试（test_eval 真调 LLM，不纳入常规回归）
cd agent-lite; pytest tests/ --ignore=tests/test_eval.py -v

# 起服务
cd agent-lite; python main.py

# 读 v1 文件（不要切那个 repo 的分支）
git -C D:/Python/janyu2cs_projects/agent-stack show add-dockerfiles:agent-lite/<文件>
```

**Python 解释器**：`D:\Miniconda3\envs\my-agent-env\python.exe`
> ⚠️ **不要用 `test-env`** —— 它已损坏（解释器与标准库被删，仅剩 site-packages）。
> 详见 `LESSONS.md`。装包也一律装进 `my-agent-env`。

---

## 项目特定的坑

| 坑 | 应对 |
|----|------|
| DeepSeek 不支持 embedding | RAG 用本地 `BAAI/bge-small-zh-v1.5`（fastembed） |
| 下载 HF 模型 401 | `HF_ENDPOINT=hf-mirror` + `HF_HUB_DISABLE_XET=1` + `HF_XET_DISABLE=1`，**必须在 `import fastembed` 之前设** |
| `except: pass` 吞异常 | v1 的 RAG 因此**静默失效**。异常必须如实抛出或记日志 |
| Windows GBK 控制台 | 脚本输出用 `[OK]`/`[FAIL]`，**不要用 emoji** |
| ChromaDB 串味 | 写入打 `metadatas=[{"session_id": ...}]`，查询用 `where` 过滤 |
| 模型名写错 | 必须 `provider/model` 格式：`cheapai/grok-4.7`、`cheapai/grok-4.6` |
| **假流式** | 攒完再一次性吐 = 假流式。**v2 要求真流式**（首字时间必须显著小于总耗时） |

---

## 前端要求

图形界面（不能是纯终端文本输出）；**必须真流式**；界面能看到 trace / 工具调用过程；干净克制、暗色系。

---

## 汇报格式（缺项视为未完成）

```
任务：<编号与名称>
改动文件：<列表>
验证命令：<原样命令>
真实输出：<粘贴，不要概括>
回归测试：<真实输出>
LESSONS.md 新增：<有无，第几条>
遗留问题：<有就写，没有写"无">
```
