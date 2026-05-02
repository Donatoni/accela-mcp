"""MCP server bootstrap.

Wires settings + capabilities + tokens + the HTTP client into a `FastMCP`
instance, registers tool modules per the enabled groups, and runs the stdio
transport.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.api.client import AccelaClient, RetryConfig
from accela_mcp.auth.refresher import RefreshTokenExpiredError, introspect, refresh_if_needed
from accela_mcp.auth.token_store import TokenStore
from accela_mcp.capabilities import LoadedConfig, group_meta, load_capabilities
from accela_mcp.observability.logging_config import configure_logging, get_logger
from accela_mcp.settings import Settings, get_settings
from accela_mcp.tools._base import ToolContext
from accela_mcp.utils.cache import TTLCache

log = get_logger(__name__)


class StartupError(RuntimeError):
    """Raised on misconfiguration that prevents the server from starting."""


async def build_context(settings: Settings, config: LoadedConfig) -> ToolContext:
    """Load tokens, validate them, build the AccelaClient, return a context."""
    store = TokenStore(settings.token_path, settings.mcp_key.get_secret_value())
    tokens = store.load()
    if tokens is None:
        raise StartupError(
            "No persisted tokens found. Run `accela-mcp auth` to authenticate first."
        )

    if tokens.agency.lower() != config.capabilities.agency.lower():
        raise StartupError(
            f"capabilities.yaml agency {config.capabilities.agency!r} does not match the "
            f"agency in the persisted tokens ({tokens.agency!r}). Run `accela-mcp auth` "
            "for the correct agency or update the YAML."
        )
    if tokens.environment.lower() != config.capabilities.environment.lower():
        raise StartupError(
            f"capabilities.yaml environment {config.capabilities.environment!r} does not "
            f"match the persisted token environment ({tokens.environment!r})."
        )

    if tokens.is_refresh_expired:
        raise RefreshTokenExpiredError(
            "The Accela refresh token has expired. Run `accela-mcp auth` to re-authenticate."
        )

    # Proactive refresh if expiring or already expired.
    tokens = await refresh_if_needed(tokens, settings, store)

    if tokens.is_refresh_expiring_soon:
        log.warning(
            "refresh_token_expiring_soon",
            seconds_until_refresh_expires=tokens.seconds_until_refresh_expires(),
            hint="Run `accela-mcp auth` within 24 hours to avoid service interruption.",
        )

    retry_cfg = RetryConfig(
        max_attempts=config.capabilities.rate_limit.max_retries + 1,
        base_backoff_seconds=config.capabilities.rate_limit.base_backoff_seconds,
        max_backoff_seconds=config.capabilities.rate_limit.max_backoff_seconds,
    )
    client = AccelaClient(
        settings=settings,
        tokens=tokens,
        token_store=store,
        agency=tokens.agency,
        environment=tokens.environment,
        retry=retry_cfg,
    )

    cache: TTLCache[dict[str, Any]] = TTLCache(
        ttl_seconds=max(1, config.capabilities.cache.reference_data_ttl_seconds)
    )

    return ToolContext(
        settings=settings,
        config=config,
        client=client,
        reference_cache=cache,
    )


def register_enabled_tools(mcp: FastMCP, ctx: ToolContext) -> list[str]:
    """Import every enabled group's module and call its `register(mcp, ctx)`.

    Returns the list of group IDs whose tools were registered, for logging.
    """
    registered: list[str] = []
    for group_id in sorted(ctx.config.enabled_groups):
        meta = group_meta(group_id)
        module_path = meta.get("module")
        if not module_path:
            log.info(
                "skipping_group_no_module",
                group=group_id,
                reason="group has no implementation in this version",
            )
            continue
        module = importlib.import_module(module_path)
        if not hasattr(module, "register"):
            raise StartupError(
                f"tool module {module_path!r} for group {group_id!r} has no register()"
            )
        module.register(mcp, ctx)
        registered.append(group_id)
        log.info("group_registered", group=group_id)
    return registered


async def serve_async(
    *,
    settings: Settings | None = None,
    config: LoadedConfig | None = None,
) -> None:
    """Async entry point — used by the CLI's `serve` subcommand."""
    settings = settings or get_settings()
    config = config or load_capabilities(settings.config_path)

    configure_logging(
        level=config.capabilities.logging.level, fmt=config.capabilities.logging.format
    )
    log.info(
        "accela_mcp_starting",
        agency=config.capabilities.agency,
        environment=config.capabilities.environment,
        enabled_groups=sorted(config.enabled_groups),
        scopes=config.scopes,
    )

    ctx = await build_context(settings, config)

    # Best-effort token-info validation; on 4xx we already refreshed so don't error.
    try:
        info = await introspect(ctx.client.tokens, settings)
        if info:
            log.info(
                "token_introspection_ok",
                user_id=info.get("userId"),
                expires_in=info.get("expiresIn"),
                scopes=info.get("scopes"),
            )
    except Exception as e:
        log.warning("token_introspection_failed", error=str(e))

    mcp = FastMCP("accela-mcp")
    register_enabled_tools(mcp, ctx)

    try:
        await mcp.run_stdio_async()
    finally:
        await ctx.client.aclose()


def serve() -> None:
    """Sync wrapper for the CLI entry point."""
    asyncio.run(serve_async())


__all__ = [
    "StartupError",
    "build_context",
    "register_enabled_tools",
    "serve",
    "serve_async",
]
