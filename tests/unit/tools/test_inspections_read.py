from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import inspections_read

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register_creates_four_tools(tool_context) -> None:
    mcp = register_module(inspections_read, tool_context)
    assert tool_names(mcp) == {
        "accela_list_inspections_for_record",
        "accela_get_inspection",
        "accela_get_inspection_history",
        "accela_get_inspection_checklists",
    }


@pytest.mark.asyncio
@respx.mock
async def test_list_inspections_for_record(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-1-2-3/inspections").mock(
        return_value=Response(
            200,
            json={
                "result": [{"id": 1}, {"id": 2}],
                "page": {"hasmore": False},
            },
        )
    )
    mcp = register_module(inspections_read, tool_context)
    out = await call(mcp, "accela_list_inspections_for_record")(record_id="ISLANDTON-1-2-3")
    assert out["inspections"] == [{"id": 1}, {"id": 2}]


@pytest.mark.asyncio
@respx.mock
async def test_get_inspection_joins_ids(tool_context) -> None:
    route = respx.get("https://apis.test.example/v4/inspections/1,2,3").mock(
        return_value=Response(200, json={"result": [{"id": 1}, {"id": 2}, {"id": 3}]})
    )
    mcp = register_module(inspections_read, tool_context)
    out = await call(mcp, "accela_get_inspection")(inspection_ids=["1", "2", "3"])
    assert route.called
    assert len(out["inspections"]) == 3


@pytest.mark.asyncio
async def test_get_inspection_empty_list_validates(tool_context) -> None:
    mcp = register_module(inspections_read, tool_context)
    out = await call(mcp, "accela_get_inspection")(inspection_ids=[])
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
@respx.mock
async def test_get_inspection_history(tool_context) -> None:
    respx.get("https://apis.test.example/v4/inspections/1/histories").mock(
        return_value=Response(200, json={"result": [{"event": "scheduled"}]})
    )
    mcp = register_module(inspections_read, tool_context)
    out = await call(mcp, "accela_get_inspection_history")(inspection_ids=["1"])
    assert out["history"] == [{"event": "scheduled"}]


@pytest.mark.asyncio
@respx.mock
async def test_get_inspection_checklists_with_items(tool_context) -> None:
    respx.get("https://apis.test.example/v4/inspections/1/checklists").mock(
        return_value=Response(
            200,
            json={"result": [{"id": "cl1", "name": "Final"}]},
        )
    )
    respx.get("https://apis.test.example/v4/inspections/1/checklists/cl1/items").mock(
        return_value=Response(
            200,
            json={"result": [{"id": "i1", "status": "Pass"}]},
        )
    )
    mcp = register_module(inspections_read, tool_context)
    out = await call(mcp, "accela_get_inspection_checklists")(inspection_id="1")
    assert out["checklists"][0]["items"] == [{"id": "i1", "status": "Pass"}]


@pytest.mark.asyncio
@respx.mock
async def test_get_inspection_checklists_partial_failure(tool_context) -> None:
    respx.get("https://apis.test.example/v4/inspections/1/checklists").mock(
        return_value=Response(
            200,
            json={"result": [{"id": "cl1"}, {"id": "cl2"}]},
        )
    )
    respx.get("https://apis.test.example/v4/inspections/1/checklists/cl1/items").mock(
        return_value=Response(200, json={"result": [{"id": "i1"}]})
    )
    respx.get("https://apis.test.example/v4/inspections/1/checklists/cl2/items").mock(
        return_value=Response(500, json={"code": "x", "message": "boom"})
    )

    mcp = register_module(inspections_read, tool_context)
    out = await call(mcp, "accela_get_inspection_checklists")(inspection_id="1")
    assert out["checklists"][0]["items"] == [{"id": "i1"}]
    # cl2 surfaced as a structured error.
    assert isinstance(out["checklists"][1]["items"], dict)
    assert out["checklists"][1]["items"]["error"] == "fetch_failed"
