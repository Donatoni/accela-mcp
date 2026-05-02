"""MCP server bootstrap.

Wires settings + capabilities + tokens + the HTTP client into a `FastMCP`
instance, registers tool modules per the enabled groups, and runs the stdio
transport.

The auth group (`accela_auth_status`, `accela_login`) is always registered
first, before tokens are validated. If token loading fails (no tokens yet,
or refresh token expired), the server falls into "bootstrap mode" — only
the auth tools are exposed, so the user can call `accela_login` from chat
to recover without dropping to a terminal.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.api.client import AccelaClient, RetryConfig
from accela_mcp.auth.refresher import RefreshTokenExpiredError, introspect, refresh_if_needed
from accela_mcp.auth.token_store import TokenStore
from accela_mcp.capabilities import (
    CapabilityConfigError,
    LoadedConfig,
    group_meta,
    load_capabilities,
)
from accela_mcp.observability.logging_config import configure_logging, get_logger
from accela_mcp.safety import AuditLog
from accela_mcp.settings import Settings, ensure_mcp_key, get_settings
from accela_mcp.tools._base import ToolContext
from accela_mcp.tools.auth import AuthContext
from accela_mcp.tools.auth import register as register_auth_tools
from accela_mcp.utils.cache import TTLCache

log = get_logger(__name__)

# Group IDs whose tools depend only on settings/config and don't need an
# authenticated AccelaClient. Registered separately so they remain available
# in bootstrap mode.
_BOOTSTRAP_GROUPS = frozenset({"auth"})


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

    audit = AuditLog(config.capabilities.writes.audit_log_path)
    if config.capabilities.writes.enabled:
        log.info(
            "writes_enabled",
            audit_log_path=str(config.capabilities.writes.audit_log_path)
            if config.capabilities.writes.audit_log_path
            else None,
            agency_environment_allowed=config.capabilities.writes.agency_environment_allowed
            or "any",
            real_money_allowed=config.capabilities.payments.real_money_allowed,
        )

    return ToolContext(
        settings=settings,
        config=config,
        client=client,
        reference_cache=cache,
        audit_log=audit,
    )


def register_enabled_tools(mcp: FastMCP, ctx: ToolContext) -> list[str]:
    """Import every enabled group's module and call its `register(mcp, ctx)`.

    Skips groups that were already registered by the bootstrap path (auth).
    Returns the list of group IDs whose tools were registered, for logging.
    """
    registered: list[str] = []
    for group_id in sorted(ctx.config.enabled_groups):
        if group_id in _BOOTSTRAP_GROUPS:
            continue
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
    if settings is None:
        # First-run MCPB users leave ACCELA_MCP_KEY blank in the host settings
        # panel; auto-generate one and persist before settings validation.
        ensure_mcp_key()
        settings = get_settings()

    # Capabilities config is optional in bootstrap mode — the user may not
    # have one yet (first-time MCPB install, no terminal setup ever ran).
    # If the file is simply missing, fall through to bootstrap mode so the
    # in-chat `accela_login` flow can recover. If the file exists but is
    # malformed, propagate the error — that's a real misconfiguration.
    config_load_error: CapabilityConfigError | None = None
    if config is None:
        if settings.config_path.exists():
            config = load_capabilities(settings.config_path)
        else:
            config_load_error = CapabilityConfigError(
                f"capabilities config not found at {settings.config_path}"
            )

    log_level = config.capabilities.logging.level if config else "INFO"
    log_format = config.capabilities.logging.format if config else "json"
    configure_logging(level=log_level, fmt=log_format)

    if config is not None:
        log.info(
            "accela_mcp_starting",
            agency=config.capabilities.agency,
            environment=config.capabilities.environment,
            enabled_groups=sorted(config.enabled_groups),
            scopes=config.scopes,
        )
    else:
        log.warning(
            "accela_mcp_starting_without_config",
            reason=str(config_load_error) if config_load_error else "no config provided",
            hint="Only auth tools will be available until capabilities.yaml exists.",
        )

    mcp = FastMCP("accela-mcp")

    # Auth tools register first so the user can recover from chat even if
    # tokens are missing or the refresh window has lapsed.
    register_auth_tools(mcp, AuthContext(settings=settings, config=config))

    ctx: ToolContext | None = None
    if config is not None:
        try:
            ctx = await build_context(settings, config)
        except (StartupError, RefreshTokenExpiredError) as e:
            log.warning(
                "starting_in_bootstrap_mode",
                reason=str(e),
                hint=(
                    "Only accela_auth_status and accela_login are available. "
                    "Call accela_login from chat to authenticate, then restart "
                    "the host app to enable the rest of the Accela tools."
                ),
            )

    if ctx is not None:
        register_enabled_tools(mcp, ctx)

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

    try:
        await mcp.run_stdio_async()
    finally:
        if ctx is not None:
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
