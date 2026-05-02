from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import property_read

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register_creates_four_tools(tool_context) -> None:
    mcp = register_module(property_read, tool_context)
    assert tool_names(mcp) == {
        "accela_get_address",
        "accela_search_addresses",
        "accela_get_parcel",
        "accela_get_owners_for_parcel",
    }


@pytest.mark.asyncio
@respx.mock
async def test_get_address(tool_context) -> None:
    respx.get("https://apis.test.example/v4/addresses/100").mock(
        return_value=Response(200, json={"result": [{"id": 100, "city": "Petaluma"}]})
    )
    mcp = register_module(property_read, tool_context)
    out = await call(mcp, "accela_get_address")(address_id="100")
    assert out["city"] == "Petaluma"


@pytest.mark.asyncio
@respx.mock
async def test_get_address_not_found(tool_context) -> None:
    respx.get("https://apis.test.example/v4/addresses/100").mock(
        return_value=Response(200, json={"result": []})
    )
    mcp = register_module(property_read, tool_context)
    out = await call(mcp, "accela_get_address")(address_id="100")
    assert out["error"] == "not_found"


@pytest.mark.asyncio
@respx.mock
async def test_search_addresses(tool_context) -> None:
    route = respx.post("https://apis.test.example/v4/search/addresses").mock(
        return_value=Response(
            200,
            json={"result": [{"id": 1}], "page": {"hasmore": False}},
        )
    )
    mcp = register_module(property_read, tool_context)
    out = await call(mcp, "accela_search_addresses")(city="Petaluma", state="CA")
    assert route.called
    assert out["addresses"] == [{"id": 1}]
    body = route.calls.last.request.read()
    assert b"Petaluma" in body
    assert b"CA" in body


@pytest.mark.asyncio
async def test_search_addresses_requires_at_least_one_field(tool_context) -> None:
    mcp = register_module(property_read, tool_context)
    out = await call(mcp, "accela_search_addresses")()
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
@respx.mock
async def test_get_parcel(tool_context) -> None:
    respx.get("https://apis.test.example/v4/parcels/abc").mock(
        return_value=Response(200, json={"result": [{"id": "abc"}]})
    )
    mcp = register_module(property_read, tool_context)
    out = await call(mcp, "accela_get_parcel")(parcel_id="abc")
    assert out["id"] == "abc"


@pytest.mark.asyncio
async def test_get_parcel_rejects_unknown_expand(tool_context) -> None:
    mcp = register_module(property_read, tool_context)
    out = await call(mcp, "accela_get_parcel")(parcel_id="abc", expand=["nope"])
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
@respx.mock
async def test_get_owners_for_parcel(tool_context) -> None:
    respx.get("https://apis.test.example/v4/parcels/abc/owners").mock(
        return_value=Response(200, json={"result": [{"name": "Doe"}]})
    )
    mcp = register_module(property_read, tool_context)
    out = await call(mcp, "accela_get_owners_for_parcel")(parcel_id="abc")
    assert out["owners"][0]["name"] == "Doe"
