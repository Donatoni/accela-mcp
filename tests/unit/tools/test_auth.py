from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from accela_mcp.auth.flow import OAuthFlowError
from accela_mcp.auth.token_store import REFRESH_TOKEN_LIFETIME, Tokens, TokenStore
from accela_mcp.capabilities import LoadedConfig
from accela_mcp.settings import Settings
from accela_mcp.tools import auth as auth_tools
from accela_mcp.tools.auth import AuthContext

from ._helpers import call, register_module, tool_names


def _auth_ctx(settings: Settings, config: LoadedConfig | None) -> AuthContext:
    return AuthContext(settings=settings, config=config)


def _register_auth(settings: Settings, config: LoadedConfig | None):
    return register_module(auth_tools, _auth_ctx(settings, config))


@pytest.mark.asyncio
async def test_register_creates_two_tools(settings: Settings, loaded_config: LoadedConfig) -> None:
    mcp = _register_auth(settings, loaded_config)
    assert tool_names(mcp) == {"accela_auth_status", "accela_login"}


@pytest.mark.asyncio
async def test_status_no_tokens(settings: Settings, loaded_config: LoadedConfig) -> None:
    mcp = _register_auth(settings, loaded_config)
    out = await call(mcp, "accela_auth_status")()
    assert out["authenticated"] is False
    assert "accela_login" in out["next_step"]


@pytest.mark.asyncio
async def test_status_with_valid_tokens(
    settings: Settings,
    loaded_config: LoadedConfig,
    fresh_tokens: Tokens,
    token_store: TokenStore,
) -> None:
    token_store.save(fresh_tokens)
    mcp = _register_auth(settings, loaded_config)
    out = await call(mcp, "accela_auth_status")()
    assert out["authenticated"] is True
    assert out["agency"] == "NULLISLAND"
    assert out["environment"] == "TEST"
    assert out["scope"] == "records inspections"
    assert "access_expires_at" in out
    assert "refresh_expires_at" in out


@pytest.mark.asyncio
async def test_status_refresh_expired(
    settings: Settings,
    loaded_config: LoadedConfig,
    expired_refresh_tokens: Tokens,
    token_store: TokenStore,
) -> None:
    token_store.save(expired_refresh_tokens)
    mcp = _register_auth(settings, loaded_config)
    out = await call(mcp, "accela_auth_status")()
    assert out["authenticated"] is False
    assert out["error"] == "refresh_token_expired"
    assert "accela_login" in out["next_step"]


@pytest.mark.asyncio
async def test_status_decrypt_failure(settings: Settings, loaded_config: LoadedConfig) -> None:
    settings.token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.token_path.write_bytes(b"not a real fernet ciphertext")
    mcp = _register_auth(settings, loaded_config)
    out = await call(mcp, "accela_auth_status")()
    assert out["authenticated"] is False
    assert out["error"] == "token_decrypt_failed"


@pytest.mark.asyncio
async def test_login_persists_tokens(
    settings: Settings,
    loaded_config: LoadedConfig,
    token_store: TokenStore,
) -> None:
    fake_tokens = Tokens(
        access_token="new-access",
        refresh_token="new-refresh",
        scope="records inspections",
        agency="NULLISLAND",
        environment="TEST",
        expires_at=datetime.now(UTC) + timedelta(hours=8),
        refresh_expires_at=datetime.now(UTC) + REFRESH_TOKEN_LIFETIME,
    )

    async def fake_flow(*args: Any, **kwargs: Any) -> Tokens:
        return fake_tokens

    mcp = _register_auth(settings, loaded_config)
    with patch("accela_mcp.tools.auth.run_authorization_code_flow", new=fake_flow):
        out = await call(mcp, "accela_login")(open_browser=False)

    assert out["authenticated"] is True
    assert out["agency"] == "NULLISLAND"
    persisted = token_store.load()
    assert persisted is not None
    assert persisted.access_token == "new-access"


@pytest.mark.asyncio
async def test_login_creates_capabilities_yaml_when_missing(
    settings: Settings,
    fresh_tokens: Tokens,
) -> None:
    # No config loaded — bootstrap-style. Settings.config_path doesn't exist yet.
    assert not settings.config_path.exists()

    async def fake_flow(*args: Any, **kwargs: Any) -> Tokens:
        return fresh_tokens

    mcp = _register_auth(settings, config=None)
    with patch("accela_mcp.tools.auth.run_authorization_code_flow", new=fake_flow):
        out = await call(mcp, "accela_login")(
            agency="NULLISLAND", environment="TEST", open_browser=False
        )

    assert out["authenticated"] is True
    assert out["config_created"] is True
    assert settings.config_path.exists()
    body = settings.config_path.read_text()
    assert "agency: NULLISLAND" in body
    assert "environment: TEST" in body


@pytest.mark.asyncio
async def test_login_requires_agency_when_no_config(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ACCELA_AGENCY", raising=False)
    monkeypatch.delenv("ACCELA_ENVIRONMENT", raising=False)
    mcp = _register_auth(settings, config=None)
    out = await call(mcp, "accela_login")(open_browser=False)
    assert out["error"] == "agency_missing"


@pytest.mark.asyncio
async def test_login_falls_back_to_env_agency(
    settings: Settings,
    fresh_tokens: Tokens,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In bootstrap mode (no config), accela_login should pick up the
    Agency / Environment that the MCPB UI passed via env vars rather than
    forcing the user to repeat them in chat."""
    monkeypatch.setenv("ACCELA_AGENCY", "NULLISLAND")
    monkeypatch.setenv("ACCELA_ENVIRONMENT", "TEST")

    captured: dict[str, str] = {}

    async def fake_flow(s, *, agency, environment, scopes, open_browser):
        captured["agency"] = agency
        captured["environment"] = environment
        return fresh_tokens

    mcp = _register_auth(settings, config=None)
    with patch("accela_mcp.tools.auth.run_authorization_code_flow", new=fake_flow):
        out = await call(mcp, "accela_login")(open_browser=False)

    assert out["authenticated"] is True
    assert captured == {"agency": "NULLISLAND", "environment": "TEST"}


@pytest.mark.asyncio
async def test_login_surfaces_oauth_failure(
    settings: Settings, loaded_config: LoadedConfig
) -> None:
    async def boom(*args: Any, **kwargs: Any) -> Tokens:
        raise OAuthFlowError("port already in use")

    mcp = _register_auth(settings, loaded_config)
    with patch("accela_mcp.tools.auth.run_authorization_code_flow", new=boom):
        out = await call(mcp, "accela_login")(open_browser=False)

    assert out["error"] == "oauth_flow_failed"
    assert "port already in use" in out["message"]


@pytest.mark.asyncio
async def test_login_rejects_blank_app_id(
    tmp_path: Path,
    fernet_key: str,
    loaded_config: LoadedConfig,
) -> None:
    settings = Settings(
        ACCELA_APP_ID="x",  # pydantic min_length=1, so use a placeholder
        ACCELA_APP_SECRET="x",
        ACCELA_REDIRECT_URI="http://localhost:8765/oauth/callback",
        ACCELA_MCP_KEY=fernet_key,
        ACCELA_MCP_CONFIG_PATH=str(tmp_path / "capabilities.yaml"),
        ACCELA_MCP_TOKEN_PATH=str(tmp_path / "tokens.json"),
    )
    # Force the runtime check: we look up the public attr directly. Empty
    # cannot pass pydantic validation, so we sneak a blank in post-construct.
    settings.app_id = ""  # type: ignore[misc]

    mcp = _register_auth(settings, loaded_config)
    out = await call(mcp, "accela_login")(open_browser=False)
    assert out["error"] == "config_missing"
