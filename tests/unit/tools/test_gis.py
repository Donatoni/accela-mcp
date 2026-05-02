from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import gis

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register(tool_context) -> None:
    mcp = register_module(gis, tool_context)
    assert tool_names(mcp) == {"accela_geocode", "accela_reverse_geocode"}


@pytest.mark.asyncio
@respx.mock
async def test_geocode(tool_context) -> None:
    route = respx.get("https://apis.test.example/v4/gis/geocode").mock(
        return_value=Response(200, json={"result": [{"latitude": 38.9, "longitude": -77.0}]})
    )
    mcp = register_module(gis, tool_context)
    out = await call(mcp, "accela_geocode")(address="123 Main St")
    assert route.called
    assert out["matches"][0]["latitude"] == 38.9
    sent_url = str(route.calls.last.request.url)
    assert "address=123" in sent_url


@pytest.mark.asyncio
async def test_geocode_requires_input(tool_context) -> None:
    mcp = register_module(gis, tool_context)
    out = await call(mcp, "accela_geocode")()
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
@respx.mock
async def test_reverse_geocode(tool_context) -> None:
    route = respx.get("https://apis.test.example/v4/gis/reverseGeocode").mock(
        return_value=Response(200, json={"result": [{"address": "123 Main St"}]})
    )
    mcp = register_module(gis, tool_context)
    out = await call(mcp, "accela_reverse_geocode")(latitude=38.9, longitude=-77.0)
    assert route.called
    assert out["matches"][0]["address"] == "123 Main St"
