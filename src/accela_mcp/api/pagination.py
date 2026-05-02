"""Helpers for offset/limit pagination loops.

Two helpers are exposed:

* `paginate_all` — async iterator over every item across pages of a GET
  endpoint. Use when a tool semantically wants every result (e.g., listing
  every document on a record).
* `auto_paginate_collect` — collects pages from a fetcher callable up to a
  `max_results` soft cap and returns a structured result with continuation
  info. Use for search tools where the LLM should auto-paginate up to a
  cap and then surface a continuation cursor for the user to confirm
  before going further.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True)
class AutoPaginateResult:
    """Structured result for `auto_paginate_collect`.

    `continuation` is non-None only when the cap was hit while more results
    were still available — the LLM should surface this to the user and ask
    whether to continue.
    """

    items: list[dict[str, Any]]
    last_page: dict[str, Any]
    continuation: dict[str, Any] | None


async def auto_paginate_collect(
    fetch_page: Callable[[int, int], Awaitable[dict[str, Any]]],
    *,
    page_size: int = SEARCH_MAX_PAGE,
    max_results: int = DEFAULT_AUTO_PAGINATE_HARD_CAP,
    start_offset: int = 0,
) -> AutoPaginateResult:
    """Loop `fetch_page(offset, limit)` until exhausted or `max_results`.

    Each call to `fetch_page` must return a parsed Accela response with
    `result` (list) and `page` (envelope with `hasmore`). The helper:

    * walks pages of `page_size`, advancing offset by the requested limit
    * stops when `page.hasmore` is false, the page is empty, or we've
      collected `max_results` items
    * returns a continuation cursor if we stopped at the cap with
      more results still available
    """
    items: list[dict[str, Any]] = []
    last_page: dict[str, Any] = {}
    offset = start_offset

    while len(items) < max_results:
        remaining = max_results - len(items)
        limit = min(page_size, remaining)
        response = await fetch_page(offset, limit)
        page_items = response.get("result") or []
        last_page = response.get("page") or {}
        # Trim defensively in case the API returns more than requested
        # (rare, but keeps `max_results` an honest cap).
        items.extend(page_items[:remaining])
        if not last_page.get("hasmore") or not page_items:
            return AutoPaginateResult(items=items, last_page=last_page, continuation=None)
        offset += limit

    if last_page.get("hasmore"):
        return AutoPaginateResult(
            items=items,
            last_page=last_page,
            continuation={"next_offset": offset, "max_results_cap": max_results},
        )
    return AutoPaginateResult(items=items, last_page=last_page, continuation=None)


__all__ = [
    "DEFAULT_AUTO_PAGINATE_HARD_CAP",
    "SEARCH_MAX_PAGE",
    "AutoPaginateResult",
    "auto_paginate_collect",
    "paginate_all",
]
