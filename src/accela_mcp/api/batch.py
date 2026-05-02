"""`POST /v4/batch` helper.

Bundles up to N sub-requests into one round trip. The outer request must
carry the auth header (per the docs — without it sub-requests fail with
"Account not found"); the underlying client handles that.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict

from accela_mcp.api.client import AccelaClient

# Accela doesn't publish a hard cap; 50 is a comfortable bound that's still
# meaningfully better than serial calls. Tune via the call site if needed.
DEFAULT_BATCH_SIZE = 50


class SubRequest(TypedDict, total=False):
    method: str
    relativeUrl: str
    headers: dict[str, str]
    body: Any


class SubResponse(TypedDict, total=False):
    status: int
    result: Any
    code: str
    message: str
    traceId: str


def make_sub_request(
    method: str,
    relative_url: str,
    *,
    body: Any = None,
    agency_override: str | None = None,
) -> SubRequest:
    """Build one batch sub-request entry.

    The outer call inherits auth + appid from the request; per-sub headers can
    only override `x-accela-agency` for cross-agency batches (we don't use
    that in v1).
    """
    sub: SubRequest = {
        "method": method.upper(),
        "relativeUrl": relative_url,
    }
    if body is not None:
        sub["body"] = body
    if agency_override:
        sub["headers"] = {"x-accela-agency": agency_override}
    return sub


async def batch(
    client: AccelaClient,
    sub_requests: Sequence[SubRequest],
    *,
    chunk_size: int = DEFAULT_BATCH_SIZE,
) -> list[SubResponse]:
    """Execute a list of sub-requests, chunking past `chunk_size` if needed.

    Returns the flat list of sub-responses in input order. Sub-requests can
    succeed or fail independently — callers must inspect each entry.
    """
    if not sub_requests:
        return []

    out: list[SubResponse] = []
    for chunk in _chunked(sub_requests, chunk_size):
        body = list(chunk)
        response = await client.post("/v4/batch", json=body)
        out.extend(response.get("result") or [])
    return out


async def batch_get(
    client: AccelaClient,
    paths: Sequence[str],
    *,
    chunk_size: int = DEFAULT_BATCH_SIZE,
) -> list[SubResponse]:
    """Convenience: fan out a list of GETs in one batch."""
    sub_requests = [make_sub_request("GET", p) for p in paths]
    return await batch(client, sub_requests, chunk_size=chunk_size)


def split_results(
    sub_responses: Sequence[SubResponse],
) -> tuple[list[SubResponse], list[SubResponse]]:
    """Partition into (successes, failures) based on sub-status."""
    successes: list[SubResponse] = []
    failures: list[SubResponse] = []
    for sub in sub_responses:
        status = int(sub.get("status", 200))
        (failures if status >= 400 else successes).append(sub)
    return successes, failures


def _chunked(seq: Sequence[Any], size: int) -> list[Sequence[Any]]:
    if size <= 0:
        raise ValueError("size must be positive")
    return [seq[i : i + size] for i in range(0, len(seq), size)]


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "SubRequest",
    "SubResponse",
    "batch",
    "batch_get",
    "make_sub_request",
    "split_results",
]
