"""Async-safe access-token refresh.

Both the proactive (pre-expiry) and reactive (post-401) paths route through
`refresh_if_needed`. A single `asyncio.Lock` per `AccelaClient` ensures only
one refresh is in flight at a time even under concurrent fan-out.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from accela_mcp.auth.token_store import (
    Tokens,
    TokenStore,
    make_refresh_expiry,
)
from accela_mcp.observability.logging_config import get_logger
from accela_mcp.settings import Settings

log = get_logger(__name__)


class RefreshTokenExpiredError(RuntimeError):
    """The refresh token has exceeded its 7-day window. Operator must re-auth."""


_LOCK_REGISTRY: dict[int, asyncio.Lock] = {}


def _lock_for(store: TokenStore) -> asyncio.Lock:
    """One lock per TokenStore instance.

    Keyed by `id(store)` because `TokenStore` isn't hashable in any meaningful
    semantic way — we want one lock per live instance, no cross-test bleed.
    """
    key = id(store)
    if key not in _LOCK_REGISTRY:
        _LOCK_REGISTRY[key] = asyncio.Lock()
    return _LOCK_REGISTRY[key]


async def refresh_if_needed(
    tokens: Tokens,
    settings: Settings,
    store: TokenStore,
    *,
    force: bool = False,
) -> Tokens:
    """Refresh the access token if it's expiring (or `force=True`).

    Returns either the original `tokens` (no refresh needed) or the new
    `Tokens` from the IdP. The new tokens are persisted before returning.
    """
    lock = _lock_for(store)
    async with lock:
        # Re-check inside the lock — another task may have refreshed already.
        latest = store.load() or tokens
        if not force and not latest.is_expiring_soon:
            return latest

        if latest.is_refresh_expired:
            raise RefreshTokenExpiredError(
                "The Accela refresh token has expired. "
                "Please run `accela-mcp auth` to re-authenticate."
            )

        log.info(
            "refreshing_access_token",
            agency=latest.agency,
            environment=latest.environment,
            forced=force,
            seconds_until_refresh_expires=latest.seconds_until_refresh_expires(),
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.auth_base_url}/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": settings.app_id,
                    "client_secret": settings.app_secret.get_secret_value(),
                    "refresh_token": latest.refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            # Treat any non-200 from the refresh endpoint as fatal — the most
            # likely cause is the 7-day window elapsing.
            log.error(
                "token_refresh_failed",
                status=response.status_code,
                body=response.text[:500],
            )
            raise RefreshTokenExpiredError(
                f"Token refresh failed (HTTP {response.status_code}). "
                "Please run `accela-mcp auth` to re-authenticate."
            )

        body = response.json()
        new_tokens = _new_tokens_from_refresh(body, latest)
        store.save(new_tokens)
        log.info(
            "access_token_refreshed",
            expires_at=new_tokens.expires_at.isoformat(),
            refresh_expires_at=new_tokens.refresh_expires_at.isoformat(),
        )
        return new_tokens


def _new_tokens_from_refresh(body: dict[str, Any], previous: Tokens) -> Tokens:
    try:
        access = body["access_token"]
        refresh = body["refresh_token"]
        expires_in = int(body["expires_in"])
    except (KeyError, TypeError, ValueError) as e:
        raise RefreshTokenExpiredError(
            "Refresh response was missing required fields. Please run "
            "`accela-mcp auth` to re-authenticate."
        ) from e

    now = datetime.now(UTC)
    return Tokens(
        access_token=access,
        refresh_token=refresh,
        token_type=body.get("token_type", previous.token_type),
        scope=body.get("scope") or previous.scope,
        agency=previous.agency,
        environment=previous.environment,
        expires_at=now + timedelta(seconds=expires_in),
        refresh_expires_at=make_refresh_expiry(now),
        issued_at=now,
    )


async def introspect(tokens: Tokens, settings: Settings) -> dict[str, Any] | None:
    """Call /oauth2/tokeninfo. Returns the response dict, or None if 4xx."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{settings.auth_base_url}/oauth2/tokeninfo",
            headers={"Authorization": tokens.access_token},
        )
    if 400 <= response.status_code < 500:
        return None
    response.raise_for_status()
    return response.json()


__all__ = [
    "RefreshTokenExpiredError",
    "introspect",
    "refresh_if_needed",
]
