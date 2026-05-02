from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import respx
from httpx import Response

from accela_mcp.auth.refresher import (
    RefreshTokenExpiredError,
    introspect,
    refresh_if_needed,
)
from accela_mcp.auth.token_store import REFRESH_TOKEN_LIFETIME, Tokens, TokenStore
from accela_mcp.settings import Settings


@pytest.mark.asyncio
@respx.mock
async def test_refresh_when_expiring_soon(
    expiring_tokens: Tokens, settings: Settings, token_store: TokenStore
) -> None:
    token_store.save(expiring_tokens)
    route = respx.post(f"{settings.auth_base_url}/oauth2/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "fresh_access",
                "refresh_token": "fresh_refresh",
                "token_type": "bearer",
                "expires_in": "28800",
                "scope": "records inspections",
            },
        )
    )
    new_tokens = await refresh_if_needed(expiring_tokens, settings, token_store)
    assert route.called
    assert new_tokens.access_token == "fresh_access"
    assert new_tokens.refresh_token == "fresh_refresh"
    # Persisted to disk too.
    persisted = token_store.load()
    assert persisted is not None
    assert persisted.access_token == "fresh_access"


@pytest.mark.asyncio
async def test_refresh_skipped_when_token_fresh(
    fresh_tokens: Tokens, settings: Settings, token_store: TokenStore
) -> None:
    token_store.save(fresh_tokens)
    # No respx mock — would error if a request fired.
    out = await refresh_if_needed(fresh_tokens, settings, token_store)
    assert out is fresh_tokens or out.access_token == fresh_tokens.access_token


@pytest.mark.asyncio
async def test_refresh_token_expired_raises(
    expired_refresh_tokens: Tokens, settings: Settings, token_store: TokenStore
) -> None:
    token_store.save(expired_refresh_tokens)
    with pytest.raises(RefreshTokenExpiredError):
        await refresh_if_needed(expired_refresh_tokens, settings, token_store)


@pytest.mark.asyncio
@respx.mock
async def test_refresh_400_treated_as_expired(
    expiring_tokens: Tokens, settings: Settings, token_store: TokenStore
) -> None:
    token_store.save(expiring_tokens)
    respx.post(f"{settings.auth_base_url}/oauth2/token").mock(
        return_value=Response(400, json={"code": "invalid_grant"})
    )
    with pytest.raises(RefreshTokenExpiredError):
        await refresh_if_needed(expiring_tokens, settings, token_store)


@pytest.mark.asyncio
@respx.mock
async def test_force_refresh_even_when_fresh(
    fresh_tokens: Tokens, settings: Settings, token_store: TokenStore
) -> None:
    token_store.save(fresh_tokens)
    respx.post(f"{settings.auth_base_url}/oauth2/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "forced_access",
                "refresh_token": "forced_refresh",
                "token_type": "bearer",
                "expires_in": "28800",
                "scope": "records",
            },
        )
    )
    out = await refresh_if_needed(fresh_tokens, settings, token_store, force=True)
    assert out.access_token == "forced_access"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_response_missing_fields_raises(
    expiring_tokens: Tokens, settings: Settings, token_store: TokenStore
) -> None:
    token_store.save(expiring_tokens)
    respx.post(f"{settings.auth_base_url}/oauth2/token").mock(
        return_value=Response(200, json={"access_token": "only_access"})
    )
    with pytest.raises(RefreshTokenExpiredError):
        await refresh_if_needed(expiring_tokens, settings, token_store)


@pytest.mark.asyncio
@respx.mock
async def test_introspect_ok(settings: Settings) -> None:
    respx.get(f"{settings.auth_base_url}/oauth2/tokeninfo").mock(
        return_value=Response(
            200,
            json={
                "appId": "x",
                "userId": "u",
                "agencyName": "NULLISLAND",
                "environment": "TEST",
                "scopes": ["records"],
                "expiresIn": 1234,
            },
        )
    )
    now = datetime.now(UTC)
    tokens = Tokens(
        access_token="a",
        refresh_token="r",
        scope="records",
        agency="NULLISLAND",
        environment="TEST",
        expires_at=now + timedelta(hours=8),
        refresh_expires_at=now + REFRESH_TOKEN_LIFETIME,
        issued_at=now,
    )
    info = await introspect(tokens, settings)
    assert info is not None
    assert info["userId"] == "u"


@pytest.mark.asyncio
@respx.mock
async def test_introspect_4xx_returns_none(settings: Settings, fresh_tokens: Tokens) -> None:
    respx.get(f"{settings.auth_base_url}/oauth2/tokeninfo").mock(return_value=Response(400))
    info = await introspect(fresh_tokens, settings)
    assert info is None
