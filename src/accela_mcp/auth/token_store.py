"""Encrypted token persistence.

The token file is Fernet-encrypted with a key derived from `ACCELA_MCP_KEY`.
On Unix it's mode 0600. On Windows we rely on the per-user `%APPDATA%`
directory ACL for isolation — Fernet encryption is the primary defense.
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field

# Accela's documented refresh-token validity window.
REFRESH_TOKEN_LIFETIME = timedelta(days=7)
ACCESS_TOKEN_NEAR_EXPIRY = timedelta(minutes=5)
REFRESH_TOKEN_NEAR_EXPIRY = timedelta(hours=24)


class Tokens(BaseModel):
    """Persisted OAuth token bundle for a single (agency, environment).

    `expires_at` and `refresh_expires_at` are absolute timestamps so we don't
    need to remember when the file was last written.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth field name; not a credential
    scope: str
    agency: str
    environment: str
    expires_at: datetime
    refresh_expires_at: datetime
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_expiring_soon(self) -> bool:
        """True if access token will expire within the proactive-refresh window."""
        return self.expires_at - datetime.now(UTC) < ACCESS_TOKEN_NEAR_EXPIRY

    @property
    def is_refresh_expiring_soon(self) -> bool:
        """True if refresh token expires within the next 24 hours."""
        return self.refresh_expires_at - datetime.now(UTC) < REFRESH_TOKEN_NEAR_EXPIRY

    @property
    def is_refresh_expired(self) -> bool:
        return datetime.now(UTC) >= self.refresh_expires_at

    def seconds_until_refresh_expires(self) -> int:
        return max(0, int((self.refresh_expires_at - datetime.now(UTC)).total_seconds()))


class TokenStore:
    """Encrypted on-disk token bundle.

    Encryption is Fernet (AES-128-CBC + HMAC-SHA256). The Fernet key is
    sourced from the `ACCELA_MCP_KEY` env var via `Settings`.
    """

    def __init__(self, path: Path, key: str) -> None:
        self.path = Path(path)
        # Validation already happened in Settings; we trust the key here.
        self.fernet = Fernet(key.encode())

    def save(self, tokens: Tokens) -> None:
        """Atomically encrypt and write the token bundle."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        ciphertext = self.fernet.encrypt(tokens.model_dump_json().encode("utf-8"))

        # Atomic write via a temp file in the same directory, then rename.
        # Avoids leaving a half-written or world-readable file behind.
        fd, tmp_name = tempfile.mkstemp(prefix=".tokens-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(ciphertext)
            if os.name != "nt":
                os.chmod(tmp_name, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp_name, self.path)
        except Exception:
            # Best-effort cleanup of the temp file on failure.
            try:
                Path(tmp_name).unlink(missing_ok=True)
            finally:
                raise

        # Some platforms reset perms on replace; reassert just in case.
        if os.name != "nt":
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)

    def load(self) -> Tokens | None:
        if not self.path.exists():
            return None
        try:
            plaintext = self.fernet.decrypt(self.path.read_bytes())
        except InvalidToken as e:
            raise RuntimeError(
                f"Failed to decrypt token file at {self.path}. "
                "This usually means ACCELA_MCP_KEY changed since the tokens "
                "were saved. Run `accela-mcp auth` to re-authenticate."
            ) from e
        return Tokens.model_validate_json(plaintext)

    def clear(self) -> None:
        """Remove the on-disk token file. Safe if it doesn't exist."""
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


def make_refresh_expiry(now: datetime | None = None) -> datetime:
    """Compute the refresh-token expiry timestamp (now + 7 days)."""
    return (now or datetime.now(UTC)) + REFRESH_TOKEN_LIFETIME


__all__ = [
    "ACCESS_TOKEN_NEAR_EXPIRY",
    "REFRESH_TOKEN_LIFETIME",
    "REFRESH_TOKEN_NEAR_EXPIRY",
    "TokenStore",
    "Tokens",
    "make_refresh_expiry",
]
