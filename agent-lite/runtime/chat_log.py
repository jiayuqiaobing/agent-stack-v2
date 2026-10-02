"""会话消息本体。SQLite 只负责留下记录，不负责每次切换时重画界面。"""

import os
import sqlite3
import threading
from datetime import datetime, timezone


_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chat.sqlite")
_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    conn = sqlite3.connect(_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sessions ("
        "id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
        "role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    return conn


def append_message(session_id: str, role: str, content: str) -> None:
    text = content or ""
    if not session_id or role not in {"user", "assistant"} or not text.strip():
        return
    now = datetime.now(timezone.utc).isoformat()
    title = text.strip().replace("\n", " ")[:18] if role == "user" else ""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO sessions(id, title, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, "
                "title=CASE WHEN sessions.title='' THEN excluded.title ELSE sessions.title END",
                (session_id, title, now),
            )
            conn.execute(
                "INSERT INTO messages(session_id, role, content, created_at) VALUES(?,?,?,?)",
                (session_id, role, text, now),
            )
            conn.commit()
        finally:
            conn.close()


def load_messages(session_id: str) -> list[dict]:
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        finally:
            conn.close()
    return [{"role": row["role"], "text": row["content"], "at": row["created_at"]} for row in rows]


def list_sessions() -> list[dict]:
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id, title, updated_at FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        finally:
            conn.close()
    return [{"id": row["id"], "title": row["title"], "updated_at": row["updated_at"]} for row in rows]


def delete_session(session_id: str) -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            conn.commit()
        finally:
            conn.close()
