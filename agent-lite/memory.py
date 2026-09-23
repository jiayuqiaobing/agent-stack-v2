"""
test08/memory.py

HybridMemory类的定义，agent的记忆系统
"""


from datetime import datetime
from rag_store import RAGStore
import logging


#  初始化日志实体
logger = logging.getLogger(__name__)


class HybridMemory:
    """
    HybridMemory
    ├── 短期记忆 → 数组存、按顺序读
    └── 长期记忆 → ChromaDB 存、语义检索读  ← RAG 就在这
    """
    def __init__(self,system_prompt,client,session_id="default",summary_trigger=15,keep_recent=6):
        """
        system_prompt:系统提示词，在上下文最上层，100%缓存命中，减少token开销
        client: 同步 OpenAI 客户端（仅 search_memory 等非热路径使用）
        session_id:会话标识，用于 RAG 长期记忆按会话隔离（防串味）
        summary_trigger:会话历史压缩阈值，short_term大于等于summary_trigger，在下一次agent——loop开始阶段压缩
        keep_recent:压缩时保留在short_term中的会话数，保留最近完整记忆
        """
        self.client = client
        self.system_prompt = system_prompt
        self.session_id = session_id
        self.summary_trigger = summary_trigger
        self.keep_recent = keep_recent

        self.short_term:list[dict] = []
        self.long_term:list[dict] = []

        try:
            self.rag = RAGStore(session_id=session_id)

            #  启动时从 ChromaDB 恢复本 session 的历史摘要
            docs = self.rag.restore()
            if docs:
                for doc in docs:
                    self.long_term.append({
                        "summary":  doc,
                        "timestamp":"(历史记录)"
                    })
                logger.info("从 ChromaDB 恢复了 %d 条历史摘要（session=%s）",len(docs), session_id)
            else:
                logger.info("ChromaDB 中无本 session 的历史数据，从零开始")
        except Exception:
            logger.warning("ChromaDB 恢复失败，降级为空记忆继续运行。", exc_info = True)
            self.rag = None

    def add(self,role:str,content:str,**extra) -> None:
        """
        添加消息（非工具调用版）
        **extra:对字典解包，字典类型
        msg:构建出的short_term结构的变量
        """
        msg = {"role":role,"content":content}
        msg.update(extra)
        self.short_term.append(msg)
        logger.debug("短期记忆 +1：role=%s, content_len=%d", role, len(content))

    def add_assistant_with_tool_calls(self,msg) -> None:
        """
        添加消息（工具调用版）
        msg:模型返回的message格式
        注: short_term 的一条信息可以有一个队列的工具信息
        """
        self.short_term.append({
            "role":"assistant",
            "content":msg.content or "",
            "tool_calls":[
                {
                    "id":tc.id,
                    "type":"function",
                    "function":{
                        "name":tc.function.name,
                        "arguments":tc.function.arguments
                    }
                }
                for tc in msg.tool_calls
            ]
        })
        logger.debug("短期记忆 +1（工具调用）：%d 个 tool_call", len(msg.tool_calls))

    async def build_context(self) -> list:
        """
        构建上下文
        上下文结构：system_prompt（100% KV-Cache命中） + RAG语义检索的长期记忆（同一问题可能缓存命中） + 较早短期记忆（过了摘要窗口，暂时不变） + 最近短期记忆（频繁变化，但模型注意力最强） + 当前用户问题（最后，最敏感）
        KV-Cache 前缀命中（不变放前面省钱） + Lost in the Middle（重要的放最后）
        """
        context=[{"role":"system","content":self.system_prompt}]

        #  拼接用户当前问题
        user_query = ""
        for msg in reversed(self.short_term):  #  反向搜索最近的用户问题
            if msg["role"] == "user":
                user_query = msg.get("content","")
                break

        #  语义检索最相关的长期记忆（top-5）
        if user_query and self.rag is not None:
            try:
                relevant = await self.rag.search(user_query,k=5)
            except Exception:
                logger.warning("RAG 检索失败，跳过",exc_info=True)
                relevant = []
            if relevant:
                logger.debug("RAG 检索命中 %d 条结果，查询：%s", len(relevant), user_query[:50])
                context.append({
                    "role": "system",
                    "content":"以下是历史相关记忆：\n" + "\n".join(
                        f"- {m}" for m in relevant
                    )
                })

        #  短期记忆原样追加
        context.extend(self.short_term)
        logger.debug("上下文构建完成，共 %d 条消息", len(context))
        return context

    async def maybe_summarize(self) -> str:
        """
        当短期记忆数超过 summary_trigger 时，触发压缩
        把最早的short_term（保留 keep_recent 条） 用模型总结成一段文字，转移到长期记忆，并且索引入库（RAG）
        返回值：摘要文本（如果未触发返回空字符串）
        """
        if len(self.short_term) <= self.summary_trigger:
            return ""

        #  short_term中需要摘要的切片
        to_summarize = self.short_term[:len(self.short_term)-self.keep_recent]

        if len(to_summarize) <= 2:
            return ""

        logger.info("触发记忆压缩：short_term %d 条 → 保留 %d 条，待总结 %d 条",
                    len(self.short_term), self.keep_recent, len(to_summarize))

        #  用模型做摘要（异步，不阻塞事件循环）
        summary = await self._generate_summary(to_summarize)

        #  移动到长期记忆
        self.long_term.append({
            "summary":  summary,
            "timestamp":datetime.now().strftime("%Y-%m-%d %H:%M")
        })

        #  移动到chroma db（异步 Embedding）
        if self.rag is not None:
            try:
                await self.rag.add(summary)
            except Exception:
                logger.warning("RAG 写入失败，摘要仅保存到 long_term",exc_info=True)


        #  短期记忆只保存最近的keep_recent条
        self.short_term = self.short_term[-self.keep_recent:]

        #  清理孤儿 tool 消息（父 assistant 已被截掉）
        orphan_count = 0
        while self.short_term and self.short_term[0].get("role") == "tool":
            self.short_term.pop(0)
            orphan_count += 1
        if orphan_count > 0:
            logger.debug("清理孤儿 tool 消息：%d 条", orphan_count)

        return summary

    async def _generate_summary(self,messages:list[dict]) -> str:
        """
        使用模型压缩short_term,返回压缩的记忆文本或者失败提示
        message:需要压缩的短期记忆部分
        """
        from config import aclient, MODEL_NAME

        #  提取信息
        text_parts = []
        for m in messages:
            role = m["role"]
            content = m.get("content","")
            if isinstance(content,str) and content.strip():
                text_parts.append(f"[{role}]:{content}")

        conversation_text = "\n".join(text_parts)

        try:
            response = await aclient.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role":    "system",
                     "content": "你是一个摘要助手，请用简短的中文总结以下对话的关键信息，包括'讨论了什么话题、得出了什么结论、用户透露了什么重要信息（如名字、偏好等）。控制在200字以内。'"},
                    {"role":   "user",
                     "content": f"请总结一下对话: \n\n{conversation_text}"}
                ],
                max_tokens=500,
                temperature=0
            )
            summary = response.choices[0].message.content or "(摘要生成失败)"
            logger.info("摘要生成完成，长度：%d 字符", len(summary))
            return summary
        except Exception as e:
            logger.error("摘要生成失败：%s", e)
            return f"(摘要生成出错：{e})"

    def search_memory(self,keyword:str) -> str:
        """
        记忆检索：简单的关键词匹配检索
        同时搜索长期记忆（摘要）和短期记忆（原文），返回匹配到的最近5条结果
        keyword:
        """
        results = []

        # 搜长期记忆
        for i, entry in enumerate(self.long_term):
            if keyword.lower() in entry["summary"].lower():
                results.append(f"[长期 #{i + 1}] {entry['summary'][:200]}{'...' if len(entry['summary']) > 200 else ''}")

        # 搜短期记忆
        for msg in self.short_term:
            content = msg.get("content", "")
            if isinstance(content, str) and keyword.lower() in content.lower():
                snippet = content[:200] + ("..." if len(content) > 200 else "")
                results.append(f"[短期 {msg['role']}] {snippet}")

        if not results:
            logger.debug("关键词搜索无结果：%s", keyword[:50])
            return "未找到相关内容"

        return "\n---\n".join(results[-5:])

    def clear(self) -> None:
        """放弃当前对话,删除长期记忆（已经保存到Chroma），作用是清空上下文"""
        logger.info("记忆清空：short_term=%d 条, long_term=%d 条",
                    len(self.short_term), len(self.long_term))
        self.short_term.clear()
        self.long_term.clear()

    def stats(self) -> dict:
        """记忆展示"""
        if self.rag is not None:
            rag_count = self.rag.count()
        else:
            rag_count = -1
        return {
            "short_term_count": len(self.short_term),
            "long_term_count": len(self.long_term),
            "rag_vector_count": rag_count,
            "summary_trigger": self.summary_trigger,
            "keep_recent": self.keep_recent,
            "short_term_preview": [m.get("role", "") + ": " + str(m.get("content", ""))[:50]
                                   for m in self.short_term[-3:]],
            "long_term_preview": [e["summary"][:80] for e in self.long_term],
        }
