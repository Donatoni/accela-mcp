"""`accela-mcp` CLI: `auth`, `serve`, `status`."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import click
from cryptography.fernet import Fernet
from pydantic import ValidationError

from accela_mcp import __version__
from accela_mcp.auth.flow import OAuthFlowError, run_authorization_code_flow
from accela_mcp.auth.refresher import (
    RefreshTokenExpiredError,
    introspect,
    refresh_if_needed,
)
from accela_mcp.auth.token_store import TokenStore
from accela_mcp.capabilities import (
    CapabilityConfigError,
    load_capabilities,
    scopes_for,
)
from accela_mcp.observability.logging_config import configure_logging, get_logger
from accela_mcp.server import serve_async
from accela_mcp.settings import Settings, default_env_path, get_settings, settings_env_files

DEFAULT_REDIRECT_URI = "http://localhost:8765/oauth/callback"
DEFAULT_SETUP_GROUPS = {
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
InstallTarget = Literal["both", "claude", "codex", "none"]


def _load_settings_or_die() -> Settings:
    try:
        return get_settings()
    except ValidationError as e:
        click.echo("Configuration error:\n" + str(e), err=True)
        sys.exit(2)


def _default_capabilities_path(env_path: Path | None = None) -> Path:
    base = (env_path or default_env_path()).parent
    return base / "capabilities.yaml"


def _default_token_path(env_path: Path | None = None) -> Path:
    base = (env_path or default_env_path()).parent
    return base / "tokens.json"


def _dotenv_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _backup_file(path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.{stamp}.bak")
    shutil.copy2(path, backup)
    return backup


def _write_setup_env_file(
    path: Path,
    *,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
    mcp_key: str,
    config_path: Path,
    token_path: Path,
    force: bool,
) -> None:
    if (
        path.exists()
        and not force
        and not click.confirm(f"{path} already exists. Replace it?", default=False)
    ):
        raise click.Abort()

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Created by `accela-mcp setup`. Keep this file private.",
        f"ACCELA_APP_ID={_dotenv_quote(app_id)}",
        f"ACCELA_APP_SECRET={_dotenv_quote(app_secret)}",
        f"ACCELA_REDIRECT_URI={_dotenv_quote(redirect_uri)}",
        f"ACCELA_MCP_KEY={_dotenv_quote(mcp_key)}",
        f"ACCELA_MCP_CONFIG_PATH={_dotenv_quote(str(config_path))}",
        f"ACCELA_MCP_TOKEN_PATH={_dotenv_quote(str(token_path))}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)


def _write_capabilities_yaml(
    path: Path,
    *,
    agency: str,
    environment: str,
    force: bool,
) -> bool:
    if (
        path.exists()
        and not force
        and not click.confirm(f"{path} already exists. Replace it?", default=False)
    ):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_default_capabilities_yaml(agency, environment), encoding="utf-8")
    return True


def _default_claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _default_codex_config_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home) / "config.toml"
    return Path.home() / ".codex" / "config.toml"


def _resolve_accela_command() -> str:
    return shutil.which("accela-mcp") or "accela-mcp"


def _write_claude_desktop_config(
    path: Path,
    *,
    env_path: Path,
    command: str,
    force: bool,
) -> Path | None:
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise click.ClickException(
                f"Claude Desktop config at {path} is not valid JSON. "
                "Fix it manually, then rerun setup."
            ) from e
        if not isinstance(config, dict):
            raise click.ClickException(f"Claude Desktop config at {path} must be a JSON object.")
    else:
        config = {}

    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise click.ClickException("Claude Desktop config has non-object `mcpServers`.")

    if (
        "accela" in servers
        and not force
        and not click.confirm("Claude Desktop already has an `accela` MCP server. Replace it?")
    ):
        return None

    servers["accela"] = {
        "command": command,
        "args": ["serve"],
        "env": {
            # This is intentionally not a secret. The secrets stay in the
            # user-level env file created by setup.
            "ACCELA_MCP_ENV_PATH": str(env_path),
        },
    }

    backup: Path | None = None
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = _backup_file(path)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return backup


_TOML_HEADER_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$")


def _remove_toml_sections(text: str, section_names: set[str]) -> str:
    """Remove exact TOML table sections from text, preserving all other text."""
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        match = _TOML_HEADER_RE.match(line)
        if match:
            skipping = match.group(1).strip() in section_names
        if not skipping:
            kept.append(line)
    return "\n".join(kept).rstrip()


def _write_codex_config(
    path: Path,
    *,
    env_path: Path,
    command: str,
    force: bool,
) -> Path | None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    has_accela = "[mcp_servers.accela]" in existing or "[mcp_servers.accela.env]" in existing
    if (
        has_accela
        and not force
        and not click.confirm("Codex already has an `accela` MCP server. Replace it?")
    ):
        return None

    body = _remove_toml_sections(
        existing,
        {"mcp_servers.accela", "mcp_servers.accela.env"},
    )
    accela_block = "\n".join(
        [
            "[mcp_servers.accela]",
            f"command = {_toml_quote(command)}",
            'args = ["serve"]',
            "",
            "[mcp_servers.accela.env]",
            f"ACCELA_MCP_ENV_PATH = {_toml_quote(str(env_path))}",
            "",
        ]
    )

    backup: Path | None = None
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = _backup_file(path)
    new_text = (body + "\n\n" if body else "") + accela_block
    path.write_text(new_text, encoding="utf-8")
    return backup


def _target_includes(target: InstallTarget, app: Literal["claude", "codex"]) -> bool:
    return target == "both" or target == app


@click.group(help="Accela MCP — Model Context Protocol server for the Accela Construct API.")
@click.version_option(__version__, prog_name="accela-mcp")
def cli() -> None:
    pass


@cli.command(help="Guided first-time setup for non-technical users.")
@click.option("--app-id", prompt="Accela App ID", help="Accela Developer Portal app ID.")
@click.option(
    "--app-secret",
    prompt="Accela App Secret",
    hide_input=True,
    help="Accela Developer Portal app secret.",
)
@click.option(
    "--agency",
    prompt="Accela agency",
    default="NULLISLAND",
    show_default=True,
    help="Agency name, e.g. NULLISLAND.",
)
@click.option(
    "--environment",
    prompt="Accela environment",
    default="TEST",
    show_default=True,
    help="Agency environment, e.g. TEST.",
)
@click.option(
    "--redirect-uri",
    prompt="OAuth redirect URI",
    default=DEFAULT_REDIRECT_URI,
    show_default=True,
    help="Must match the redirect URI registered on the Developer Portal.",
)
@click.option("--no-browser", is_flag=True, help="Print the auth URL instead of opening it.")
@click.option(
    "--install-for",
    type=click.Choice(["both", "claude", "codex", "none"], case_sensitive=False),
    default=None,
    help="Which local app config to update. Prompts when omitted.",
)
@click.option(
    "--skip-claude",
    is_flag=True,
    hidden=True,
    help="Do not update Claude Desktop config automatically.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Replace existing Accela MCP setup files and app config entries.",
)
@click.option(
    "--env-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Advanced: path for the private env file.",
)
@click.option(
    "--config-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Advanced: path for capabilities.yaml.",
)
@click.option(
    "--token-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Advanced: path for encrypted tokens.",
)
@click.option(
    "--claude-config-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Advanced: path to Claude Desktop config JSON.",
)
@click.option(
    "--codex-config-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Advanced: path to Codex config TOML.",
)
def setup(
    app_id: str,
    app_secret: str,
    agency: str,
    environment: str,
    redirect_uri: str,
    no_browser: bool,
    install_for: str | None,
    skip_claude: bool,
    force: bool,
    env_path: Path | None,
    config_path: Path | None,
    token_path: Path | None,
    claude_config_path: Path | None,
    codex_config_path: Path | None,
) -> None:
    """Run the guided setup flow and leave the MCP ready for local apps."""
    configure_logging()

    env_path = (env_path or default_env_path()).expanduser()
    config_path = (config_path or _default_capabilities_path(env_path)).expanduser()
    token_path = (token_path or _default_token_path(env_path)).expanduser()
    claude_config_path = (claude_config_path or _default_claude_desktop_config_path()).expanduser()
    codex_config_path = (codex_config_path or _default_codex_config_path()).expanduser()
    if install_for is None:
        install_for = click.prompt(
            "Install MCP config for",
            type=click.Choice(["both", "claude", "codex", "none"], case_sensitive=False),
            default="both",
            show_choices=True,
            show_default=True,
        )
    install_target: InstallTarget = install_for.lower()  # type: ignore[assignment]
    if skip_claude:
        install_target = "codex" if install_target == "both" else "none"
    mcp_key = Fernet.generate_key().decode()

    try:
        settings = Settings(
            ACCELA_APP_ID=app_id,
            ACCELA_APP_SECRET=app_secret,
            ACCELA_REDIRECT_URI=redirect_uri,
            ACCELA_MCP_KEY=mcp_key,
            ACCELA_MCP_CONFIG_PATH=str(config_path),
            ACCELA_MCP_TOKEN_PATH=str(token_path),
        )
    except ValidationError as e:
        click.echo("Configuration error:\n" + str(e), err=True)
        sys.exit(2)

    _write_setup_env_file(
        env_path,
        app_id=app_id,
        app_secret=app_secret,
        redirect_uri=redirect_uri,
        mcp_key=mcp_key,
        config_path=config_path,
        token_path=token_path,
        force=force,
    )
    config_written = _write_capabilities_yaml(
        config_path,
        agency=agency,
        environment=environment,
        force=force,
    )

    scope_list = scopes_for(DEFAULT_SETUP_GROUPS)
    click.echo(f"Requesting scopes: {' '.join(scope_list)}")

    try:
        tokens = asyncio.run(
            run_authorization_code_flow(
                settings,
                agency=agency,
                environment=environment,
                scopes=scope_list,
                open_browser=not no_browser,
            )
        )
    except OAuthFlowError as e:
        click.echo(f"Authentication failed: {e}", err=True)
        click.echo(f"Your setup file was saved at {env_path}. Rerun `accela-mcp setup` to retry.")
        sys.exit(2)

    TokenStore(token_path, mcp_key).save(tokens)

    command = _resolve_accela_command()
    claude_backup: Path | None = None
    codex_backup: Path | None = None
    if _target_includes(install_target, "claude"):
        claude_backup = _write_claude_desktop_config(
            claude_config_path,
            env_path=env_path,
            command=command,
            force=force,
        )
    if _target_includes(install_target, "codex"):
        codex_backup = _write_codex_config(
            codex_config_path,
            env_path=env_path,
            command=command,
            force=force,
        )

    click.echo(
        "\nSetup complete.\n"
        f"  agency:              {tokens.agency}\n"
        f"  environment:         {tokens.environment}\n"
        f"  private setup file:  {env_path}\n"
        f"  token file:          {token_path}\n"
        f"  capabilities:        {config_path}"
        f"{' (written)' if config_written else ' (kept existing)'}\n"
        f"  refresh expires:     {tokens.refresh_expires_at.isoformat()}\n"
    )
    if _target_includes(install_target, "claude"):
        click.echo(f"Claude Desktop config: {claude_config_path}")
        if claude_backup:
            click.echo(f"Claude backup created: {claude_backup}")
    if _target_includes(install_target, "codex"):
        click.echo(f"Codex config:          {codex_config_path}")
        if codex_backup:
            click.echo(f"Codex backup created:  {codex_backup}")
    if install_target == "none":
        click.echo("No app config was changed. Add the MCP server manually when ready.")
    else:
        apps = []
        if _target_includes(install_target, "claude"):
            apps.append("Claude Desktop")
        if _target_includes(install_target, "codex"):
            apps.append("Codex")
        click.echo(f"Restart {' and '.join(apps)}, then look for the Accela tools.")


@cli.command(help="Run the interactive OAuth Authorization Code flow and persist tokens.")
@click.option("--agency", required=True, help="Accela agency name, e.g. NULLISLAND")
@click.option("--environment", required=True, help="Agency environment, e.g. TEST")
@click.option(
    "--scopes",
    default=None,
    help=(
        "Space-separated OAuth scopes. If omitted, the union of scopes for "
        "the enabled capability groups in capabilities.yaml is requested."
    ),
)
@click.option(
    "--no-browser",
    is_flag=True,
    default=False,
    help="Skip auto-opening the browser; print the authorize URL instead.",
)
def auth(agency: str, environment: str, scopes: str | None, no_browser: bool) -> None:
    settings = _load_settings_or_die()
    configure_logging()

    if scopes:
        scope_list = [s for s in scopes.split() if s]
    else:
        try:
            config = load_capabilities(settings.config_path)
            scope_list = config.scopes
        except CapabilityConfigError:
            # No config yet — fall back to a generous union covering the
            # default-on read groups so the operator can finish setup.
            scope_list = scopes_for(
                {
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
            )

    click.echo(f"Requesting scopes: {' '.join(scope_list)}")

    try:
        tokens = asyncio.run(
            run_authorization_code_flow(
                settings,
                agency=agency,
                environment=environment,
                scopes=scope_list,
                open_browser=not no_browser,
            )
        )
    except OAuthFlowError as e:
        click.echo(f"Authentication failed: {e}", err=True)
        sys.exit(2)

    store = TokenStore(settings.token_path, settings.mcp_key.get_secret_value())
    store.save(tokens)

    # Auto-create capabilities.yaml at the configured path if missing, so the
    # operator never has to hunt for the right directory on their platform
    # (macOS: ~/Library/Application Support; Linux/XDG: ~/.config; Windows:
    # %APPDATA%). They can edit it later to opt into more groups.
    config_created = False
    if not settings.config_path.exists():
        settings.config_path.parent.mkdir(parents=True, exist_ok=True)
        settings.config_path.write_text(_default_capabilities_yaml(agency, environment))
        config_created = True

    click.echo(
        "Authentication successful.\n"
        f"  agency:           {tokens.agency}\n"
        f"  environment:      {tokens.environment}\n"
        f"  access expires:   {tokens.expires_at.isoformat()}\n"
        f"  refresh expires:  {tokens.refresh_expires_at.isoformat()}\n"
        f"  token file:       {settings.token_path}\n"
        f"  capabilities:     {settings.config_path}"
        f"{' (created)' if config_created else ''}"
    )


def _default_capabilities_yaml(agency: str, environment: str) -> str:
    """A safe default capabilities.yaml for first-run auto-creation.

    Enables the spec's default-on read groups; no writes, no escape hatch.
    """
    return f"""# Auto-generated by `accela-mcp auth` on first run.
# Edit to enable additional capability groups (records_write,
# inspections_write, payments_*, admin_escape_hatch, ...).
# `discovery` is always on regardless of this list.

version: 1
agency: {agency}
environment: {environment}

enabled_groups:
  - discovery
  - records_read
  - inspections_read
  - documents_read
  - property_read
  - people_read
  - workflow_read
  - fees_read
  - reference_data
  - search
"""


@cli.command(help="Start the MCP server (stdio transport).")
def serve() -> None:
    settings = _load_settings_or_die()
    try:
        # Logging gets fully reconfigured inside `serve_async` based on YAML.
        configure_logging(level=settings.log_level, fmt=settings.log_format)
        asyncio.run(serve_async(settings=settings))
    except CapabilityConfigError as e:
        click.echo(f"Capability config invalid: {e}", err=True)
        sys.exit(2)
    except RefreshTokenExpiredError as e:
        click.echo(str(e), err=True)
        sys.exit(3)
    except KeyboardInterrupt:
        sys.exit(0)


@cli.command(help="Check local setup and print plain-language fixes.")
@click.option(
    "--claude-config-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Advanced: path to Claude Desktop config JSON.",
)
@click.option(
    "--codex-config-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Advanced: path to Codex config TOML.",
)
@click.option(
    "--apps",
    type=click.Choice(["both", "claude", "codex", "none"], case_sensitive=False),
    default="both",
    show_default=True,
    help="Which app configs to check.",
)
@click.option(
    "--online",
    is_flag=True,
    help="Also contact Accela tokeninfo to verify the current access token.",
)
def doctor(
    claude_config_path: Path | None,
    codex_config_path: Path | None,
    apps: str,
    online: bool,
) -> None:
    configure_logging()
    log = get_logger("doctor")
    problems = 0
    app_target: InstallTarget = apps.lower()  # type: ignore[assignment]

    def ok(message: str) -> None:
        click.echo(f"[ok]  {message}")

    def fix(message: str) -> None:
        nonlocal problems
        problems += 1
        click.echo(f"[fix] {message}")

    click.echo("Checking Accela MCP setup...\n")
    click.echo("Settings files checked:")
    for env_file in settings_env_files():
        path = Path(env_file).expanduser()
        click.echo(f"  - {path}{' (found)' if path.exists() else ' (not found)'}")

    try:
        settings = get_settings()
    except ValidationError as e:
        fix("Required settings are missing or invalid. Run `accela-mcp setup`.")
        click.echo(str(e))
        sys.exit(1)

    ok("Required settings loaded.")

    loaded_config = None
    try:
        loaded_config = load_capabilities(settings.config_path)
        ok(f"Capabilities config is valid: {settings.config_path}")
    except CapabilityConfigError as e:
        fix(f"Capabilities config problem: {e}")

    store = TokenStore(settings.token_path, settings.mcp_key.get_secret_value())
    tokens = None
    try:
        tokens = store.load()
    except RuntimeError as e:
        fix(str(e))

    if tokens is None:
        fix(f"No encrypted tokens found at {settings.token_path}. Run `accela-mcp setup`.")
    else:
        ok(f"Encrypted tokens found: {settings.token_path}")
        if tokens.is_refresh_expired:
            fix("Refresh token is expired. Run `accela-mcp setup` or `accela-mcp auth` again.")
        elif tokens.is_refresh_expiring_soon:
            fix(
                "Refresh token expires within 24 hours. Run `accela-mcp auth` soon "
                "to avoid interruption."
            )
        else:
            hours = tokens.seconds_until_refresh_expires() // 3600
            ok(f"Refresh token is valid for about {hours} more hours.")

        if loaded_config:
            if tokens.agency.lower() != loaded_config.capabilities.agency.lower():
                fix(
                    "Token agency does not match capabilities.yaml. "
                    "Run setup again for the desired agency."
                )
            if tokens.environment.lower() != loaded_config.capabilities.environment.lower():
                fix(
                    "Token environment does not match capabilities.yaml. "
                    "Run setup again for the desired environment."
                )

    if _target_includes(app_target, "claude"):
        claude_path = (claude_config_path or _default_claude_desktop_config_path()).expanduser()
        if not claude_path.exists():
            fix(f"Claude Desktop config not found at {claude_path}. Run `accela-mcp setup`.")
        else:
            try:
                claude_config = json.loads(claude_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                fix(f"Claude Desktop config is not valid JSON: {claude_path}")
            else:
                server = (claude_config.get("mcpServers") or {}).get("accela")
                if not isinstance(server, dict):
                    fix("Claude Desktop does not have an `accela` MCP server entry.")
                else:
                    ok("Claude Desktop has an `accela` MCP server entry.")
                    env_path = (server.get("env") or {}).get("ACCELA_MCP_ENV_PATH")
                    if env_path and Path(env_path).expanduser().exists():
                        ok("Claude Desktop points to the private setup file.")
                    elif env_path:
                        fix(f"Claude Desktop points to a missing setup file: {env_path}")

    if _target_includes(app_target, "codex"):
        codex_path = (codex_config_path or _default_codex_config_path()).expanduser()
        if not codex_path.exists():
            fix(f"Codex config not found at {codex_path}. Run `accela-mcp setup`.")
        else:
            text = codex_path.read_text(encoding="utf-8")
            if "[mcp_servers.accela]" not in text:
                fix("Codex does not have an `accela` MCP server entry.")
            else:
                ok("Codex has an `accela` MCP server entry.")
                match = re.search(r'ACCELA_MCP_ENV_PATH\s*=\s*"([^"]+)"', text)
                if match and Path(match.group(1)).expanduser().exists():
                    ok("Codex points to the private setup file.")
                elif match:
                    fix(f"Codex points to a missing setup file: {match.group(1)}")

    if online and tokens is not None:

        async def _online_check() -> dict[str, Any] | None:
            fresh = await refresh_if_needed(tokens, settings, store)
            return await introspect(fresh, settings)

        try:
            info = asyncio.run(_online_check())
        except Exception as e:
            log.warning("doctor_online_check_failed", error=str(e))
            fix(f"Online token check failed: {e}")
        else:
            if info:
                ok(f"Accela tokeninfo responded for user {info.get('userId')}.")
            else:
                fix("Accela tokeninfo rejected the current token. Run `accela-mcp auth`.")

    if problems:
        click.echo(f"\nFound {problems} issue(s).")
        sys.exit(1)

    click.echo("\nEverything looks ready. Restart the configured app(s) if you just ran setup.")


@cli.command(help="Show the current token status and connected agency/environment.")
def status() -> None:
    settings = _load_settings_or_die()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    log = get_logger("status")

    store = TokenStore(settings.token_path, settings.mcp_key.get_secret_value())
    tokens = store.load()
    if tokens is None:
        click.echo(f"No tokens at {settings.token_path}. Run `accela-mcp auth`.")
        sys.exit(1)

    click.echo(
        f"agency:          {tokens.agency}\n"
        f"environment:     {tokens.environment}\n"
        f"access expires:  {tokens.expires_at.isoformat()}\n"
        f"refresh expires: {tokens.refresh_expires_at.isoformat()}"
    )

    if tokens.is_refresh_expired:
        click.echo("\nRefresh token EXPIRED. Run `accela-mcp auth` to re-authenticate.", err=True)
        sys.exit(2)

    if tokens.is_refresh_expiring_soon:
        click.echo(
            f"\nWARNING: refresh token expires in "
            f"{tokens.seconds_until_refresh_expires() // 3600}h."
        )

    # Try a refresh + introspect for a deeper health check, but don't block
    # the user — exit cleanly even if Accela is unreachable.
    async def _check() -> dict[str, Any] | None:
        fresh = await refresh_if_needed(tokens, settings, store)
        return await introspect(fresh, settings)

    try:
        info = asyncio.run(_check())
    except RefreshTokenExpiredError as e:
        click.echo(f"\n{e}", err=True)
        sys.exit(2)
    except Exception as e:
        log.warning("status_introspect_failed", error=str(e))
        click.echo(f"\nNote: introspect call failed ({e}).")
        return

    if info:
        click.echo(
            "\ntoken introspection:\n"
            f"  userId:    {info.get('userId')}\n"
            f"  appId:     {info.get('appId')}\n"
            f"  expiresIn: {info.get('expiresIn')} seconds\n"
            f"  scopes:    {info.get('scopes')}"
        )


def main() -> None:
    """Console-script entry point."""
    cli(prog_name="accela-mcp")


if __name__ == "__main__":
    main()
