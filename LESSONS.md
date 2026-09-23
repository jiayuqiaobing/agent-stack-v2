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

## 变更记录

| 日期 | 新增 |
|------|------|
| 2026-09-23 | 初版：从 v1 项目记忆迁移 7 条已知坑 |
