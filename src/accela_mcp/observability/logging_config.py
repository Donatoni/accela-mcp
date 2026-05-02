"""Structured logging via `structlog`.

All logs go to **stderr** so they don't collide with the MCP stdio transport,
which uses stdout. JSON format is the default; `console` is human-readable
for local development.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from accela_mcp.settings import LogFormat, LogLevel
from accela_mcp.utils.redaction import redact_event

_CONFIGURED = False


def configure_logging(level: LogLevel = "INFO", fmt: LogFormat = "json") -> None:
    """Configure structlog and the stdlib root logger.

    Idempotent — safe to call multiple times. Subsequent calls update level/format.
    """
    global _CONFIGURED

    log_level = getattr(logging, level)
    # Route stdlib logging to stderr too, so anything from httpx etc. obeys the rule.
    handler = logging.StreamHandler(sys.stderr)
    root = logging.getLogger()
    # Remove pre-existing handlers we may have installed on a prior call.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(log_level)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_event,
    ]

    if fmt == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer(sort_keys=True)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True


def get_logger(*args: Any, **kwargs: Any) -> structlog.stdlib.BoundLogger:
    """Get a configured logger. Auto-configures with defaults if not yet done."""
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(*args, **kwargs)
