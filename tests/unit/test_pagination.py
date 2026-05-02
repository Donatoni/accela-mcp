from __future__ import annotations

from typing import Any

import pytest
import respx
from httpx import Response

from accela_mcp.api.client import AccelaClient
from accela_mcp.api.pagination import auto_paginate_collect, paginate_all


@pytest.mark.asyncio
@respx.mock
async def test_paginates_until_hasmore_false(client: AccelaClient) -> None:
    respx.get("https://apis.test.example/v4/records").mock(
        side_effect=[
            Response(
                200,
                json={
                    "page": {"offset": 0, "limit": 2, "hasmore": True},
                    "result": [{"id": "1"}, {"id": "2"}],
                },
            ),
            Response(
                200,
                json={
                    "page": {"offset": 2, "limit": 2, "hasmore": True},
                    "result": [{"id": "3"}, {"id": "4"}],
                },
            ),
            Response(
                200,
                json={
                    "page": {"offset": 4, "limit": 2, "hasmore": False},
                    "result": [{"id": "5"}],
                },
            ),
        ]
    )
    items = [item async for item in paginate_all(client, "/v4/records", page_size=2)]
    assert [i["id"] for i in items] == ["1", "2", "3", "4", "5"]


@pytest.mark.asyncio
@respx.mock
async def test_pagination_respects_hard_cap(client: AccelaClient) -> None:
    respx.get("https://apis.test.example/v4/records").mock(
        return_value=Response(
            200,
            json={
                "page": {"offset": 0, "limit": 10, "hasmore": True},
                "result": [{"id": str(i)} for i in range(10)],
            },
        )
    )
    items = [item async for item in paginate_all(client, "/v4/records", page_size=10, hard_cap=5)]
    assert len(items) == 5


@pytest.mark.asyncio
@respx.mock
async def test_pagination_stops_on_empty_page(client: AccelaClient) -> None:
    respx.get("https://apis.test.example/v4/records").mock(
        return_value=Response(
            200, json={"page": {"offset": 0, "limit": 10, "hasmore": True}, "result": []}
        )
    )
    items = [item async for item in paginate_all(client, "/v4/records", page_size=10)]
    assert items == []


@pytest.mark.asyncio
async def test_auto_paginate_collect_exits_when_hasmore_false() -> None:
    pages = [
        {"page": {"hasmore": True}, "result": [{"id": "1"}, {"id": "2"}]},
        {"page": {"hasmore": False}, "result": [{"id": "3"}]},
    ]
    calls: list[tuple[int, int]] = []

    async def fetch(off: int, lim: int) -> dict[str, Any]:
        calls.append((off, lim))
        return pages[len(calls) - 1]

    result = await auto_paginate_collect(fetch, page_size=2, max_results=100)
    assert [item["id"] for item in result.items] == ["1", "2", "3"]
    assert result.continuation is None
    assert calls == [(0, 2), (2, 2)]


@pytest.mark.asyncio
async def test_auto_paginate_collect_returns_continuation_at_cap() -> None:
    async def fetch(off: int, lim: int) -> dict[str, Any]:
        return {"page": {"hasmore": True}, "result": [{"id": str(off + i)} for i in range(lim)]}

    result = await auto_paginate_collect(fetch, page_size=10, max_results=25)
    assert len(result.items) == 25
    assert result.continuation == {"next_offset": 25, "max_results_cap": 25}


@pytest.mark.asyncio
async def test_auto_paginate_collect_no_continuation_when_exhausted_at_cap() -> None:
    # Cap exactly matches available results, last page has hasmore=False.
    async def fetch(off: int, lim: int) -> dict[str, Any]:
        return {"page": {"hasmore": False}, "result": [{"id": str(i)} for i in range(lim)]}

    result = await auto_paginate_collect(fetch, page_size=10, max_results=10)
    assert len(result.items) == 10
    assert result.continuation is None


@pytest.mark.asyncio
async def test_auto_paginate_collect_honors_start_offset() -> None:
    starts: list[int] = []

    async def fetch(off: int, lim: int) -> dict[str, Any]:
        starts.append(off)
        return {"page": {"hasmore": False}, "result": [{"id": str(off)}]}

    await auto_paginate_collect(fetch, page_size=10, max_results=100, start_offset=42)
    assert starts == [42]
