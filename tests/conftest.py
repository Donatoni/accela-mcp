"""Pytest fixtures shared across the unit suite."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet

from accela_mcp.api.client import AccelaClient, RetryConfig
from accela_mcp.auth.token_store import REFRESH_TOKEN_LIFETIME, Tokens, TokenStore
from accela_mcp.capabilities import (
    Capabilities,
    LoadedConfig,
    scopes_for,
)
from accela_mcp.settings import Settings
from accela_mcp.tools._base import ToolContext
from accela_mcp.utils.cache import TTLCache

# Make sure no stray ACCELA_* env vars from the host bleed into tests that
# instantiate Settings via env.
_RESERVED_ENV = [
    "ACCELA_APP_ID",
    "ACCELA_APP_SECRET",
    "ACCELA_REDIRECT_URI",
    "ACCELA_MCP_KEY",
    "ACCELA_MCP_CONFIG_PATH",
    "ACCELA_MCP_TOKEN_PATH",
    "ACCELA_MCP_LOG_LEVEL",
    "ACCELA_MCP_LOG_FORMAT",
    "ACCELA_MCP_ENV_PATH",
    "ACCELA_AUTH_BASE_URL",
    "ACCELA_API_BASE_URL",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _RESERVED_ENV:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def settings(tmp_path: Path, fernet_key: str) -> Settings:
    return Settings(
        ACCELA_APP_ID="test-app-id",
        ACCELA_APP_SECRET="test-app-secret",
        ACCELA_REDIRECT_URI="http://localhost:8765/oauth/callback",
        ACCELA_MCP_KEY=fernet_key,
        ACCELA_MCP_CONFIG_PATH=str(tmp_path / "capabilities.yaml"),
        ACCELA_MCP_TOKEN_PATH=str(tmp_path / "tokens.json"),
        ACCELA_AUTH_BASE_URL="https://auth.test.example",
        ACCELA_API_BASE_URL="https://apis.test.example",
    )


@pytest.fixture
def token_store(settings: Settings) -> TokenStore:
    return TokenStore(settings.token_path, settings.mcp_key.get_secret_value())


@pytest.fixture
def fresh_tokens() -> Tokens:
    now = datetime.now(UTC)
    return Tokens(
        access_token="initial_access_token",
        refresh_token="initial_refresh_token",
        scope="records inspections",
        agency="NULLISLAND",
        environment="TEST",
        expires_at=now + timedelta(hours=8),
        refresh_expires_at=now + REFRESH_TOKEN_LIFETIME,
        issued_at=now,
    )


@pytest.fixture
def expiring_tokens() -> Tokens:
    """Access token expires in 30 seconds — triggers proactive refresh."""
    now = datetime.now(UTC)
    return Tokens(
        access_token="old_access",
        refresh_token="old_refresh",
        scope="records",
        agency="NULLISLAND",
        environment="TEST",
        expires_at=now + timedelta(seconds=30),
        refresh_expires_at=now + timedelta(days=5),
        issued_at=now,
    )


@pytest.fixture
def expired_refresh_tokens() -> Tokens:
    """Refresh token already expired — must hard-fail."""
    now = datetime.now(UTC)
    return Tokens(
        access_token="dead_access",
        refresh_token="dead_refresh",
        scope="records",
        agency="NULLISLAND",
        environment="TEST",
        expires_at=now - timedelta(seconds=30),
        refresh_expires_at=now - timedelta(seconds=1),
        issued_at=now - timedelta(days=8),
    )


@pytest.fixture
def loaded_config() -> LoadedConfig:
    enabled = {
        "discovery",
        "records_read",
        "inspections_read",
        "documents_read",
        "property_read",
        "people_read",
        "workflow_read",
        "fees_read",
        "reference_data",
        "search",
    }
    caps = Capabilities(
        version=1,
        agency="NULLISLAND",
        environment="TEST",
        enabled_groups=sorted(enabled),
    )
    return LoadedConfig(
        capabilities=caps,
        enabled_groups=enabled,
        scopes=scopes_for(enabled),
    )


@pytest_asyncio.fixture
async def client(
    settings: Settings,
    fresh_tokens: Tokens,
    token_store: TokenStore,
) -> AsyncIterator[AccelaClient]:
    """A client wired to a transport-injected httpx.AsyncClient.

    Test bodies attach `respx` mocks; the client uses fast retry config so the
    suite finishes quickly.
    """
    token_store.save(fresh_tokens)
    transport_client = httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=httpx.Timeout(5.0),
    )
    cl = AccelaClient(
        settings=settings,
        tokens=fresh_tokens,
        token_store=token_store,
        agency=fresh_tokens.agency,
        environment=fresh_tokens.environment,
        retry=RetryConfig(max_attempts=4, fast_for_tests=True),
        http_client=transport_client,
    )
    try:
        yield cl
    finally:
        await transport_client.aclose()


@pytest_asyncio.fixture
async def tool_context(
    settings: Settings,
    loaded_config: LoadedConfig,
    client: AccelaClient,
) -> AsyncIterator[ToolContext]:
    cache: TTLCache[dict[str, Any]] = TTLCache(ttl_seconds=60)
    yield ToolContext(
        settings=settings,
        config=loaded_config,
        client=client,
        reference_cache=cache,
    )


def _has_envvar(name: str) -> bool:
    return os.environ.get(name) not in (None, "")


@pytest.fixture
def sample_record() -> dict[str, Any]:
    """A trimmed sample record matching Accela's typical record shape."""
    return {
        "id": "ISLANDTON-14CAP-00000-000I4",
        "customId": "BLD14-00255",
        "trackingId": 204387084,
        "value": "14CAP-00000-000I4",
        "serviceProviderCode": "ISLANDTON",
        "name": "BRAD-VuSpex Residential #1",
        "description": "Residence alteration",
        "type": {
            "module": "Building",
            "group": "Building",
            "type": "Residential",
            "subType": "Alteration",
            "category": "NA",
            "value": "Building/Residential/Alteration/NA",
            "id": "Building-Residential-Alteration-NA",
            "text": "Residential Alteration",
        },
        "status": {"value": "Submitted", "text": "Submitted"},
        "openedDate": "2014-10-15T14:46:49Z",
    }
