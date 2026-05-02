from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.api.client import AccelaClient
from accela_mcp.api.pagination import paginate_all


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
