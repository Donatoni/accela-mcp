from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import payments_read

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register(tool_context) -> None:
    mcp = register_module(payments_read, tool_context)
    assert tool_names(mcp) == {"accela_list_record_payments"}


@pytest.mark.asyncio
@respx.mock
async def test_list_payments(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-1-2-3/payments").mock(
        return_value=Response(200, json={"result": [{"id": 1, "amount": 99.5}]})
    )
    mcp = register_module(payments_read, tool_context)
    out = await call(mcp, "accela_list_record_payments")(record_id="ISLANDTON-1-2-3")
    assert out["payments"] == [{"id": 1, "amount": 99.5}]


@pytest.mark.asyncio
async def test_validates(tool_context) -> None:
    mcp = register_module(payments_read, tool_context)
    out = await call(mcp, "accela_list_record_payments")(record_id="")
    assert out["error"] == "invalid_input"
