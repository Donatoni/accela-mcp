from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from accela_mcp.settings import Settings, ensure_mcp_key, get_settings


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


class TestEnsureMcpKey:
    def _isolate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Path:
        """Point default_env_path at a tmp dir and clear ACCELA_MCP_KEY env."""
        # platformdirs reads XDG_CONFIG_HOME on Linux/macOS; set both for safety.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ACCELA_MCP_KEY", raising=False)

        # Re-import default_env_path so it picks up the patched env.
        from accela_mcp.settings import default_env_path

        return default_env_path()

    def test_generates_when_no_env_no_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_path = self._isolate(tmp_path, monkeypatch)
        assert not env_path.exists()

        ensure_mcp_key()

        assert os.environ["ACCELA_MCP_KEY"]
        # Round-trip through Fernet to confirm the generated value is valid.
        Fernet(os.environ["ACCELA_MCP_KEY"].encode())
        assert env_path.exists()
        assert "ACCELA_MCP_KEY=" in env_path.read_text(encoding="utf-8")

    def test_picks_up_existing_file_when_env_blank(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        env_path = self._isolate(tmp_path, monkeypatch)
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(f'ACCELA_MCP_KEY="{fernet_key}"\n', encoding="utf-8")
        # Simulate the host passing through an empty value.
        monkeypatch.setenv("ACCELA_MCP_KEY", "")

        ensure_mcp_key()

        assert os.environ["ACCELA_MCP_KEY"] == fernet_key

    def test_noop_when_env_already_populated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        self._isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("ACCELA_MCP_KEY", fernet_key)

        ensure_mcp_key()

        # Unchanged
        assert os.environ["ACCELA_MCP_KEY"] == fernet_key

    def test_idempotent_on_repeat(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._isolate(tmp_path, monkeypatch)

        ensure_mcp_key()
        first = os.environ["ACCELA_MCP_KEY"]
        ensure_mcp_key()
        second = os.environ["ACCELA_MCP_KEY"]

        assert first == second
