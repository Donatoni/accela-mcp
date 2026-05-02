"""Safety scaffolding for write tools.

Every tool that mutates Accela state (records, inspections, documents,
workflow tasks, payments) goes through this module. The point is that the
user — not the LLM — is the one who actually authorizes a change.

Three layers, in order:

  1. **`confirm: bool = False` parameter.** Every write tool defaults to a
     dry-run. Without `confirm=True`, the tool returns a `WritePreview`
     describing exactly what would be sent and refuses to call Accela. This
     forces the LLM to surface the preview to the user and get explicit
     approval before re-invoking with `confirm=True`.

  2. **Master kill-switch in `capabilities.yaml`.** `writes.enabled: false`
     refuses every confirmed write at startup time, regardless of which
     `*_write` groups are enabled. Lifting the switch is a deliberate edit.

  3. **Append-only audit log.** Every confirmed write records timestamp,
     tool name, agency, environment, exact request (PII-scrubbed), Accela
     response status, and `traceId` to a JSON-line file. Survives
     `logging.format=console`. Lets operators answer "what wrote this?"
     without trawling streaming logs.

Payments add a fourth gate (`payments.real_money_allowed`) on top — see
`capabilities.PaymentsConfig`.
"""

from __future__ import annotations

import functools
import json
import os
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from accela_mcp.api.errors import AccelaAPIError, is_likely_emse_error
from accela_mcp.observability.logging_config import get_logger
from accela_mcp.utils.redaction import redact_mapping

log = get_logger(__name__)


@dataclass(frozen=True)
class WritePreview:
    """Description of a pending write — what the tool *would* send.

    Returned to the caller (LLM/MCP client) when `confirm=False`. The shape
    is deliberately stable and self-explanatory so an LLM can show a useful
    summary to the human user without further interpretation.
    """

    tool: str
    method: str
    path: str
    summary: str
    body: Any = None
    query_params: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    irreversible: bool = False
    affects_money: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview": True,
            "confirmation_required": True,
            "tool": self.tool,
            "method": self.method,
            "path": self.path,
            "summary": self.summary,
            "body": self.body,
            "query_params": self.query_params,
            "warnings": self.warnings or None,
            "irreversible": self.irreversible,
            "affects_money": self.affects_money,
            "next_step": (
                "Show this preview to the human user. If they approve, "
                f"re-invoke {self.tool!r} with the same arguments and "
                "`confirm=True` to actually execute."
            ),
        }


class WriteSafetyError(RuntimeError):
    """Raised when a write is attempted in a state that policy forbids.

    Surfaced to MCP clients as `{"error": "writes_disabled", ...}` rather
    than crashing the server — the operator may be exploring tools and
    bumping into a misconfigured kill-switch.
    """


class AuditLog:
    """Append-only JSON-line audit log for confirmed writes.

    File is created with mode 0600 on Unix. Writes are line-buffered and
    fsynced — slower than pure buffered I/O, but the file is tiny (one line
    per write) and durability matters more than throughput here.

    Thread-safe via a process-local lock; multi-process safety is out of
    scope (the MCP server is single-process today).
    """

    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self.path.touch()
                if os.name != "nt":
                    os.chmod(self.path, 0o600)

    def record(
        self,
        *,
        tool: str,
        method: str,
        path: str,
        agency: str,
        environment: str,
        params: dict[str, Any] | None,
        body: Any,
        result_status: int | None,
        result_id: str | None = None,
        trace_id: str | None = None,
        error: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Append one entry. Best-effort — if we can't write, log a warning
        and continue (refusing the call would be more disruptive than
        losing one audit line)."""
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "tool": tool,
            "method": method,
            "path": path,
            "agency": agency,
            "environment": environment,
            "params": redact_mapping(params or {}),
            "body": _scrub_body(body),
            "result_status": result_status,
            "result_id": result_id,
            "trace_id": trace_id,
            "error": error,
            "duration_ms": duration_ms,
        }
        line = json.dumps(entry, sort_keys=True, default=str) + "\n"

        if self.path is None:
            # Audit-only-to-stderr mode — still leaves a record in the
            # structured logs even if the operator didn't configure a file.
            log.info("write_audit", **entry)
            return

        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError as e:
                log.warning(
                    "audit_log_write_failed",
                    path=str(self.path),
                    error=str(e),
                    fallback_entry=entry,
                )


def _scrub_body(body: Any) -> Any:
    """Run a write body through `redact_mapping` so PII fields don't land
    verbatim in the audit log. Lists and primitives pass through with their
    nested mappings scrubbed."""
    if isinstance(body, dict):
        return redact_mapping(body)
    if isinstance(body, list):
        return [_scrub_body(item) for item in body]
    return body


P = ParamSpec("P")
R = TypeVar("R")


def write_tool(
    tool_name: str,
    ctx: Any,
    *,
    affects_money: bool = False,
) -> Callable[
    [Callable[P, Coroutine[Any, Any, R]]],
    Callable[P, Coroutine[Any, Any, dict[str, Any] | R]],
]:
    """Decorator companion to `tool_call` for *write* tools.

    Pass the live `ToolContext` at registration time (closure capture). The
    wrapped function must:
      * accept a `confirm: bool` kwarg with a False default — that's the
        signature MCP picks up and exposes to the LLM
      * return either a `WritePreview` (from a dry-run path) or a dict with
        `method`, `path`, `result_status`, optional `result_id` /
        `trace_id` / `request_body` (from a confirmed path)

    The decorator handles:
      * the `writes.enabled` kill-switch — refuses confirmed calls when off
      * the agency-environment allowlist when configured
      * audit-logging every confirmed call (success or error)
      * surfacing `AccelaAPIError`s as the same `{"error": ...}` dict the
        read-tool decorator produces, with the EMSE hint when applicable
      * timing the call

    Validation of inputs (record_id format, required fields, etc.) stays in
    the tool body. The decorator only cares about the safety envelope.
    """

    def decorator(
        fn: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, dict[str, Any] | R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any] | R:
            confirm = bool(kwargs.get("confirm", False))
            params_for_log = redact_mapping({k: v for k, v in kwargs.items() if v is not None})

            log.info(
                "write_tool_call_start",
                tool=tool_name,
                confirm=confirm,
                affects_money=affects_money,
                params=params_for_log,
            )

            writes_cfg = getattr(ctx, "writes_config", None)
            audit = getattr(ctx, "audit_log", None)
            agency = getattr(ctx.client, "agency", "unknown") if ctx else "unknown"
            environment = getattr(ctx.client, "environment", "unknown") if ctx else "unknown"

            if confirm:
                if writes_cfg is not None and not writes_cfg.enabled:
                    log.warning(
                        "write_refused_kill_switch_off",
                        tool=tool_name,
                        agency=agency,
                        environment=environment,
                    )
                    return {
                        "error": "writes_disabled",
                        "message": (
                            "Confirmed write refused: capabilities.yaml has "
                            "`writes.enabled: false`. Set it to true (and "
                            "ideally restrict `writes.agency_environment_allowed`) "
                            "before write tools can mutate Accela data."
                        ),
                        "tool": tool_name,
                    }

                if (
                    writes_cfg is not None
                    and writes_cfg.agency_environment_allowed
                    and environment.upper()
                    not in {e.upper() for e in writes_cfg.agency_environment_allowed}
                ):
                    log.warning(
                        "write_refused_environment_not_allowed",
                        tool=tool_name,
                        agency=agency,
                        environment=environment,
                        allowed=writes_cfg.agency_environment_allowed,
                    )
                    return {
                        "error": "writes_disabled",
                        "message": (
                            f"Confirmed write refused: environment {environment!r} "
                            "is not in `writes.agency_environment_allowed`. Update "
                            "capabilities.yaml to permit this environment, or run "
                            "the write against an allowed one."
                        ),
                        "tool": tool_name,
                        "environment": environment,
                        "allowed": writes_cfg.agency_environment_allowed,
                    }

            start = time.monotonic()
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
                log.warning(
                    "write_tool_call_error",
                    tool=tool_name,
                    confirm=confirm,
                    duration_ms=duration_ms,
                    status=e.status,
                    code=e.code,
                    trace_id=e.trace_id,
                )
                if confirm and audit is not None:
                    audit.record(
                        tool=tool_name,
                        method=getattr(e, "method", "?") or "?",
                        path=getattr(e, "path", "?") or "?",
                        agency=agency,
                        environment=environment,
                        params=params_for_log,
                        body=None,
                        result_status=e.status,
                        trace_id=e.trace_id,
                        error={"code": e.code, "message": e.message},
                        duration_ms=duration_ms,
                    )
                return payload
            except ValueError as e:
                duration_ms = int((time.monotonic() - start) * 1000)
                log.warning(
                    "write_tool_call_invalid_input",
                    tool=tool_name,
                    duration_ms=duration_ms,
                    message=str(e),
                )
                return {
                    "error": "invalid_input",
                    "message": str(e),
                }

            duration_ms = int((time.monotonic() - start) * 1000)

            # Dry-run path: tool returned a preview; do not audit.
            if isinstance(result, WritePreview):
                log.info(
                    "write_tool_call_preview",
                    tool=tool_name,
                    duration_ms=duration_ms,
                )
                preview_dict = result.to_dict()
                if affects_money:
                    warnings = list(preview_dict.get("warnings") or [])
                    warnings.append("This tool initiates a financial transaction.")
                    preview_dict["warnings"] = warnings
                    preview_dict["affects_money"] = True
                return preview_dict

            # Confirmed path: audit on success, then return verbatim.
            if confirm and audit is not None:
                audit.record(
                    tool=tool_name,
                    method=_extract(result, "method") or "?",
                    path=_extract(result, "path") or "?",
                    agency=agency,
                    environment=environment,
                    params=params_for_log,
                    body=_extract(result, "request_body"),
                    result_status=_extract(result, "result_status"),
                    result_id=_extract(result, "result_id"),
                    trace_id=_extract(result, "trace_id"),
                    duration_ms=duration_ms,
                )
            log.info(
                "write_tool_call_ok",
                tool=tool_name,
                confirm=confirm,
                duration_ms=duration_ms,
            )
            return result

        return wrapper

    return decorator


def _extract(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return None


__all__ = [
    "AuditLog",
    "WritePreview",
    "WriteSafetyError",
    "write_tool",
]
