# 评估体系

> v2 三个核心能力之一：**"改动之后，是变好还是变坏？"**
>
> 没有基线的"评估体系"等于没有。**第一次跑出来的分数就是基线，之后每次改动都要跟它比。**

---

## 怎么用

```bash
cd D:/Python/janyu2cs_projects/agent-stack-v2

# 1) 干跑：只校验数据集结构，不花钱
python -m eval.run --dry-run

# 2) 真跑：对每个用例调用 agent（需要 OPENAI_API_KEY）
python -m eval.run

# 3) 只看某一类
python -m eval.run --category tool

# 4) 调试：只跑前 3 条
python -m eval.run --limit 3 -v
```

结果自动存到 `eval/results/run-<时间戳>.json`。

**第一次跑完，把结果定为基线：**
```bash
cp eval/results/run-<时间戳>.json eval/results/baseline.json
```

之后每次改动重跑，对比 `summary.score` 就知道是变好还是变坏。

---

## 数据集

`dataset.jsonl` —— 一行一个用例（JSONL 便于 diff 和追加）。

```json
{
  "id": "tool-calc-01",
  "category": "tool",
  "turns": ["3 + 5 等于多少"],
  "check": { "type": "contains", "value": "8" },
  "note": "基础加法"
}
```

| 字段 | 说明 |
|------|------|
| `turns` | 多轮提问，依次发送。**判定看最后一轮的回复** |
| `check.type` | `contains`（包含子串）/ `regex`（正则，忽略大小写）/ `any_of`（任一命中） |
| `check.value` | 对应 type 的匹配目标 |

**每个用例用独立 session** —— 防止用例之间记忆污染。

---

## 当前覆盖（40 条）

| 分类 | 条数 | 考什么 |
|------|------|--------|
| `tool` | 12 | 是否**真的调用工具**而非心算/编造；无对应工具时是否如实说明 |
| `memory` | 8 | 多轮对话中能否召回之前说过的信息（v1 修过"串味"，这条守住） |
| `multiturn` | 8 | 指代理解、信息更新（改口后必须用新值）、链式运算 |
| `error` | 6 | 读不存在的文件、除零、越界请求、危险操作 —— **必须如实报错，不能编造** |
| `basic` | 6 | 连通性、指令遵循、开放性问答 |

> 数据集刻意包含**"必须失败"的用例**（如读不存在的文件、拒绝危险操作）。
> 一个只会说"好的"的 agent 在这套题上拿不到高分 —— 这是设计意图。

---

## 加用例

直接在 `dataset.jsonl` 末尾追加一行即可。加完跑一次 `--dry-run` 校验结构：

```
[OK] 数据集结构校验通过
分类分布：{'tool': 12, 'memory': 8, ...}
```

id 重复、`check.type` 非法、`turns` 为空都会被拦下来。

---

## ⚠️ 已知局限

1. **判定基于文本匹配**，不是语义判断。
   比如 `contains: "8"` 可能被 `"18"` 误伤 —— 写用例时 value 要选得足够特异。
2. **暂不检查工具调用本身**（调了哪个工具、参数对不对）。
   目前只从**最终回复**推断。真正的工具级断言要等 `trace` 埋点接进 `agent_loop`
   （阶段二后续任务：把 span 落到 llm / tool 调用点上）。
3. **测试用例是"答案易得"型** —— 分数高不代表模型强，只代表**这套基本盘没坏**。
   它的作用是回归检测，不是能力排名。
