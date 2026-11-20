"""Structured JSON logging with an automatically attached correlation ID.

Log field names are snake_case because they are a cross-service query
contract. The correlation ID travels in a context variable so call sites do
not have to remember it.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from orchestrator import SERVICE_NAME

LOG_FILE_NAME = "orchestrator.log"
# Ten files of 10 MB keeps several days of indexing and conversation history
# without letting the log grow without bound.
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 9
ACCESS_RECORD_ARGUMENT_COUNT = 5
HTTP_ERROR_FLOOR = 400

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
session_id_var: ContextVar[str] = ContextVar("session_id", default="-")

# Attributes present on every LogRecord. Anything else was passed via `extra`
# and belongs in the structured payload.
_STANDARD_RECORD_ATTRIBUTES = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


class JsonLogFormatter(logging.Formatter):
    """Render each record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": SERVICE_NAME,
            "environment": os.environ.get("LOCAL_COWORK_ENVIRONMENT", "local"),
            "logger": record.name,
            "correlation_id": correlation_id_var.get(),
            "session_id": session_id_var.get(),
        }
        for name, field_value in record.__dict__.items():
            if name not in _STANDARD_RECORD_ATTRIBUTES:
                payload[name] = field_value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
            payload["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RoutinePollingFilter(logging.Filter):
    """Drops access-log lines for successful GET requests.

    The interface polls health, indexing status and the index map every few
    seconds. Logging each poll buries the events that explain a problem.
    Writes (POST, PUT, PATCH, DELETE) and any failed request are kept.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or not isinstance(record.args, tuple):
            return True
        # Uvicorn's access record args: client, method, path, version, status.
        if len(record.args) < ACCESS_RECORD_ARGUMENT_COUNT:
            return True
        method, status_code = record.args[1], record.args[4]
        is_successful = isinstance(status_code, int) and status_code < HTTP_ERROR_FLOOR
        return not (method == "GET" and is_successful)


def configure_logging(log_directory: Path | None = None) -> Path | None:
    """Install the JSON formatter on the root logger. Safe to call twice.

    Args:
        log_directory: When given, logs are also written to a rotating
            `orchestrator.log` there, so they survive the console closing.

    Returns:
        The log file path, or None when logging to the console only.
    """
    level_name = os.environ.get("LOCAL_COWORK_LOG_LEVEL", "INFO").upper()
    formatter = JsonLogFormatter()
    polling_filter = RoutinePollingFilter()
    console_handler = logging.StreamHandler(sys.stderr)
    handlers: list[logging.Handler] = [console_handler]
    log_file: Path | None = None
    if log_directory is not None:
        log_directory.mkdir(parents=True, exist_ok=True)
        log_file = log_directory / LOG_FILE_NAME
        handlers.append(
            RotatingFileHandler(
                log_file,
                maxBytes=LOG_FILE_MAX_BYTES,
                backupCount=LOG_FILE_BACKUP_COUNT,
                encoding="utf-8",
            )
        )
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(polling_filter)
    root_logger = logging.getLogger()
    root_logger.handlers = handlers
    root_logger.setLevel(level_name)
    # One line per HTTP call to the model service drowns everything else.
    # The gateway and indexer log their own outcomes with timings.
    for noisy_logger in ("httpx", "httpx2"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    return log_file
