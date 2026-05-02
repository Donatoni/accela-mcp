"""Interactive OAuth 2.0 Authorization Code flow with PKCE.

Run once per refresh-token-validity-window (≤7 days). Spins up a one-shot
loopback HTTP listener bound to 127.0.0.1, opens the browser to Accela's
authorize endpoint, captures the redirect, exchanges the code for tokens,
and returns a `Tokens` bundle ready to be persisted.

PKCE is always enabled (S256). The authorization-code grant doesn't strictly
require it for confidential clients, but it's a defense-in-depth win against
a compromised redirect listener and Accela's IdP supports it.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import secrets
import urllib.parse
import webbrowser
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any

import httpx

from accela_mcp.auth.token_store import Tokens, make_refresh_expiry
from accela_mcp.observability.logging_config import get_logger
from accela_mcp.settings import Settings

log = get_logger(__name__)

CALLBACK_TIMEOUT_SECONDS = 300  # 5 minutes for the human to log in


class OAuthFlowError(RuntimeError):
    """Raised for any failure during the interactive auth flow."""


def _pkce_pair() -> tuple[str, str]:
    """Generate a (verifier, S256 challenge) pair per RFC 7636."""
    verifier = secrets.token_urlsafe(64)  # 86 chars, well within RFC bounds
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _CallbackResult:
    """Mutable holder for the redirect-handler thread to communicate back."""

    __slots__ = ("code", "error", "error_description", "state")

    def __init__(self) -> None:
        self.code: str | None = None
        self.state: str | None = None
        self.error: str | None = None
        self.error_description: str | None = None


def _build_handler(result: _CallbackResult) -> type[BaseHTTPRequestHandler]:
    """Build a fresh handler class bound to a local result holder.

    A fresh class per flow avoids cross-talk if the function is reused.
    """

    class _Handler(BaseHTTPRequestHandler):
        # Class-level config — silences default access logs.
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            result.code = params.get("code", [None])[0]
            result.state = params.get("state", [None])[0]
            result.error = params.get("error", [None])[0]
            result.error_description = params.get("error_description", [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if result.error:
                msg = result.error_description or result.error
                body = (
                    f"<h1>Authentication failed</h1><p>{_escape_html(msg)}</p>"
                    "<p>You can close this window.</p>"
                )
            else:
                body = "<h1>Authentication successful</h1><p>You can close this window.</p>"
            self.wfile.write(body.encode("utf-8"))

    return _Handler


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _parse_redirect(uri: str) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(uri)
    host = parsed.hostname or "localhost"
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise OAuthFlowError(f"Redirect URI host {host!r} is not loopback; aborting for safety.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # Always bind 127.0.0.1 — never the resolved 'localhost' which may include 0.0.0.0
    # in some IPv6 setups.
    return ("127.0.0.1", port)


async def run_authorization_code_flow(
    settings: Settings,
    *,
    agency: str,
    environment: str,
    scopes: list[str],
    open_browser: bool = True,
) -> Tokens:
    """Run the interactive OAuth flow end-to-end. Returns fresh `Tokens`."""

    if not scopes:
        raise OAuthFlowError("scopes must be a non-empty list")

    bind_host, bind_port = _parse_redirect(settings.redirect_uri)
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()

    authorize_params = {
        "response_type": "code",
        "client_id": settings.app_id,
        "agency_name": agency,
        "environment": environment,
        "redirect_uri": settings.redirect_uri,
        "state": state,
        "scope": " ".join(scopes),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{settings.auth_base_url}/oauth2/authorize?" + urllib.parse.urlencode(
        authorize_params
    )

    result = _CallbackResult()
    handler_cls = _build_handler(result)

    try:
        server = HTTPServer((bind_host, bind_port), handler_cls)
    except OSError as e:
        raise OAuthFlowError(
            f"Failed to bind {bind_host}:{bind_port} for the OAuth callback. "
            f"Is something else using this port? ({e})"
        ) from e

    server_thread = Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    log.info(
        "oauth_authorize_url_built",
        agency=agency,
        environment=environment,
        bind=f"{bind_host}:{bind_port}",
    )
    print(f"Opening browser to authenticate with agency {agency}...")
    print(f"Listening for redirect on http://{bind_host}:{bind_port} ...")
    if open_browser:
        with contextlib.suppress(webbrowser.Error):
            webbrowser.open(authorize_url)
    print(f"If your browser didn't open, visit:\n  {authorize_url}\n")

    deadline = asyncio.get_event_loop().time() + CALLBACK_TIMEOUT_SECONDS
    try:
        while server_thread.is_alive():
            if asyncio.get_event_loop().time() > deadline:
                raise OAuthFlowError(f"Auth flow timed out after {CALLBACK_TIMEOUT_SECONDS}s.")
            await asyncio.sleep(0.2)
    finally:
        # Best-effort — the listener has already served one request.
        with contextlib.suppress(OSError):
            server.server_close()

    if result.error:
        raise OAuthFlowError(
            f"OAuth error from Accela: {result.error}: {result.error_description or ''}"
        )
    if not result.state or not secrets.compare_digest(result.state, state):
        raise OAuthFlowError("OAuth state mismatch — possible CSRF; aborting.")
    if not result.code:
        raise OAuthFlowError("Did not receive an authorization code from Accela.")

    return await _exchange_code_for_tokens(
        settings,
        agency=agency,
        environment=environment,
        code=result.code,
        code_verifier=verifier,
        scopes=scopes,
    )


async def _exchange_code_for_tokens(
    settings: Settings,
    *,
    agency: str,
    environment: str,
    code: str,
    code_verifier: str,
    scopes: list[str],
) -> Tokens:
    """POST to /oauth2/token to swap the code for tokens."""
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.app_id,
        "client_secret": settings.app_secret.get_secret_value(),
        "code": code,
        "redirect_uri": settings.redirect_uri,
        "agency_name": agency,
        "environment": environment,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.auth_base_url}/oauth2/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code != 200:
        # Log status + body sans secrets — body is small here, contains
        # OAuth error fields which are safe to log.
        log.error(
            "token_exchange_failed",
            status=response.status_code,
            body=response.text[:500],
        )
        raise OAuthFlowError(
            f"Token exchange failed (HTTP {response.status_code}). "
            "Verify ACCELA_APP_ID, ACCELA_APP_SECRET, and the registered redirect URI."
        )

    body = response.json()
    return _tokens_from_response(
        body,
        agency=agency,
        environment=environment,
        fallback_scope=" ".join(scopes),
    )


def _tokens_from_response(
    body: dict[str, Any],
    *,
    agency: str,
    environment: str,
    fallback_scope: str,
) -> Tokens:
    """Convert a /oauth2/token JSON response to a `Tokens` model.

    `expires_in` arrives as a string from some Accela endpoints and an int
    from others; we coerce.
    """
    try:
        access = body["access_token"]
        refresh = body["refresh_token"]
        expires_in = int(body["expires_in"])
    except (KeyError, TypeError, ValueError) as e:
        raise OAuthFlowError(
            "Token endpoint returned an unexpected payload "
            "(missing or malformed access_token/refresh_token/expires_in)."
        ) from e

    now = datetime.now(UTC)
    return Tokens(
        access_token=access,
        refresh_token=refresh,
        token_type=body.get("token_type", "bearer"),
        scope=body.get("scope") or fallback_scope,
        agency=agency,
        environment=environment,
        expires_at=now + timedelta(seconds=expires_in),
        refresh_expires_at=make_refresh_expiry(now),
        issued_at=now,
    )


__all__ = [
    "CALLBACK_TIMEOUT_SECONDS",
    "OAuthFlowError",
    "run_authorization_code_flow",
]
