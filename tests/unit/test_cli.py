from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from accela_mcp.auth.token_store import Tokens, TokenStore
from accela_mcp.cli import cli


def _env(fernet_key: str, **overrides: str) -> dict[str, str]:
    base = {
        "ACCELA_APP_ID": "abc",
        "ACCELA_APP_SECRET": "shh",
        "ACCELA_REDIRECT_URI": "http://localhost:8765/oauth/callback",
        "ACCELA_MCP_KEY": fernet_key,
    }
    base.update(overrides)
    return base


class TestStatus:
    def test_no_tokens_exits_1(self, tmp_path: Path, fernet_key: str) -> None:
        env = _env(
            fernet_key,
            ACCELA_MCP_TOKEN_PATH=str(tmp_path / "tokens.json"),
            ACCELA_MCP_CONFIG_PATH=str(tmp_path / "capabilities.yaml"),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["status"], env=env)
        assert result.exit_code == 1
        assert "No tokens" in result.output

    def test_expired_refresh_exits_2(
        self,
        tmp_path: Path,
        fernet_key: str,
        expired_refresh_tokens: Tokens,
    ) -> None:
        store_path = tmp_path / "tokens.json"
        TokenStore(store_path, fernet_key).save(expired_refresh_tokens)
        env = _env(
            fernet_key,
            ACCELA_MCP_TOKEN_PATH=str(store_path),
            ACCELA_MCP_CONFIG_PATH=str(tmp_path / "capabilities.yaml"),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["status"], env=env)
        assert result.exit_code == 2
        assert "EXPIRED" in result.output


class TestVersion:
    def test_version_flag(self, fernet_key: str) -> None:
        runner = CliRunner()
        # Version command doesn't need full env.
        result = runner.invoke(cli, ["--version"], env=_env(fernet_key))
        assert result.exit_code == 0
        assert "accela-mcp" in result.output


class TestSetup:
    def test_setup_creates_files_and_claude_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_flow(settings, *, agency, environment, scopes, open_browser):
            assert settings.app_id == "abc"
            assert agency == "DELAND"
            assert environment == "TEST"
            assert "records" in scopes
            assert open_browser is False
            now = datetime.now(UTC)
            return Tokens(
                access_token="access",
                refresh_token="refresh",
                scope=" ".join(scopes),
                agency=agency,
                environment=environment,
                expires_at=now + timedelta(hours=8),
                refresh_expires_at=now + timedelta(days=7),
                issued_at=now,
            )

        monkeypatch.setattr("accela_mcp.cli.run_authorization_code_flow", fake_flow)

        env_path = tmp_path / "setup.env"
        config_path = tmp_path / "capabilities.yaml"
        token_path = tmp_path / "tokens.json"
        claude_path = tmp_path / "claude_desktop_config.json"
        codex_path = tmp_path / "codex_config.toml"

        result = CliRunner().invoke(
            cli,
            [
                "setup",
                "--app-id",
                "abc",
                "--app-secret",
                "shh",
                "--agency",
                "DELAND",
                "--environment",
                "TEST",
                "--redirect-uri",
                "http://localhost:8765/oauth/callback",
                "--no-browser",
                "--install-for",
                "both",
                "--force",
                "--env-path",
                str(env_path),
                "--config-path",
                str(config_path),
                "--token-path",
                str(token_path),
                "--claude-config-path",
                str(claude_path),
                "--codex-config-path",
                str(codex_path),
            ],
            env={},
        )

        assert result.exit_code == 0, result.output
        assert "Setup complete" in result.output
        assert "shh" not in result.output

        env_text = env_path.read_text()
        assert 'ACCELA_APP_ID="abc"' in env_text
        assert 'ACCELA_APP_SECRET="shh"' in env_text
        assert f'ACCELA_MCP_CONFIG_PATH="{config_path}"' in env_text

        assert "agency: DELAND" in config_path.read_text()
        assert token_path.exists()

        claude = json.loads(claude_path.read_text())
        server = claude["mcpServers"]["accela"]
        assert server["args"] == ["serve"]
        assert server["env"] == {"ACCELA_MCP_ENV_PATH": str(env_path)}
        assert "ACCELA_APP_SECRET" not in claude_path.read_text()

        codex_text = codex_path.read_text()
        assert "[mcp_servers.accela]" in codex_text
        assert 'args = ["serve"]' in codex_text
        assert f'ACCELA_MCP_ENV_PATH = "{env_path}"' in codex_text
        assert "ACCELA_APP_SECRET" not in codex_text

    def test_setup_can_install_for_codex_only(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_flow(settings, *, agency, environment, scopes, open_browser):
            now = datetime.now(UTC)
            return Tokens(
                access_token="access",
                refresh_token="refresh",
                scope=" ".join(scopes),
                agency=agency,
                environment=environment,
                expires_at=now + timedelta(hours=8),
                refresh_expires_at=now + timedelta(days=7),
                issued_at=now,
            )

        monkeypatch.setattr("accela_mcp.cli.run_authorization_code_flow", fake_flow)
        env_path = tmp_path / "setup.env"
        claude_path = tmp_path / "claude_desktop_config.json"
        codex_path = tmp_path / "codex_config.toml"

        result = CliRunner().invoke(
            cli,
            [
                "setup",
                "--app-id",
                "abc",
                "--app-secret",
                "shh",
                "--agency",
                "DELAND",
                "--environment",
                "TEST",
                "--redirect-uri",
                "http://localhost:8765/oauth/callback",
                "--no-browser",
                "--install-for",
                "codex",
                "--force",
                "--env-path",
                str(env_path),
                "--claude-config-path",
                str(claude_path),
                "--codex-config-path",
                str(codex_path),
            ],
            env={},
        )
        assert result.exit_code == 0, result.output
        assert not claude_path.exists()
        assert "[mcp_servers.accela]" in codex_path.read_text()

    def test_doctor_accepts_setup_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_flow(settings, *, agency, environment, scopes, open_browser):
            now = datetime.now(UTC)
            return Tokens(
                access_token="access",
                refresh_token="refresh",
                scope=" ".join(scopes),
                agency=agency,
                environment=environment,
                expires_at=now + timedelta(hours=8),
                refresh_expires_at=now + timedelta(days=7),
                issued_at=now,
            )

        monkeypatch.setattr("accela_mcp.cli.run_authorization_code_flow", fake_flow)
        env_path = tmp_path / "setup.env"
        claude_path = tmp_path / "claude_desktop_config.json"
        codex_path = tmp_path / "codex_config.toml"
        config_path = tmp_path / "capabilities.yaml"
        token_path = tmp_path / "tokens.json"

        setup_result = CliRunner().invoke(
            cli,
            [
                "setup",
                "--app-id",
                "abc",
                "--app-secret",
                "shh",
                "--agency",
                "DELAND",
                "--environment",
                "TEST",
                "--redirect-uri",
                "http://localhost:8765/oauth/callback",
                "--no-browser",
                "--install-for",
                "both",
                "--force",
                "--env-path",
                str(env_path),
                "--config-path",
                str(config_path),
                "--token-path",
                str(token_path),
                "--claude-config-path",
                str(claude_path),
                "--codex-config-path",
                str(codex_path),
            ],
            env={},
        )
        assert setup_result.exit_code == 0, setup_result.output

        doctor_result = CliRunner().invoke(
            cli,
            [
                "doctor",
                "--claude-config-path",
                str(claude_path),
                "--codex-config-path",
                str(codex_path),
            ],
            env={"ACCELA_MCP_ENV_PATH": str(env_path)},
        )
        assert doctor_result.exit_code == 0, doctor_result.output
        assert "Everything looks ready" in doctor_result.output


class TestServeMissingConfig:
    def test_missing_capabilities_yaml_enters_bootstrap_mode(
        self, tmp_path: Path, fernet_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing capabilities.yaml is no longer fatal — `serve` falls into
        bootstrap mode so the user can run accela_login from chat. We patch
        run_stdio_async so the test doesn't actually block on stdin."""
        env = _env(
            fernet_key,
            ACCELA_MCP_TOKEN_PATH=str(tmp_path / "tokens.json"),
            ACCELA_MCP_CONFIG_PATH=str(tmp_path / "capabilities.yaml"),
        )

        async def fake_stdio(self) -> None:  # type: ignore[no-untyped-def]
            return None

        monkeypatch.setattr("mcp.server.fastmcp.FastMCP.run_stdio_async", fake_stdio)

        runner = CliRunner()
        result = runner.invoke(cli, ["serve"], env=env)
        assert result.exit_code == 0, result.output

    def test_malformed_capabilities_yaml_exits_2(self, tmp_path: Path, fernet_key: str) -> None:
        """A *malformed* capabilities.yaml is still fatal — that's a real
        misconfiguration, not a first-run state."""
        cfg_path = tmp_path / "capabilities.yaml"
        cfg_path.write_text(":\nthis: [is broken")
        env = _env(
            fernet_key,
            ACCELA_MCP_TOKEN_PATH=str(tmp_path / "tokens.json"),
            ACCELA_MCP_CONFIG_PATH=str(cfg_path),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["serve"], env=env)
        assert result.exit_code == 2
        assert "capabilities" in result.output.lower()
