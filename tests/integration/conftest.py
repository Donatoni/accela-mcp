"""Integration test gating + sandbox fixtures.

These tests hit the real Accela sandbox. They run only when
`ACCELA_INTEGRATION_TEST=1` is in the environment AND `ACCELA_APP_ID`,
`ACCELA_APP_SECRET`, `ACCELA_MCP_KEY` are present and a token bundle has
been saved via `accela-mcp auth`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from accela_mcp.api.client import AccelaClient
from accela_mcp.auth.token_store import TokenStore
from accela_mcp.settings import get_settings

if not os.getenv("ACCELA_INTEGRATION_TEST"):
    pytest.skip(
        "set ACCELA_INTEGRATION_TEST=1 to run integration tests",
        allow_module_level=True,
    )


@pytest_asyncio.fixture
async def sandbox_client() -> AsyncIterator[AccelaClient]:
    settings = get_settings()
    store = TokenStore(settings.token_path, settings.mcp_key.get_secret_value())
    tokens = store.load()
    if tokens is None:
        pytest.skip("No persisted tokens — run `accela-mcp auth` first.")

    client = AccelaClient(
        settings=settings,
        tokens=tokens,
        token_store=store,
        agency=tokens.agency,
        environment=tokens.environment,
    )
    try:
        yield client
    finally:
        await client.aclose()
