"""Helpers for offset/limit pagination loops.

Tools default to **NOT** auto-paginating — they expose `limit`/`offset` and
let the LLM iterate. Use `paginate_all` only when a tool semantically wants
all results (e.g., listing every document on a record, where the LLM should
not have to count pages itself).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

from accela_mcp.api.client import AccelaClient

# The Accela-published max page size for search endpoints (agency users).
SEARCH_MAX_PAGE = 100
# Soft cap on auto-pagination so we never hammer the API on a runaway list.
DEFAULT_AUTO_PAGINATE_HARD_CAP = 1000


async def paginate_all(
    client: AccelaClient,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    page_size: int = SEARCH_MAX_PAGE,
    hard_cap: int = DEFAULT_AUTO_PAGINATE_HARD_CAP,
) -> AsyncIterator[dict[str, Any]]:
    """Async-iterate every item across pages of a paginated endpoint.

    Uses Accela's `page.hasmore` envelope (lowercase). Stops when:
      * hasmore is false / missing
      * we've yielded `hard_cap` items (safety valve)
      * the API returns an empty page
    """
    params = dict(params or {})
    offset = int(params.get("offset", 0))
    limit = int(params.get("limit", page_size))
    yielded = 0

    while True:
        params["offset"] = offset
        params["limit"] = limit
        response = await client.get(path, params=params)
        items = response.get("result") or []
        for item in items:
            if yielded >= hard_cap:
                return
            yielded += 1
            yield item

        page = response.get("page") or {}
        if not page.get("hasmore") or not items:
            return
        offset += limit


__all__ = [
    "DEFAULT_AUTO_PAGINATE_HARD_CAP",
    "SEARCH_MAX_PAGE",
    "paginate_all",
]
