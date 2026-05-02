from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import search

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register(tool_context) -> None:
    mcp = register_module(search, tool_context)
    assert tool_names(mcp) == {"accela_global_search"}


@pytest.mark.asyncio
@respx.mock
async def test_global_search(tool_context) -> None:
    route = respx.get("https://apis.test.example/v4/search/global").mock(
        return_value=Response(
            200,
            json={"result": [{"type": "Record", "id": "ISLANDTON-1-2-3"}], "page": {}},
        )
    )
    mcp = register_module(search, tool_context)
    out = await call(mcp, "accela_global_search")(query="Smith")
    assert out["results"][0]["id"] == "ISLANDTON-1-2-3"
    sent = str(route.calls.last.request.url)
    assert "q=Smith" in sent


@pytest.mark.asyncio
async def test_global_search_validates_query(tool_context) -> None:
    mcp = register_module(search, tool_context)
    out = await call(mcp, "accela_global_search")(query="  ")
    assert out["error"] == "invalid_input"
