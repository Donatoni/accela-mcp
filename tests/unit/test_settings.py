from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from accela_mcp.settings import Settings, get_settings


class TestSettings:
    def test_minimal_valid_construction(self, fernet_key: str) -> None:
        s = Settings(
            ACCELA_APP_ID="abc",
            ACCELA_APP_SECRET="shh",
            ACCELA_REDIRECT_URI="http://localhost:8765/oauth/callback",
            ACCELA_MCP_KEY=fernet_key,
        )
        assert s.app_id == "abc"
        assert s.app_secret.get_secret_value() == "shh"
        assert s.redirect_uri.startswith("http://")
        assert s.auth_base_url == "https://auth.accela.com"
        assert s.api_base_url == "https://apis.accela.com"

    def test_missing_required_fails(self) -> None:
        # Pass `_env_file=None` to bypass any local `.env` file the developer
        # may have for actual use.
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_invalid_redirect_uri_fails(self, fernet_key: str) -> None:
        with pytest.raises(ValidationError):
            Settings(
                ACCELA_APP_ID="abc",
                ACCELA_APP_SECRET="shh",
                ACCELA_REDIRECT_URI="ftp://localhost",
                ACCELA_MCP_KEY=fernet_key,
            )

    def test_invalid_fernet_key_fails(self) -> None:
        with pytest.raises(ValidationError) as exc:
            Settings(
                ACCELA_APP_ID="abc",
                ACCELA_APP_SECRET="shh",
                ACCELA_REDIRECT_URI="http://localhost:8765/cb",
                ACCELA_MCP_KEY="not-a-real-fernet-key",
            )
        assert "Fernet" in str(exc.value)

    def test_trailing_slash_stripped_from_base_urls(self, fernet_key: str) -> None:
        s = Settings(
            ACCELA_APP_ID="abc",
            ACCELA_APP_SECRET="shh",
            ACCELA_REDIRECT_URI="http://localhost:8765/cb",
            ACCELA_MCP_KEY=fernet_key,
            ACCELA_AUTH_BASE_URL="https://auth.accela.com/",
            ACCELA_API_BASE_URL="https://apis.accela.com/",
        )
        assert s.auth_base_url == "https://auth.accela.com"
        assert s.api_base_url == "https://apis.accela.com"

    def test_get_settings_reads_user_env_path(
        self,
        tmp_path: Path,
        fernet_key: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_path = tmp_path / "setup.env"
        env_path.write_text(
            "\n".join(
                [
                    'ACCELA_APP_ID="abc"',
                    'ACCELA_APP_SECRET="shh"',
                    'ACCELA_REDIRECT_URI="http://localhost:8765/cb"',
                    f'ACCELA_MCP_KEY="{fernet_key}"',
                ]
            )
        )
        monkeypatch.setenv("ACCELA_MCP_ENV_PATH", str(env_path))

        s = get_settings()
        assert s.app_id == "abc"
        assert s.redirect_uri == "http://localhost:8765/cb"
