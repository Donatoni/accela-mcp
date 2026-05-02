from __future__ import annotations

from accela_mcp.utils.redaction import (
    REDACTED,
    redact_event,
    redact_mapping,
    redact_token_strings,
)


class TestRedactMapping:
    def test_drops_secret_keys(self) -> None:
        out = redact_mapping(
            {
                "access_token": "abcdefghij" * 5,
                "refresh_token": "abcdefghij" * 5,
                "client_secret": "ssh",
                "agency": "NULLISLAND",
            }
        )
        assert out["access_token"] == REDACTED
        assert out["refresh_token"] == REDACTED
        assert out["client_secret"] == REDACTED
        assert out["agency"] == "NULLISLAND"

    def test_masks_pii(self) -> None:
        out = redact_mapping({"email": "alice@example.com", "phone": "5551234"})
        assert "@" not in out["email"]
        assert "*" in out["email"]
        assert "*" in out["phone"]

    def test_recurses_into_dicts_and_lists(self) -> None:
        out = redact_mapping(
            {
                "headers": {"Authorization": "Bearer xyzxyzxyzxyzxyzxyz"},
                "items": [
                    {"refresh_token": "yyyyyyyyyy" * 5},
                    {"agency": "NULLISLAND"},
                ],
            }
        )
        assert out["headers"]["Authorization"] == REDACTED
        assert out["items"][0]["refresh_token"] == REDACTED
        assert out["items"][1]["agency"] == "NULLISLAND"

    def test_short_pii_fully_masked(self) -> None:
        out = redact_mapping({"email": "a@b"})
        assert out["email"] == "***"

    def test_non_string_pii_left_alone(self) -> None:
        out = redact_mapping({"phone": 5551234})
        assert out["phone"] == 5551234


class TestRedactTokenStrings:
    def test_redacts_long_opaque_token(self) -> None:
        s = "Bearer 3xGDezCgbB3BC4abcdefghijklmnopqrstuvwxyz0123456789"
        assert REDACTED in redact_token_strings(s)

    def test_short_strings_pass_through(self) -> None:
        assert redact_token_strings("hello world") == "hello world"


class TestRedactEvent:
    def test_processes_event_dict(self) -> None:
        out = redact_event(None, "info", {"access_token": "x" * 50, "agency": "NULL"})
        assert out["access_token"] == REDACTED
        assert out["agency"] == "NULL"
