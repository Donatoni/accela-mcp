"""Shared infrastructure for tool modules.

`ToolContext` is the bag of dependencies every tool can pull from — the
HTTP client, settings, capabilities, the reference-data cache, and the
admin allowlist (if enabled).

`tool_call` wraps tool bodies to translate `AccelaAPIError` into a
serializable shape and to emit one structured log line per call.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, ParamSpec, TypeVar

from accela_mcp.api.client import AccelaClient
from accela_mcp.api.errors import AccelaAPIError, is_likely_emse_error
from accela_mcp.capabilities import LoadedConfig, PaymentsConfig, WritesConfig
from accela_mcp.observability.logging_config import get_logger
from accela_mcp.safety import AuditLog
from accela_mcp.settings import Settings
from accela_mcp.utils.cache import TTLCache
from accela_mcp.utils.redaction import redact_mapping

log = get_logger(__name__)

# Conservative cap on a single tool's `limit` param. Accela's effective
# search max is 100; any tool exposes `limit` clamped to this.
TOOL_LIMIT_MAX = 100

# Absolute ceiling on auto-pagination `max_results`. The default is 1000;
# this ceiling protects against a runaway request that would page through
# tens of thousands of records in one tool call.
TOOL_MAX_RESULTS_CEILING = 5000


@dataclass
class ToolContext:
    settings: Settings
    config: LoadedConfig
    client: AccelaClient
    reference_cache: TTLCache[dict[str, Any]]
    audit_log: AuditLog | None = None

    def tokens_scope_list(self) -> list[str]:
        """Parsed scope list from the active access token."""
        return [s for s in (self.client.tokens.scope or "").split() if s]

    @property
    def writes_config(self) -> WritesConfig:
        return self.config.capabilities.writes

    @property
    def payments_config(self) -> PaymentsConfig:
        return self.config.capabilities.payments


P = ParamSpec("P")
R = TypeVar("R")


def tool_call(
    tool_name: str,
) -> Callable[
    [Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, dict[str, Any] | R]]
]:
    """Decorator: log the call, time it, translate AccelaAPIError into a dict."""

    def decorator(
        fn: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, dict[str, Any] | R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any] | R:
            start = time.monotonic()
            params_for_log = redact_mapping({k: v for k, v in kwargs.items() if v is not None})
            log.info("tool_call_start", tool=tool_name, params=params_for_log)
            try:
                result = await fn(*args, **kwargs)
            except AccelaAPIError as e:
                duration_ms = int((time.monotonic() - start) * 1000)
                payload = e.to_dict()
                if is_likely_emse_error(e):
                    payload["hint"] = (
                        "This appears to be a custom validation rule from your "
                        "Accela agency (EMSE). The agency administrator may need "
                        "to review the script."
                    )
                elif e.status == 401:
                    # 401 here means Accela rejected the access token after the
                    # client already tried a refresh. The user needs a fresh
                    # interactive login.
                    payload["hint"] = (
                        "Accela rejected the access token even after refresh. "
                        "Run accela_login from chat to re-authenticate, then retry."
                    )
                log.warning(
                    "tool_call_error",
                    tool=tool_name,
                    duration_ms=duration_ms,
                    status=e.status,
                    code=e.code,
                    trace_id=e.trace_id,
                )
                return payload
            except ValueError as e:
                # Tool-side validation — emit a structured client-error.
                duration_ms = int((time.monotonic() - start) * 1000)
                log.warning(
                    "tool_call_invalid_input",
                    tool=tool_name,
                    duration_ms=duration_ms,
                    message=str(e),
                )
                return {
                    "error": "invalid_input",
                    "message": str(e),
                }
            else:
                duration_ms = int((time.monotonic() - start) * 1000)
                log.info("tool_call_ok", tool=tool_name, duration_ms=duration_ms)
                return result

        return wrapper

    return decorator


def clamp_limit(limit: int | None, default: int = 25) -> int:
    """Clamp a user-supplied `limit` to a safe range."""
    if limit is None:
        return default
    if not isinstance(limit, int):
        raise ValueError(f"limit must be an integer, got {type(limit).__name__}")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    return min(limit, TOOL_LIMIT_MAX)


def clamp_offset(offset: int | None) -> int:
    if offset is None:
        return 0
    if not isinstance(offset, int):
        raise ValueError(f"offset must be an integer, got {type(offset).__name__}")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    return offset


def clamp_max_results(max_results: int | None, default: int = 1000) -> int:
    """Clamp a user-supplied `max_results` to a safe range."""
    if max_results is None:
        return default
    if not isinstance(max_results, int):
        raise ValueError(f"max_results must be an integer, got {type(max_results).__name__}")
    if max_results < 1:
        raise ValueError("max_results must be >= 1")
    return min(max_results, TOOL_MAX_RESULTS_CEILING)


def first_result(payload: dict[str, Any]) -> Any:
    """Extract the first item from a `result` array, or the result if it's a dict.

    Many Accela endpoints return `{"result": [...]}` even for single-ID lookups;
    callers usually want the inner object.
    """
    result = payload.get("result")
    if isinstance(result, list):
        return result[0] if result else None
    return result


def normalize_yn(value: Any) -> bool | None:
    """Convert Accela's `Y`/`N` string booleans to native Python booleans."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().upper()
        if v == "Y":
            return True
        if v == "N":
            return False
    return None


__all__ = [
    "TOOL_LIMIT_MAX",
    "TOOL_MAX_RESULTS_CEILING",
    "ToolContext",
    "clamp_limit",
    "clamp_max_results",
    "clamp_offset",
    "first_result",
    "normalize_yn",
    "tool_call",
]
