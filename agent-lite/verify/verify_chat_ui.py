"""verify_chat_ui.py — 聊天页修复的独立验证（不碰 tests/，不调 LLM）

检查：
- ChatRequest 可以多带 model，不带时仍合法
- 页面把 model 放进请求体，且有模型选择
- 页面用单独文本节点写回复，不用父节点 textContent 追加（该写法会在插入 token 子节点时清掉正文）
- 页面识别 usage 事件
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import ChatRequest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "static", "index.html")


def main() -> int:
    ok = True

    bare = ChatRequest(message="hi")
    if bare.model is not None:
        print(f"[FAIL] 不传 model 时应为 None，实际 {bare.model!r}")
        ok = False
    else:
        print("[OK] 不传 model 仍可构造")

    chosen = ChatRequest(
        message="hi",
        model="cheapai/grok-4.6",
        api_key="sk-test",
        base_url="https://example.com/v1",
    )
    if chosen.model != "cheapai/grok-4.6" or chosen.api_key != "sk-test":
        print(f"[FAIL] 渠道字段未保留：{chosen}")
        ok = False
    elif chosen.base_url != "https://example.com/v1":
        print(f"[FAIL] base_url 未保留：{chosen.base_url!r}")
        ok = False
    else:
        print("[OK] model、api_key、base_url 可传入")

    html = open(HTML, encoding="utf-8").read()
    checks = [
        ("model", "请求体没有 model"),
        ('type === "usage"', "没有 usage 事件处理"),
        ("replyText", "回复没有单独文本节点"),
        ("model-picker", "没有模型选择"),
        ("base_url", "请求体没有接口地址"),
        ("复制", "没有复制按钮"),
        ("复制计划摘要", "没有计划摘要复制"),
        ("!view.replyText.querySelector(\".brief\")", "没有保护计划卡片免于空回复误判"),
        ("setTimeout(() => copyBtn.textContent", "复制按钮没有复位"),
        ("controller.abort()", "停止时没有中止当前面板自己的请求"),
        ("panels.get", "切换时没有保留原来的会话面板"),
        ("dataset.rawReply", "计划结构没有保存原始数据"),
        ("home.requestId !== requestId", "流式事件没有绑定发出它的那一个面板"),
        ("session_id: requestSessionId", "请求体没有冻结创建请求时的会话 ID"),
        ("function persist()", "计划选择没有实时持久化"),
        ("persist();", "计划选择变更没有触发快照"),
        ("/messages", "刷新后没有从会话记录取回消息"),
    ]
    for needle, label in checks:
        if needle not in html:
            print(f"[FAIL] {label}")
            ok = False
        else:
            print(f"[OK] {label.replace('没有', '已有').replace('不', '已')}")

    if "assistantDiv.textContent +=" in html or ".textContent +=" in html:
        print("[FAIL] 仍在用 textContent += 写回复")
        ok = False
    else:
        print("[OK] 未用 textContent += 写回复")

    if 'activeRequest.row && activeRequest.row.isConnected' in html:
        print("[FAIL] 切换会话仍会删除未完成消息")
        ok = False
    start = html.find("function openSession")
    end = html.find("function restorePanel")
    body = html[start:end]
    if "abort(" in body or "innerHTML" in body:
        print("[FAIL] 切换会话仍会中断请求或清空页面")
        ok = False
    else:
        print("[OK] 切换会话不中断、不清空")

    if not ok:
        print("[FAIL] verify_chat_ui")
        return 1
    print("[OK] verify_chat_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
