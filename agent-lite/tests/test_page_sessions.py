import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from runtime.brief import fallback_brief


class _State:
    def __init__(self):
        self.sessions = []
        self.live = {}
        self.lock = threading.Lock()


def _start(state):
    html = open("static/index.html", encoding="utf-8").read()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _json(self, payload):
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path.startswith("/sessions/") and self.path.endswith("/messages"):
                self._json({"messages": []})
                return
            if self.path.startswith("/sessions"):
                with state.lock:
                    rows = list(state.sessions)
                self._json({"sessions": rows, "count": len(rows)})
                return
            raw = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            sid = body.get("session_id") or "missing"
            message = body.get("message") or ""
            with state.lock:
                state.sessions.append({"id": sid, "title": message[:18], "updated_at": ""})
                state.live[sid] = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self._write({"type": "session", "session_id": sid})
            try:
                if "科幻" in message:
                    self._write({"type": "delta", "content": fallback_brief(message)})
                    self._write({"type": "done", "reply": "done"})
                    return
                for _ in range(25):
                    self._write({"type": "delta", "content": message})
                    self.wfile.flush()
                    threading.Event().wait(0.15)
                self._write({"type": "done", "reply": message})
            except Exception:
                with state.lock:
                    state.live[sid] = False

        def _write(self, payload):
            line = json.dumps(payload, ensure_ascii=False)
            self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _open(page, port):
    page.add_init_script(
        """localStorage.setItem('channels', JSON.stringify([{id:'c1', model:'m', api_key:'k', base_url:'http://127.0.0.1/v1'}]));
           localStorage.setItem('active_channel', 'c1');"""
    )
    page.goto(f"http://127.0.0.1:{port}/")


def test_switching_does_not_abort_the_hidden_reply():
    state = _State()
    server = _start(state)
    port = server.server_address[1]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(10000)
            _open(page, port)
            page.fill("#input", "第一段仍在生成")
            page.click("#send")
            page.locator(".reply-text", has_text="第一段仍在生成").first.wait_for()
            page.click("#new-chat")
            assert page.locator(".reply-text", has_text="第一段仍在生成").count() == 1
            page.locator("#session-list").get_by_text("第一段仍在生成").click()
            page.locator(".thread.active .reply-text", has_text="第一段仍在生成").wait_for()
            with state.lock:
                assert any(state.live.values())
                assert False not in state.live.values()
            browser.close()
    finally:
        server.shutdown()


def test_stop_aborts_only_the_visible_panel():
    state = _State()
    server = _start(state)
    port = server.server_address[1]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(10000)
            _open(page, port)
            page.fill("#input", "第一段仍在生成")
            page.click("#send")
            page.locator(".reply-text", has_text="第一段仍在生成").first.wait_for()
            page.click("#new-chat")
            page.fill("#input", "第二段仍在生成")
            page.click("#send")
            page.locator(".reply-text", has_text="第二段仍在生成").first.wait_for()
            page.click("#send")
            page.locator(".thread.active", has_text="已停止").wait_for()
            page.wait_for_timeout(400)
            with state.lock:
                hidden = [sid for sid, title in ((row["id"], row["title"]) for row in state.sessions) if title.startswith("第一段")]
                visible = [sid for sid, title in ((row["id"], row["title"]) for row in state.sessions) if title.startswith("第二段")]
                assert hidden and visible
                assert state.live[hidden[0]] is True
                assert state.live[visible[0]] is False
            browser.close()
    finally:
        server.shutdown()


def test_plan_choice_survives_reload():
    state = _State()
    server = _start(state)
    port = server.server_address[1]
    brief = json.loads(fallback_brief("怎么写一本科幻小说")[len("BRIEF_FORM"):])
    alternate = brief["visible_decisions"][0]["options"][1]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(10000)
            _open(page, port)
            page.fill("#input", "怎么写一本科幻小说")
            page.click("#send")
            page.locator(".brief-opt").nth(1).click()
            page.reload()
            selected = page.locator(".brief-opt.on")
            selected.wait_for()
            assert alternate in selected.inner_text()
            browser.close()
    finally:
        server.shutdown()


def test_visual_shell_has_top_tabs_persistent_rail_and_hover_feedback():
    state = _State()
    server = _start(state)
    port = server.server_address[1]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _open(page, port)
            page.locator("#session-tabs").wait_for()
            assert page.locator("#fold").evaluate("el => el.closest('#sidebar') !== null")

            sidebar = page.locator("#sidebar")
            fold = page.locator("#fold")
            fold_box = fold.bounding_box()
            sidebar_box = sidebar.bounding_box()
            assert fold_box["x"] >= sidebar_box["x"]
            assert fold_box["x"] + fold_box["width"] <= sidebar_box["x"] + sidebar_box["width"]

            page.click("#fold")
            page.wait_for_function("document.body.classList.contains('collapsed')")
            rail_width = sidebar.evaluate("el => el.getBoundingClientRect().width")
            assert 52 <= rail_width <= 80
            fold_box = fold.bounding_box()
            sidebar_box = sidebar.bounding_box()
            assert fold_box["x"] + fold_box["width"] <= sidebar_box["x"] + sidebar_box["width"]

            icon = page.locator("#new-chat").evaluate(
                "el => getComputedStyle(el, '::before').backgroundImage"
            )
            assert "data:image/svg+xml" in icon
            before = page.locator("#new-chat").evaluate("el => getComputedStyle(el).boxShadow")
            page.locator("#new-chat").hover()
            after = page.locator("#new-chat").evaluate("el => getComputedStyle(el).boxShadow")
            assert before != after

            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator("body").evaluate("el => el.scrollWidth <= window.innerWidth")
            browser.close()
    finally:
        server.shutdown()
