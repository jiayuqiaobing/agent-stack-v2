"""打开一个网页并取出可见文字。只在需要看具体页面时才导入。

使用 Playwright。没安装浏览器时返回错误，不自己解析 HTML。
"""

BROWSER = {
    "type": "function",
    "function": {
        "name": "open_page",
        "description": "用浏览器打开 http 或 https 页面，返回可见文字。适合需要执行页面脚本后才能看到内容的网址。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
    },
}


async def open_page(url: str) -> str:
    target = (url or "").strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        return "错误: 只接受 http 或 https"
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return "错误: 未安装 Playwright。先执行 python -m playwright install chromium"
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(target, timeout=20000, wait_until="domcontentloaded")
            text = await page.inner_text("body")
            await browser.close()
    except Exception as e:
        return f"错误: 页面打不开: {type(e).__name__}"
    body = " ".join((text or "").split())
    if not body:
        return "错误: 页面没有可见文字"
    if len(body) > 4000:
        body = body[:4000] + " ...(已截断)"
    return body
