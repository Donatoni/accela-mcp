"""Helpers for parsing and validating Accela IDs."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Full record ID pattern: {AGENCY}-{YEAR}{MODULE_PREFIX}-{batch}-{seq}
# Agencies are typically uppercase letters/digits; the unique part is mixed.
# Example: ISLANDTON-14CAP-00000-000I4
_RECORD_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]*-[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+$")

# Reject API paths that aren't under /v4/ or contain shenanigans like ..
_SAFE_API_PATH_RE = re.compile(r"^/v4/[A-Za-z0-9._~!$&'()*+,;=:@/\-?]+$")


@dataclass(frozen=True)
class RecordIdParts:
    service_provider_code: str
    unique: str

    @property
    def full(self) -> str:
        return f"{self.service_provider_code}-{self.unique}"


def parse_record_id(record_id: str) -> RecordIdParts:
    """Split a record ID into the agency prefix and the rest.

    Raises `ValueError` if the input doesn't look like a record ID.
    """
    record_id = record_id.strip()
    if not _RECORD_ID_RE.match(record_id):
        raise ValueError(
            f"{record_id!r} doesn't look like an Accela record ID "
            "(expected `AGENCY-YYMOD-BATCH-SEQ`, e.g. `ISLANDTON-14CAP-00000-000I4`)"
        )
    agency, _, rest = record_id.partition("-")
    return RecordIdParts(service_provider_code=agency, unique=rest)


def is_safe_api_path(path: str) -> bool:
    """True if `path` is a /v4/... API path with no traversal sequences.

    Used by `accela_raw_request` to refuse obvious abuse before ever issuing
    the call. `..` segments, leading double-slashes, and non-/v4 prefixes are
    all rejected.
    """
    if not path or not path.startswith("/v4/"):
        return False
    if ".." in path or "//" in path:
        return False
    return bool(_SAFE_API_PATH_RE.match(path))


def join_ids(ids: list[str]) -> str:
    """Comma-join a list of IDs for endpoints like `/v4/records/{ids}`.

    Strips whitespace and rejects empties/duplicates.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        v = (raw or "").strip()
        if not v:
            raise ValueError("ID list contains an empty entry")
        if v in seen:
            continue
        seen.add(v)
        cleaned.append(v)
    if not cleaned:
        raise ValueError("ID list is empty")
    return ",".join(cleaned)
