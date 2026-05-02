"""Async HTTP client for the Accela Construct API.

Behavior:
  * Attaches required headers on every call.
  * Proactive token refresh before sending; reactive refresh on 401 with
    exactly one retry per request.
  * Retries 429/5xx/transient network errors with jittered exponential
    backoff via `tenacity`.
  * Logs every call structured-style with status, duration, attempt, and
    rate-limit headers.
  * Returns parsed JSON dicts on success and raises `AccelaAPIError` on
    permanent failure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
    wait_fixed,
)
from tenacity.wait import wait_base

from accela_mcp.api.errors import AccelaAPIError, RetryableError
from accela_mcp.auth.refresher import refresh_if_needed
from accela_mcp.auth.token_store import Tokens, TokenStore
from accela_mcp.observability.logging_config import get_logger
from accela_mcp.settings import Settings

log = get_logger(__name__)

# Connection / timeout tuning — Accela's published server timeout is 225s; we
# leave a buffer so the client times out *after* the server is sure to have
# given up, avoiding ambiguous half-states.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=240.0, write=30.0, pool=10.0)

# Headers we treat as rate-limit signals worth surfacing in logs.
_RATE_LIMIT_HEADER_PREFIXES = (
    "ratelimit-",
    "x-ratelimit-",
    "x-accela-ratelimit-",
    "x-rate-",
    "x-accela-rate-",
)


@dataclass
class RetryConfig:
    """Backoff / retry knobs surfaced to the YAML config."""

    max_attempts: int = 4  # initial + 3 retries
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    # When True (tests), use a fixed near-zero wait so the suite finishes fast.
    fast_for_tests: bool = False

    def make_wait(self) -> wait_base:
        if self.fast_for_tests:
            return wait_fixed(0)
        return wait_exponential_jitter(
            initial=self.base_backoff_seconds, max=self.max_backoff_seconds
        )


@dataclass
class _CallOutcome:
    """Internal struct returned from `_one_attempt` describing what happened."""

    response: httpx.Response | None = None
    json: dict[str, Any] | None = None
    rate_limit_headers: dict[str, str] = field(default_factory=dict)


class AccelaClient:
    """Single-tenant Accela HTTP client (one agency, one environment).

    Construct via `AccelaClient.create(...)` so we can run the proactive token
    refresh + introspection at startup; the bare constructor is fine when the
    caller already has fresh tokens (e.g., tests).
    """

    def __init__(
        self,
        *,
        settings: Settings,
        tokens: Tokens,
        token_store: TokenStore,
        agency: str,
        environment: str,
        retry: RetryConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.tokens = tokens
        self.token_store = token_store
        self.agency = agency
        self.environment = environment
        self.retry = retry or RetryConfig()
        self._client = http_client or httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=_DEFAULT_TIMEOUT,
            http2=True,
        )
        self._owns_http = http_client is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._client.aclose()

    async def __aenter__(self) -> AccelaClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ headers

    def _headers(self, *, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        # Accela legacy /v4 endpoints take the raw token without the
        # `Bearer ` prefix.
        h = {
            "Authorization": self.tokens.access_token,
            "x-accela-appid": self.settings.app_id,
            "x-accela-environment": self.environment,
            "x-accela-agency": self.agency,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    # ------------------------------------------------------------------ verbs

    async def get(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self.request("POST", path, **kw)

    async def put(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self.request("PUT", path, **kw)

    async def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self.request("DELETE", path, **kw)

    # ------------------------------------------------------------------ core

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Issue an HTTP request, applying retries and refresh-on-401."""

        # Drop None-valued params so callers can pass optional filters cleanly.
        clean_params: dict[str, Any] | None = (
            {k: v for k, v in params.items() if v is not None} if params else None
        )

        # Proactive refresh — does nothing if the token isn't expiring soon.
        self.tokens = await refresh_if_needed(self.tokens, self.settings, self.token_store)

        # State carried across the retry loop:
        #   tried_refresh_once — a 401 retry is only attempted once per
        #     logical request.
        #   last_status — the most recent retried HTTP status, used to
        #     synthesize a structured error when retries are exhausted.
        state: dict[str, Any] = {"tried_refresh_once": False, "last_status": None}

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(RetryableError),
                stop=stop_after_attempt(self.retry.max_attempts),
                wait=self.retry.make_wait(),
                reraise=True,
            ):
                with attempt:
                    return await self._one_attempt(
                        method=method,
                        path=path,
                        params=clean_params,
                        json=json,
                        extra_headers=extra_headers,
                        attempt_no=attempt.retry_state.attempt_number,
                        state=state,
                    )
        except RetryError as e:
            # `reraise=True` should preserve the underlying error, but guard.
            if e.last_attempt and e.last_attempt.failed:
                raise e.last_attempt.exception() from e  # type: ignore[misc]
            raise
        except RetryableError as e:
            # Retries exhausted on a transient status — surface as a
            # structured AccelaAPIError so callers see status + traceId
            # rather than an opaque internal error.
            status = state.get("last_status") or e.status or 503
            raise AccelaAPIError(
                status=status,
                code="retry_exhausted",
                message=(f"Retries exhausted after {self.retry.max_attempts} attempts: {e.reason}"),
                method=method,
                path=path,
            ) from e

        # Unreachable — retry loop returns or raises.
        raise RuntimeError("retry loop exited unexpectedly")  # pragma: no cover

    async def _one_attempt(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        json: Any,
        extra_headers: Mapping[str, str] | None,
        attempt_no: int,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                path,
                headers=self._headers(extra=extra_headers),
                params=params,
                json=json,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            log.warning(
                "accela_api_transport_error",
                method=method,
                path=path,
                agency=self.agency,
                environment=self.environment,
                attempt=attempt_no,
                error=str(e),
            )
            raise RetryableError(f"transport error: {e}") from e

        rate_limit_hdrs = _extract_rate_limit_headers(response.headers)
        state["last_status"] = response.status_code

        log.info(
            "accela_api_call",
            method=method,
            path=path,
            agency=self.agency,
            environment=self.environment,
            status=response.status_code,
            attempt=attempt_no,
            duration_ms=int(response.elapsed.total_seconds() * 1000),
            rate_limit=rate_limit_hdrs or None,
        )

        # 401 — refresh once, then retry; if it 401s again surface as auth error.
        if response.status_code == 401:
            if not state["tried_refresh_once"]:
                state["tried_refresh_once"] = True
                self.tokens = await refresh_if_needed(
                    self.tokens, self.settings, self.token_store, force=True
                )
                raise RetryableError("token refreshed; retrying after 401")
            raise AccelaAPIError.from_response(response, path=path, method=method)

        # 429 — retry with backoff floor on Retry-After if present.
        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            raise RetryableError("rate limited", status=429, retry_after=retry_after)

        # 5xx — retry transient. Don't retry 501.
        if 500 <= response.status_code < 600 and response.status_code != 501:
            raise RetryableError(f"server {response.status_code}", status=response.status_code)

        if response.status_code >= 400:
            err = AccelaAPIError.from_response(response, path=path, method=method)
            log.warning(
                "accela_api_error",
                status=err.status,
                code=err.code,
                message=err.message,
                trace_id=err.trace_id,
                method=method,
                path=path,
                agency=self.agency,
                environment=self.environment,
                attempt=attempt_no,
            )
            raise err

        # 2xx — return parsed body. Some endpoints (e.g., binary download)
        # callers route via `request_raw` instead; this path assumes JSON.
        try:
            return response.json()
        except ValueError as e:
            log.error(
                "accela_api_invalid_json",
                method=method,
                path=path,
                status=response.status_code,
                preview=response.text[:200],
            )
            raise AccelaAPIError(
                status=response.status_code,
                code="invalid_json",
                message=f"Accela returned non-JSON on a JSON endpoint: {e}",
                path=path,
                method=method,
            ) from e

    async def request_raw(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Like `request` but returns the raw httpx.Response.

        Use for binary downloads (documents/thumbnails). The retry/refresh
        loop runs the same as for JSON requests.
        """
        clean_params: dict[str, Any] | None = (
            {k: v for k, v in params.items() if v is not None} if params else None
        )

        self.tokens = await refresh_if_needed(self.tokens, self.settings, self.token_store)
        state: dict[str, Any] = {"tried_refresh_once": False, "last_status": None}

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(RetryableError),
                stop=stop_after_attempt(self.retry.max_attempts),
                wait=self.retry.make_wait(),
                reraise=True,
            ):
                with attempt:
                    return await self._one_attempt_raw(
                        method=method,
                        path=path,
                        params=clean_params,
                        extra_headers=extra_headers,
                        attempt_no=attempt.retry_state.attempt_number,
                        state=state,
                    )
        except RetryableError as e:
            status = state.get("last_status") or e.status or 503
            raise AccelaAPIError(
                status=status,
                code="retry_exhausted",
                message=(f"Retries exhausted after {self.retry.max_attempts} attempts: {e.reason}"),
                method=method,
                path=path,
            ) from e

        raise RuntimeError("retry loop exited unexpectedly")  # pragma: no cover

    async def _one_attempt_raw(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        extra_headers: Mapping[str, str] | None,
        attempt_no: int,
        state: dict[str, Any],
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                path,
                headers=self._headers(extra=extra_headers),
                params=params,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise RetryableError(f"transport error: {e}") from e

        state["last_status"] = response.status_code

        log.info(
            "accela_api_call",
            method=method,
            path=path,
            agency=self.agency,
            environment=self.environment,
            status=response.status_code,
            attempt=attempt_no,
            duration_ms=int(response.elapsed.total_seconds() * 1000),
            raw=True,
        )

        if response.status_code == 401:
            if not state["tried_refresh_once"]:
                state["tried_refresh_once"] = True
                self.tokens = await refresh_if_needed(
                    self.tokens, self.settings, self.token_store, force=True
                )
                raise RetryableError("token refreshed; retrying after 401")
            raise AccelaAPIError.from_response(response, path=path, method=method)

        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            raise RetryableError("rate limited", status=429, retry_after=retry_after)

        if 500 <= response.status_code < 600 and response.status_code != 501:
            raise RetryableError(f"server {response.status_code}", status=response.status_code)

        if response.status_code >= 400:
            raise AccelaAPIError.from_response(response, path=path, method=method)

        return response


def _extract_rate_limit_headers(headers: httpx.Headers) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        lk = key.lower()
        if any(lk.startswith(p) for p in _RATE_LIMIT_HEADER_PREFIXES):
            out[lk] = value
    return out


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header. We don't honor HTTP-date forms — Accela
    sends seconds when it sends one at all."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


__all__ = [
    "AccelaClient",
    "RetryConfig",
]
