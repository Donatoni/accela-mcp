"""Tests for the server bootstrap path that doesn't require running stdio."""

from __future__ import annotations

import pytest
import respx

from accela_mcp.auth.refresher import RefreshTokenExpiredError
from accela_mcp.auth.token_store import Tokens, TokenStore
from accela_mcp.capabilities import LoadedConfig
from accela_mcp.server import StartupError, build_context, register_enabled_tools
from accela_mcp.settings import Settings
from accela_mcp.tools._base import ToolContext


@pytest.mark.asyncio
async def test_build_context_requires_tokens(
    settings: Settings, loaded_config: LoadedConfig
) -> None:
    with pytest.raises(StartupError) as exc:
        await build_context(settings, loaded_config)
    assert "accela-mcp auth" in str(exc.value)


@pytest.mark.asyncio
async def test_build_context_agency_mismatch(
    settings: Settings,
    loaded_config: LoadedConfig,
    fresh_tokens: Tokens,
    token_store: TokenStore,
) -> None:
    other = fresh_tokens.model_copy(update={"agency": "ELSEWHERE"})
    token_store.save(other)
    with pytest.raises(StartupError) as exc:
        await build_context(settings, loaded_config)
    assert "agency" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_build_context_environment_mismatch(
    settings: Settings,
    loaded_config: LoadedConfig,
    fresh_tokens: Tokens,
    token_store: TokenStore,
) -> None:
    other = fresh_tokens.model_copy(update={"environment": "PROD"})
    token_store.save(other)
    with pytest.raises(StartupError) as exc:
        await build_context(settings, loaded_config)
    assert "environment" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_build_context_refresh_expired(
    settings: Settings,
    loaded_config: LoadedConfig,
    expired_refresh_tokens: Tokens,
    token_store: TokenStore,
) -> None:
    token_store.save(expired_refresh_tokens)
    with pytest.raises(RefreshTokenExpiredError):
        await build_context(settings, loaded_config)


@pytest.mark.asyncio
@respx.mock
async def test_build_context_happy_path(
    settings: Settings,
    loaded_config: LoadedConfig,
    fresh_tokens: Tokens,
    token_store: TokenStore,
) -> None:
    token_store.save(fresh_tokens)
    ctx = await build_context(settings, loaded_config)
    assert ctx.client.agency == "NULLISLAND"
    assert ctx.client.environment == "TEST"
    await ctx.client.aclose()


def test_register_enabled_tools_creates_groups(tool_context: ToolContext) -> None:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test-server")
    registered = register_enabled_tools(mcp, tool_context)
    # All default-on groups should have registered.
    assert "discovery" in registered
    assert "records_read" in registered
    # And a sampling of the actual tools should be present.
    assert mcp._tool_manager.get_tool("accela_get_agency") is not None
    assert mcp._tool_manager.get_tool("accela_search_records") is not None
