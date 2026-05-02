"""Auth tools — status and interactive login.

These are the only tools that work without persisted tokens, so the server
registers them up front. Without them, a Claude Desktop / Codex user whose
tokens have expired (or who's never logged in) would have no in-chat way
to recover and would need to drop to a terminal.

Both tools take an `AuthContext` rather than the full `ToolContext` because
they don't need an `AccelaClient` — they read the token store directly and,
for `accela_login`, drive the OAuth flow against the IdP.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.auth.flow import OAuthFlowError, run_authorization_code_flow
from accela_mcp.auth.token_store import TokenStore
from accela_mcp.capabilities import (
    LoadedConfig,
    default_capabilities_yaml,
    default_groups,
    scopes_for,
)
from accela_mcp.settings import Settings
from accela_mcp.tools._base import tool_call

# Read groups that are safe to default to during in-chat login when there's
# no capabilities.yaml on disk yet. Mirrors the CLI's setup defaults.
_FALLBACK_LOGIN_GROUPS = {
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


@dataclass
class AuthContext:
    """Minimal context for auth tools.

    Carries `settings` and an optional `config`. The config is None when the
    server starts in bootstrap mode (no tokens yet, no validated YAML), in
    which case `accela_login` falls back to a sensible default scope set.
    """

    settings: Settings
    config: LoadedConfig | None = None


def register(mcp: FastMCP, ctx: AuthContext) -> None:
    @mcp.tool()
    @tool_call("accela_auth_status")
    async def accela_auth_status() -> dict[str, Any]:
        """Reports the current Accela authentication state. No API call.

        Returns whether tokens are persisted, the connected agency and
        environment, when the access and refresh tokens expire, and the
        granted scope. Use this when the user asks "am I logged in?" or
        before suggesting a re-login.
        """
        store = TokenStore(ctx.settings.token_path, ctx.settings.mcp_key.get_secret_value())
        try:
            tokens = store.load()
        except RuntimeError as e:
            return {
                "authenticated": False,
                "error": "token_decrypt_failed",
                "message": str(e),
                "token_path": str(ctx.settings.token_path),
                "next_step": "Run accela_login to re-authenticate.",
            }

        if tokens is None:
            return {
                "authenticated": False,
                "message": ("No Accela tokens are persisted yet. Run accela_login to sign in."),
                "token_path": str(ctx.settings.token_path),
                "next_step": "Run accela_login.",
            }

        if tokens.is_refresh_expired:
            return {
                "authenticated": False,
                "error": "refresh_token_expired",
                "message": (
                    "The refresh token has expired (Accela's window is 7 days). "
                    "Run accela_login to re-authenticate."
                ),
                "agency": tokens.agency,
                "environment": tokens.environment,
                "next_step": "Run accela_login.",
            }

        return {
            "authenticated": True,
            "agency": tokens.agency,
            "environment": tokens.environment,
            "scope": tokens.scope,
            "access_expires_at": tokens.expires_at.isoformat(),
            "refresh_expires_at": tokens.refresh_expires_at.isoformat(),
            "refresh_expiring_soon": tokens.is_refresh_expiring_soon,
            "seconds_until_refresh_expires": tokens.seconds_until_refresh_expires(),
        }

    @mcp.tool()
    @tool_call("accela_login")
    async def accela_login(
        agency: str | None = None,
        environment: str | None = None,
        open_browser: bool = True,
    ) -> dict[str, Any]:
        """Runs the interactive Accela OAuth login flow and persists tokens.

        Opens the user's default browser to Accela's authorize URL, captures
        the redirect on a one-shot loopback listener, exchanges the code for
        tokens, and saves them encrypted. Use when accela_auth_status reports
        not authenticated, or when the user asks to log in.

        `agency` and `environment` default to the values in capabilities.yaml.
        Set `open_browser=False` to print the URL instead of auto-opening
        (useful in remote / headless environments).

        After success, ask the user to restart the host app (Claude Desktop /
        Codex) so the rest of the Accela tools become visible.
        """
        if not ctx.settings.app_id or not ctx.settings.app_secret.get_secret_value():
            return {
                "error": "config_missing",
                "message": (
                    "ACCELA_APP_ID and ACCELA_APP_SECRET must be set before "
                    "logging in. Open the Accela extension settings (or your "
                    "host app's MCP server config) and fill them in, then "
                    "retry accela_login."
                ),
            }

        # Resolution order: explicit arg > validated config > MCPB env var.
        # The env-var fallback covers bootstrap mode (no capabilities.yaml
        # yet) where the user filled in Agency / Environment via the host
        # extension UI and shouldn't have to repeat them in chat.
        resolved_agency = (
            agency
            or (ctx.config.capabilities.agency if ctx.config else None)
            or (os.environ.get("ACCELA_AGENCY") or "").strip()
            or None
        )
        resolved_environment = (
            environment
            or (ctx.config.capabilities.environment if ctx.config else None)
            or (os.environ.get("ACCELA_ENVIRONMENT") or "").strip()
            or None
        )
        if not resolved_agency or not resolved_environment:
            return {
                "error": "agency_missing",
                "message": (
                    "agency and environment are required. Either pass them "
                    "as arguments or create a capabilities.yaml with the "
                    "values for your Accela tenant."
                ),
            }

        if ctx.config is not None:
            scope_list = ctx.config.scopes
        else:
            scope_list = scopes_for(_FALLBACK_LOGIN_GROUPS | default_groups())

        try:
            tokens = await run_authorization_code_flow(
                ctx.settings,
                agency=resolved_agency,
                environment=resolved_environment,
                scopes=scope_list,
                open_browser=open_browser,
            )
        except OAuthFlowError as e:
            return {
                "error": "oauth_flow_failed",
                "message": str(e),
                "next_step": (
                    "Common causes: the redirect URI doesn't match the one "
                    "registered on the Accela Developer Portal, the app "
                    "secret is wrong, or another process is using the "
                    "redirect port. Fix and retry accela_login."
                ),
            }

        store = TokenStore(ctx.settings.token_path, ctx.settings.mcp_key.get_secret_value())
        store.save(tokens)

        # Auto-create capabilities.yaml on first login. Without this, restarting
        # the host app would land back in bootstrap mode because the config is
        # still missing. Mirror what `accela-mcp auth` does at the CLI.
        config_created = False
        if not ctx.settings.config_path.exists():
            ctx.settings.config_path.parent.mkdir(parents=True, exist_ok=True)
            ctx.settings.config_path.write_text(
                default_capabilities_yaml(tokens.agency, tokens.environment),
                encoding="utf-8",
            )
            config_created = True

        return {
            "authenticated": True,
            "agency": tokens.agency,
            "environment": tokens.environment,
            "scope": tokens.scope,
            "access_expires_at": tokens.expires_at.isoformat(),
            "refresh_expires_at": tokens.refresh_expires_at.isoformat(),
            "config_created": config_created,
            "config_path": str(ctx.settings.config_path),
            "next_step": (
                "Login saved. Restart the host app (Claude Desktop or Codex) "
                "to enable the rest of the Accela tools."
            ),
        }


__all__ = ["AuthContext", "register"]
