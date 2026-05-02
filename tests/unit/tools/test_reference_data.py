from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import reference_data

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register(tool_context) -> None:
    mcp = register_module(reference_data, tool_context)
    assert tool_names(mcp) == {
        "accela_list_record_types",
        "accela_list_inspection_types",
        "accela_list_record_statuses",
        "accela_list_departments",
        "accela_list_fee_schedules",
    }


@pytest.mark.asyncio
@respx.mock
async def test_list_record_types_filtered(tool_context) -> None:
    respx.get("https://apis.test.example/v4/settings/records/types").mock(
        return_value=Response(200, json={"result": [{"id": "Building-X-Y-Z"}]})
    )
    mcp = register_module(reference_data, tool_context)
    out = await call(mcp, "accela_list_record_types")(module="Building")
    assert out["record_types"][0]["id"] == "Building-X-Y-Z"


@pytest.mark.asyncio
@respx.mock
async def test_results_are_cached_on_second_call(tool_context) -> None:
    route = respx.get("https://apis.test.example/v4/settings/departments").mock(
        return_value=Response(200, json={"result": [{"id": "BLD"}]})
    )
    mcp = register_module(reference_data, tool_context)
    out1 = await call(mcp, "accela_list_departments")()
    out2 = await call(mcp, "accela_list_departments")()
    assert out1 == out2
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_cache_bypass_forces_fresh_fetch(tool_context) -> None:
    route = respx.get("https://apis.test.example/v4/settings/departments").mock(
        return_value=Response(200, json={"result": [{"id": "BLD"}]})
    )
    mcp = register_module(reference_data, tool_context)
    await call(mcp, "accela_list_departments")()
    await call(mcp, "accela_list_departments")(cache_bypass=True)
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_list_inspection_types(tool_context) -> None:
    respx.get("https://apis.test.example/v4/settings/inspections/types").mock(
        return_value=Response(200, json={"result": [{"id": 5, "value": "Final"}]})
    )
    mcp = register_module(reference_data, tool_context)
    out = await call(mcp, "accela_list_inspection_types")(module="Building", group="BLD")
    assert out["inspection_types"][0]["value"] == "Final"


@pytest.mark.asyncio
@respx.mock
async def test_list_record_statuses(tool_context) -> None:
    respx.get("https://apis.test.example/v4/settings/records/statuses").mock(
        return_value=Response(200, json={"result": [{"value": "Submitted"}]})
    )
    mcp = register_module(reference_data, tool_context)
    out = await call(mcp, "accela_list_record_statuses")(module="Building")
    assert out["statuses"][0]["value"] == "Submitted"


@pytest.mark.asyncio
@respx.mock
async def test_list_fee_schedules(tool_context) -> None:
    respx.get("https://apis.test.example/v4/settings/fees").mock(
        return_value=Response(200, json={"result": [{"code": "RES-PERMIT"}]})
    )
    mcp = register_module(reference_data, tool_context)
    out = await call(mcp, "accela_list_fee_schedules")()
    assert out["fee_schedules"][0]["code"] == "RES-PERMIT"
