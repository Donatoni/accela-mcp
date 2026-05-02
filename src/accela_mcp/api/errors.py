"""Error types and response→exception mapping for the Accela API.

`AccelaAPIError` is the user-visible error surfaced to MCP clients. It always
carries `traceId` when Accela provided one, since support escalations need it.

`RetryableError` is internal — used to drive `tenacity` retries inside the
client. It never leaks to callers.
"""

from __future__ import annotations

from typing import Any

import httpx


class AccelaAPIError(Exception):
    """Non-retryable API error surfaced to MCP clients.

    Carries Accela's structured error envelope plus the request path so the
    operator (and Accela support) can investigate.
    """

    def __init__(
        self,
        *,
        status: int,
        code: str,
        message: str,
        trace_id: str | None = None,
        more: Any = None,
        path: str | None = None,
        method: str | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.trace_id = trace_id
        self.more = more
        self.path = path
        self.method = method
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [f"[{self.status} {self.code}]", self.message]
        if self.method and self.path:
            parts.append(f"({self.method} {self.path})")
        elif self.path:
            parts.append(f"(path: {self.path})")
        if self.trace_id:
            parts.append(f"(traceId: {self.trace_id})")
        return " ".join(parts)

    @classmethod
    def from_response(
        cls,
        response: httpx.Response,
        *,
        path: str | None = None,
        method: str | None = None,
    ) -> AccelaAPIError:
        body: dict[str, Any]
        try:
            parsed = response.json()
            body = parsed if isinstance(parsed, dict) else {}
        except Exception:
            body = {}

        return cls(
            status=response.status_code,
            code=str(body.get("code") or "unknown"),
            message=str(body.get("message") or response.text[:500] or "no message"),
            trace_id=body.get("traceId"),
            more=body.get("more"),
            path=path or str(response.request.url.path),
            method=method or response.request.method,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializable shape for surfacing to the MCP client."""
        return {
            "error": "accela_api_error",
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "trace_id": self.trace_id,
            "method": self.method,
            "path": self.path,
            "more": self.more,
        }


class RetryableError(Exception):
    """Internal — signals that a request should be retried under tenacity.

    Carries the original status and an optional `retry_after_seconds` floor.
    """

    def __init__(self, reason: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.retry_after = retry_after


_EMSE_HINT_TOKENS = ("script", "emse", "rule", "validation failed", "before-event")


def is_likely_emse_error(error: AccelaAPIError) -> bool:
    """Heuristic — true if a 500 looks like agency-side EMSE script failure."""
    if error.status != 500:
        return False
    msg = (error.message or "").lower()
    return any(tok in msg for tok in _EMSE_HINT_TOKENS)


__all__ = [
    "AccelaAPIError",
    "RetryableError",
    "is_likely_emse_error",
]
