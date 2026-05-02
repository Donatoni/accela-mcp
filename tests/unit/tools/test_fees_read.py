from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import fees_read

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register(tool_context) -> None:
    mcp = register_module(fees_read, tool_context)
    assert tool_names(mcp) == {
        "accela_list_record_fees",
        "accela_estimate_record_fees",
        "accela_list_record_invoices",
    }


@pytest.mark.asyncio
@respx.mock
async def test_list_record_fees(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-1-2-3/fees").mock(
        return_value=Response(200, json={"result": [{"id": "f1", "amount": 100}]})
    )
    mcp = register_module(fees_read, tool_context)
    out = await call(mcp, "accela_list_record_fees")(record_id="ISLANDTON-1-2-3")
    assert out["fees"] == [{"id": "f1", "amount": 100}]


@pytest.mark.asyncio
@respx.mock
async def test_estimate_record_fees(tool_context) -> None:
    route = respx.put("https://apis.test.example/v4/records/ISLANDTON-1-2-3/fees/estimate").mock(
        return_value=Response(200, json={"result": {"total": 250}})
    )
    mcp = register_module(fees_read, tool_context)
    out = await call(mcp, "accela_estimate_record_fees")(
        record_id="ISLANDTON-1-2-3", fees=[{"code": "BLD-PERMIT"}]
    )
    assert route.called
    assert out["result"]["total"] == 250


@pytest.mark.asyncio
@respx.mock
async def test_list_record_invoices(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-1-2-3/invoices").mock(
        return_value=Response(200, json={"result": [{"id": "inv-1"}]})
    )
    mcp = register_module(fees_read, tool_context)
    out = await call(mcp, "accela_list_record_invoices")(record_id="ISLANDTON-1-2-3")
    assert out["invoices"][0]["id"] == "inv-1"
