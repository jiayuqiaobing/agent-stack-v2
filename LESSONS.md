# LESSONS · 踩坑记录

> **每个任务开工前必读。** 不读 = 没记。
>
> 记录规则见 `docs/5-工作协议.md` 第 4 节：
> **每当一个问题花了超过一次尝试才解决，就追加一条。**

---

## [v1 遗留] DeepSeek 不支持 embedding

- **症状**：RAG 检索永远返回空，但没有任何报错 —— **静默失效**
- **根因**：`embeddings.create(model="text-embedding-3-small")` 在 DeepSeek 上返回 **404**，
  而调用处写了 `except: pass`，异常被吞掉
- **修法**：改用本地模型 `BAAI/bge-small-zh-v1.5`（fastembed 加载，512 维，`cache_dir=agent-lite/models/`）
- **如何避免**：
  1. **永远不要用 `except: pass` 吞异常** —— 至少要 `logger.warning(..., exc_info=True)`
  2. 外部依赖（embedding、模型 API）第一次接入时，**先单独写脚本验证它能通**，再接进主流程
  3. 任何"降级"路径都要能被观测（v2 的 `rag.degraded` 字段就是为此设的）

---

## [v1 遗留] 国内下载 HuggingFace 模型 401

- **症状**：`HF_ENDPOINT=https://hf-mirror.com` 设了，下载仍报 **401**
- **根因**：hf-mirror **不支持 Xet 存储后端的 CAS 服务器**，而 huggingface_hub 默认走 Xet
- **修法**：同时设 `HF_HUB_DISABLE_XET=1` 和 `HF_XET_DISABLE=1`
- **如何避免**：**必须写在 `import fastembed` 之前** —— huggingface_hub 在 **import 时**就读这些环境变量，
  写在 import 之后就无效了。顺序错了极难排查（看起来完全没用）。

---

## [v1 遗留] ChromaDB 多会话串味

- **症状**：A 会话的对话内容，跑到 B 会话的检索结果里
- **根因**：所有 session 共用一个 collection，检索时没有过滤条件
- **修法**：写入时打标 `metadatas=[{"session_id": session_id}]`，`query` / `get` 时用 `where={"session_id": ...}` 过滤
- **如何避免**：**共享存储 + 无隔离 = 必然串味**。凡是"多个上下文共用一份数据"，第一件事就是设计隔离键。

---

## [v1 遗留] Windows GBK 控制台打不出 emoji

- **症状**：脚本跑到打印 emoji 时崩 `UnicodeEncodeError: 'gbk' codec can't encode character...`
- **根因**：Windows 控制台默认 GBK 编码
- **修法**：脚本输出改用 `[OK]` / `[FAIL]` 这类 ASCII 标记
- **如何避免**：写脚本时**默认不用 emoji 和特殊符号**（`✅` `❌` `→` `¥` 都算）。
  临时绕过可设 `PYTHONIOENCODING=utf-8`，但**不要依赖它** —— 别人跑你的脚本不一定设了。

---

## [v1 遗留] `.gitignore` 漏掉嵌套目录

- **症状**：`agent-lite/chroma_db/`（向量数据库）差点被提交到公开仓库
- **根因**：`.gitignore` 里只写了顶层的 `chroma_db/`
- **修法**：写成不限制层级的 `chroma_db/`（不带前导斜杠即可匹配任意层级）
- **如何避免**：写完 `.gitignore` 后，**用 `git status` 验证目标文件确实被忽略了**，别靠眼睛看。

---

## [v1 遗留] 同一个配置键写在两个 `.env.example` 里

- **症状**：v1 的 `API_KEY` 加进了 `agent-lite/.env.example`，但**没加进根目录的 `.env.example`**；
  而 `docker-compose.yml` 读的是**根目录**的 `.env` → **容器部署时鉴权静默失效**（未配置即放行）
- **根因**：两个 `.env.example` 并存，改了一个忘了另一个
- **修法**：v2 **只保留根目录一个 `.env.example`**，两个服务共用
- **如何避免**：**同一个配置只允许有一个来源**。发现第二份就删掉它，不要"两边都更新"。

---

## [v1 遗留] 假流式

- **症状**：界面上"看起来是流式"，实际是等模型全部生成完才一次性吐出来
- **根因**：用非流式 API 拿到完整结果，再切片慢慢显示 —— 观感像流式，但**首字延迟等于总耗时**
- **修法**：用真正的 streaming API，逐 chunk 转发
- **如何避免**：**"首字时间（TTFT）"和"总耗时"分开记录**。两者接近 = 假流式。
  v2 的 `llm` span 里记录 `start_time` / `end_time`，前端加首字打点，就是为此。

---

## [2026-09-23] 换个 shell 跑 opencode，报"API Key 无效"

- **症状**：PowerShell 里 `opencode run` 正常，换到 Git Bash 里跑同一个命令，
  报 `AI_APICallError: API Key 无效或不可用，请检查是否填写正确...`，
  且**所有模型都报同样错**（不是某个模型的问题）
- **根因**：`CHEAPAI_API_KEY` 是用 PowerShell 语法（`$env:` / `setx`）设的，
  **Git Bash 读不到** —— 环境变量不跨 shell 传递
- **修法**：**跑 opencode 一律用 PowerShell**（当初设 key 的那个 shell）
- **如何避免**：
  1. **报"API Key 无效"时，先确认 shell 对不对**，别急着怀疑 key 过期或中转站跑路
  2. **"所有模型同时报 key 错" 这个特征**基本可以断定是环境问题而非上游问题 ——
     如果是上游挂了，只会挂某几个模型（今天 grok-4.7 单独挂过，grok-4.6 正常，就是反例）

---

## [2026-09-23] `test-env` 环境已损坏，全靠 `my-agent-env`

- **症状**：`D:\Miniconda3\envs\test-env\python.exe` 不存在，
  命令行报 `No such file or directory`
- **根因**：**不是 python.exe 单独丢失，是整个环境被部分删除**：

  | 检查项 | 状态 |
  |--------|------|
  | `python.exe` / `python313.dll` / `DLLs\` | ❌ 缺 |
  | `Lib\os.py` / `Lib\encodings\`（标准库） | ❌ 缺 |
  | `conda-meta\*.json`（包记录） | ❌ 全删，只剩 `created_at` 和 `history` |
  | `Lib\site-packages\`（221 个第三方包） | ✅ 还在，但**没解释器，一个也跑不了** |

- **修法**：**放弃 test-env**（重建成本远高于修另一个）；
  改为给 `my-agent-env` 补齐依赖：
  ```
  D:\Miniconda3\envs\my-agent-env\python.exe -m pip install mcp openai chromadb fastembed pytest pytest-asyncio
  ```
- **如何避免**：
  1. **本项目统一用 `my-agent-env`**（2026-09-23 起）
  2. **旧文档里"用 test-env"的说明已全部过时** —— 本项目记忆曾写"test-env 依赖全、my-agent-env 不全"，
     实际**恰好相反**。**记忆也会过时，用之前先验证路径是否存在**
  3. 判断 conda 环境是否健康：`conda list -n <env>` 有没有正常输出包列表。
     **只输出表头 = 环境元数据已损坏**

---

## [2026-09-23] PowerShell 的 `>` 重定向写出 UTF-16 文件

- **症状**：用 `git show ... > agent-lite/config.py` 复制源码，
  文件存在、大小也"对"，但 Python 读它报
  `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0`
- **根因**：**PowerShell 的 `>` 重定向默认输出 UTF-16LE**（带 BOM），不是 UTF-8。
  同一个文件：UTF-8 是 663 字节，PowerShell 写出来是 1270 字节
- **修法**：改用 **Git Bash** 的重定向（默认 UTF-8）：
  ```bash
  git -C D:/Python/janyu2cs_projects/agent-stack show add-dockerfiles:agent-lite/config.py > agent-lite/config.py
  ```
  或复制后转换编码
- **如何避免**：
  1. **复制源码文件后，必须验证它能被解释器解析**，不能只查"文件存在 + 大小合理"：
     ```bash
     python -c "import ast,pathlib; ast.parse(pathlib.Path('agent-lite/xxx.py').read_text(encoding='utf-8'))"
     ```
  2. **文件大小异常（约为正常值 2 倍）就是 UTF-16 的信号**
  3. `file <文件名>` 能直接看出来：`UTF-8 text` vs `UTF-16, little-endian text`

---

## [2026-09-23] `pip install mcp` 装成 2.x，代码全崩

- **症状**：服务启动或 `mcp_server.py` 直接运行报
  `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`，
  错误信息提示 "This is mcp 2.x, where FastMCP was renamed to MCPServer"
- **根因**：**装包时没看版本约束**。`requirements.txt` 写的是 `mcp~=1.28.1`，
  但 `pip install mcp` 装成了 2.2.0，而代码用的是 1.x 的 `FastMCP` API
- **修法**：
  ```bash
  D:\Miniconda3\envs\my-agent-env\python.exe -m pip install "mcp~=1.28.1"
  ```
- **如何避免**：**装包要按 `requirements.txt` 的版本约束**，不要裸装包名：
  ```bash
  python -m pip install -r agent-lite/requirements.txt
  ```
  遇到 `ModuleNotFoundError` 先怀疑**版本不对**，不只是"没装"。

---

## [2026-09-23] MCP 子进程用裸 `python` 启动，解析到错误的解释器

- **症状**：服务能启动，但日志报 `No module named 'mcp'`，
  本地 MCP 工具一个都发现不了（"本地 MCP 连接失败：Connection closed"）
- **根因**：`mcp_client.py` 里写死 `"command": "python"`。
  裸 `python` 解析到 **base 环境的 Python**（`D:\Miniconda3\python.exe`），
  而依赖装在 `my-agent-env` 里 —— 子进程用的是另一个解释器
- **修法**：改用 `sys.executable`，保证子进程与当前服务**同一个解释器**：
  ```python
  "command": sys.executable,
  "args": [os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")],
  ```
  同时把 `mcp_server.py` 的路径改成**绝对路径**，避免 CWD 变化导致找不到
- **如何避免**：
  1. **任何"启动子进程跑 Python 脚本"的地方，一律用 `sys.executable`，不要写 `python`**
  2. 多环境机器上，裸 `python` / `python3` 指向哪个解释器**永远是个未知数**

---

## 变更记录

| 日期 | 新增 |
|------|------|
| 2026-09-23 | 初版：从 v1 项目记忆迁移 7 条已知坑 |
| 2026-09-23 | 新增：跨 shell 环境变量不传递导致 key 读取失败 |
| 2026-09-23 | 新增：test-env 环境损坏，统一改用 my-agent-env |
| 2026-09-23 | 新增：PowerShell `>` 重定向写出 UTF-16 文件 |
| 2026-09-23 | 新增：pip 装 mcp 2.x 导致 FastMCP 不可用 |
| 2026-09-23 | 新增：MCP 子进程用裸 python 启动导致解释器错位 |
