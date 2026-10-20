"""Structured logs for App Runner. One JSON object per line."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_RESERVED: set[str] = {
    # Attributes every LogRecord already has. Anything else came from
    # `extra=...` and belongs in the JSON payload.
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, which is what App Runner's log viewer expects.

    Call sites pass identifiers and decisions through `extra`, never tokens,
    raw parameters, or full URLs with credentials.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    # Configure only our logger and stop propagation. Uvicorn's access and error
    # loggers keep their own handlers, so both formats survive side by side.
    logger = logging.getLogger("alexa")
    logger.setLevel(level.upper())
    logger.propagate = False
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
