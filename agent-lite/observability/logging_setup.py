"""应用日志：按天一个文件，每行带上当前会话。"""

import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from observability import trace


class SessionFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.session_id = trace.get_session_id() or "-"
        record.trace_id = trace.get_trace_id() or "-"
        record.span_id = trace.get_current_span_id() or "-"
        return super().format(record)


def setup_logging(log_dir: str) -> None:
    os.makedirs(log_dir, exist_ok=True)
    fmt = SessionFormatter(
        "%(asctime)s [%(levelname)s] %(name)s trace=%(trace_id)s span=%(span_id)s session=%(session_id)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    file_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "agent-lite.log"),
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(fmt)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)
    root.addHandler(stream)
    root.addHandler(file_handler)
    logging.getLogger("mcp.client.sse").setLevel(logging.WARNING)
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
