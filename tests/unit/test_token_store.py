from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from accela_mcp.auth.token_store import (
    REFRESH_TOKEN_LIFETIME,
    Tokens,
    TokenStore,
    make_refresh_expiry,
)


def _make_tokens() -> Tokens:
    now = datetime.now(UTC)
    return Tokens(
        access_token="ax",
        refresh_token="rx",
        scope="records",
        agency="NULLISLAND",
        environment="TEST",
        expires_at=now + timedelta(hours=8),
        refresh_expires_at=now + REFRESH_TOKEN_LIFETIME,
        issued_at=now,
    )


class TestTokenStoreRoundtrip:
    def test_save_then_load(self, tmp_path: Path, fernet_key: str) -> None:
        store = TokenStore(tmp_path / "tokens.json", fernet_key)
        original = _make_tokens()
        store.save(original)
        loaded = store.load()
        assert loaded is not None
        assert loaded.access_token == original.access_token
        assert loaded.refresh_token == original.refresh_token
        assert loaded.agency == original.agency

    def test_load_missing_returns_none(self, tmp_path: Path, fernet_key: str) -> None:
        store = TokenStore(tmp_path / "missing.json", fernet_key)
        assert store.load() is None

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
    def test_file_is_mode_0600(self, tmp_path: Path, fernet_key: str) -> None:
        store = TokenStore(tmp_path / "tokens.json", fernet_key)
        store.save(_make_tokens())
        mode = stat.S_IMODE((tmp_path / "tokens.json").stat().st_mode)
        assert mode == 0o600

    def test_atomic_write_no_temp_left_on_success(self, tmp_path: Path, fernet_key: str) -> None:
        store = TokenStore(tmp_path / "tokens.json", fernet_key)
        store.save(_make_tokens())
        leftover = list(tmp_path.glob(".tokens-*.tmp"))
        assert leftover == []

    def test_wrong_key_fails_loud(self, tmp_path: Path, fernet_key: str) -> None:
        good_store = TokenStore(tmp_path / "tokens.json", fernet_key)
        good_store.save(_make_tokens())
        other_key = Fernet.generate_key().decode()
        bad_store = TokenStore(tmp_path / "tokens.json", other_key)
        with pytest.raises(RuntimeError) as exc:
            bad_store.load()
        assert "ACCELA_MCP_KEY" in str(exc.value)

    def test_clear_removes_file(self, tmp_path: Path, fernet_key: str) -> None:
        store = TokenStore(tmp_path / "tokens.json", fernet_key)
        store.save(_make_tokens())
        assert (tmp_path / "tokens.json").exists()
        store.clear()
        assert not (tmp_path / "tokens.json").exists()
        # idempotent
        store.clear()


class TestExpiryProperties:
    def test_is_expiring_soon_true_when_within_window(self) -> None:
        now = datetime.now(UTC)
        t = Tokens(
            access_token="a",
            refresh_token="r",
            scope="records",
            agency="X",
            environment="TEST",
            expires_at=now + timedelta(minutes=2),  # within 5-min proactive window
            refresh_expires_at=now + timedelta(days=5),
            issued_at=now,
        )
        assert t.is_expiring_soon

    def test_is_expiring_soon_false_when_fresh(self) -> None:
        now = datetime.now(UTC)
        t = Tokens(
            access_token="a",
            refresh_token="r",
            scope="records",
            agency="X",
            environment="TEST",
            expires_at=now + timedelta(hours=4),
            refresh_expires_at=now + timedelta(days=5),
            issued_at=now,
        )
        assert not t.is_expiring_soon

    def test_refresh_expired(self) -> None:
        now = datetime.now(UTC)
        t = Tokens(
            access_token="a",
            refresh_token="r",
            scope="records",
            agency="X",
            environment="TEST",
            expires_at=now - timedelta(seconds=10),
            refresh_expires_at=now - timedelta(seconds=1),
            issued_at=now - timedelta(days=8),
        )
        assert t.is_refresh_expired
        assert t.seconds_until_refresh_expires() == 0

    def test_refresh_expiring_soon(self) -> None:
        now = datetime.now(UTC)
        t = Tokens(
            access_token="a",
            refresh_token="r",
            scope="records",
            agency="X",
            environment="TEST",
            expires_at=now + timedelta(hours=4),
            refresh_expires_at=now + timedelta(hours=12),
            issued_at=now - timedelta(days=6),
        )
        assert t.is_refresh_expiring_soon


class TestMakeRefreshExpiry:
    def test_default_now(self) -> None:
        before = datetime.now(UTC)
        expiry = make_refresh_expiry()
        after = datetime.now(UTC)
        assert before + REFRESH_TOKEN_LIFETIME <= expiry <= after + REFRESH_TOKEN_LIFETIME

    def test_specified_now(self) -> None:
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        assert make_refresh_expiry(ts) == ts + REFRESH_TOKEN_LIFETIME
