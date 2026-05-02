"""PII and secret redaction for log events.

Used as a structlog processor and for explicit param scrubbing inside tools.
The list below is conservative — when in doubt, redact.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Keys whose VALUES must never appear in logs in any form.
SECRET_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "client_secret",
        "app_secret",
        "authorization",
        "code",  # OAuth authorization code
        "code_verifier",
        "mcp_key",
        "fernet_key",
        "password",
        "secret",
        "api_key",
        "x-api-key",
    }
)

# Keys whose values are PII — partially mask rather than drop entirely.
PII_KEYS = frozenset(
    {
        "email",
        "phone",
        "ssn",
        "license_number",
        "tax_id",
        "credit_card",
        "first_name",
        "last_name",
    }
)

REDACTED = "***REDACTED***"

_TOKEN_PATTERNS = [
    # Bearer tokens / OAuth-style opaque tokens with `!` separator (Accela)
    re.compile(r"\b[A-Za-z0-9!_\-]{40,}\b"),
]


def _mask_partial(value: str, *, keep: int = 2) -> str:
    if not value:
        return value
    if len(value) <= keep * 2:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep * 2) + value[-keep:]


def _redact_value(key: str, value: Any) -> Any:
    key_lc = key.lower()
    if key_lc in SECRET_KEYS:
        return REDACTED
    if key_lc in PII_KEYS and isinstance(value, str):
        return _mask_partial(value)
    return value


def redact_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of `data` with secret values redacted and PII partly masked.

    Recurses into nested dicts and lists. Non-mapping values are returned as-is
    (modulo the per-key redaction rules above).
    """
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, Mapping):
            out[k] = redact_mapping(v)
        elif isinstance(v, list):
            out[k] = [redact_mapping(x) if isinstance(x, Mapping) else x for x in v]
        else:
            out[k] = _redact_value(k, v)
    return out


def redact_token_strings(text: str) -> str:
    """Best-effort scrub of long opaque tokens in free-form strings.

    Used as a final safety net — explicit per-key redaction in `redact_mapping`
    is the primary mechanism.
    """
    redacted = text
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def redact_event(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor — runs `redact_mapping` over every event."""
    return redact_mapping(event_dict)
