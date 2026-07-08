"""Strukturiertes Logging (JSON-kompatibel, ME4-Standard)."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.config import settings


class JsonFormatter(logging.Formatter):
    """JSON-Formatter für Production (ELK / Loki kompatibel)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "service": settings.service_id,
        }
        # strukturierte Extras
        for k, v in record.__dict__.items():
            if k in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName", "taskName",
            ):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = str(v)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """Initialisiert das Root-Logging."""
    # Windows: UTF-8 für StreamHandler
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(settings.log_level)
    # ASCII-Formatter (kein Unicode-Problem auf Windows)
    console.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(console)

    try:
        fh = logging.FileHandler(settings.log_file, encoding="utf-8")
        fh.setLevel(settings.log_level)
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
    except OSError as e:
        root.warning("Log-Datei nicht schreibbar: %s", e)

    # Quiet noisy libs
    for noisy in ("urllib3", "httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Gibt einen Modul-Logger zurück."""
    return logging.getLogger(name)
