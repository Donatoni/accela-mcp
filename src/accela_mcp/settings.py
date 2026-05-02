"""Runtime settings loaded from environment variables.

Secrets and runtime knobs come from the environment via `pydantic-settings`.
Capability toggles come from the YAML config (see `capabilities.py`). The two
layers are intentionally separate so secrets never live in YAML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from platformdirs import user_config_dir
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["json", "console"]


def default_config_dir() -> Path:
    return Path(user_config_dir("accela-mcp"))


def default_env_path() -> Path:
    return default_config_dir() / ".env"


def _default_config_path() -> Path:
    return default_config_dir() / "capabilities.yaml"


def _default_token_path() -> Path:
    return default_config_dir() / "tokens.json"


def settings_env_files() -> tuple[Path | str, ...]:
    """Dotenv files loaded by `get_settings`, in increasing precedence.

    Operators can set ACCELA_MCP_ENV_PATH to point at a custom env file. When
    omitted, we load the user-level setup file first and a repo-local `.env`
    second so developers can override values while working from a checkout.
    """
    override = os.environ.get("ACCELA_MCP_ENV_PATH")
    if override:
        return (Path(override),)
    return (default_env_path(), ".env")


class Settings(BaseSettings):
    """Environment-driven settings.

    Required env vars (no defaults):
        ACCELA_APP_ID, ACCELA_APP_SECRET, ACCELA_REDIRECT_URI, ACCELA_MCP_KEY

    See `.env.example` for documentation on each.
    """

    model_config = SettingsConfigDict(
        env_prefix="ACCELA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Required ---
    app_id: str = Field(..., validation_alias="ACCELA_APP_ID", min_length=1)
    app_secret: SecretStr = Field(..., validation_alias="ACCELA_APP_SECRET")
    redirect_uri: str = Field(..., validation_alias="ACCELA_REDIRECT_URI", min_length=1)
    mcp_key: SecretStr = Field(..., validation_alias="ACCELA_MCP_KEY")

    # --- Optional, with defaults ---
    config_path: Path = Field(
        default_factory=_default_config_path,
        validation_alias="ACCELA_MCP_CONFIG_PATH",
    )
    token_path: Path = Field(
        default_factory=_default_token_path,
        validation_alias="ACCELA_MCP_TOKEN_PATH",
    )
    log_level: LogLevel = Field(default="INFO", validation_alias="ACCELA_MCP_LOG_LEVEL")
    log_format: LogFormat = Field(default="json", validation_alias="ACCELA_MCP_LOG_FORMAT")

    # --- Endpoint constants (overridable for tests / regional deployments) ---
    auth_base_url: str = Field(
        default="https://auth.accela.com", validation_alias="ACCELA_AUTH_BASE_URL"
    )
    api_base_url: str = Field(
        default="https://apis.accela.com", validation_alias="ACCELA_API_BASE_URL"
    )

    @field_validator("redirect_uri")
    @classmethod
    def _redirect_uri_must_be_http(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("ACCELA_REDIRECT_URI must start with http:// or https://")
        return v

    @field_validator("mcp_key")
    @classmethod
    def _mcp_key_must_be_fernet(cls, v: SecretStr) -> SecretStr:
        # Fernet keys are 32 url-safe base64 bytes. Validate at startup so the
        # operator gets an immediate, actionable error instead of a cryptic
        # InvalidToken later.
        try:
            Fernet(v.get_secret_value().encode())
        except Exception as e:
            raise ValueError(
                "ACCELA_MCP_KEY is not a valid Fernet key. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            ) from e
        return v

    @field_validator("auth_base_url", "api_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


def get_settings() -> Settings:
    """Load and return settings. Raises a `pydantic.ValidationError` if a
    required env var is missing or invalid."""
    return Settings(_env_file=settings_env_files())  # type: ignore[call-arg]
