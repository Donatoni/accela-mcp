from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from accela_mcp.tools import records_write

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register(write_tool_context) -> None:
    mcp = register_module(records_write, write_tool_context)
    assert tool_names(mcp) == {
        "accela_create_record_partial",
        "accela_finalize_record",
        "accela_update_record",
    }


# ----------------------------------------------------------- create_record_partial


@pytest.mark.asyncio
async def test_create_partial_dry_run(write_tool_context) -> None:
    mcp = register_module(records_write, write_tool_context)
    out = await call(mcp, "accela_create_record_partial")(
        record_type="Building/Residential/Alteration/NA",
        description="Small bath remodel",
    )
    assert out["preview"] is True
    assert out["method"] == "POST"
    assert out["query_params"] == {"status": "draft"}
    assert out["body"]["type"]["id"] == "Building-Residential-Alteration-NA"
    assert out["body"]["description"] == "Small bath remodel"


@pytest.mark.asyncio
@respx.mock
async def test_create_partial_confirmed(write_tool_context) -> None:
    route = respx.post("https://apis.test.example/v4/records").mock(
        return_value=Response(
            200,
            json={
                "status": 200,
                "result": [{"id": "ISLANDTON-26CAP-00000-00ABC"}],
            },
        )
    )
    mcp = register_module(records_write, write_tool_context)
    out = await call(mcp, "accela_create_record_partial")(
        record_type="Building/Residential/Alteration/NA",
        confirm=True,
    )
    assert route.called
    assert "status=draft" in str(route.calls.last.request.url)
    assert out["result_id"] == "ISLANDTON-26CAP-00000-00ABC"


@pytest.mark.asyncio
async def test_create_partial_validates(write_tool_context) -> None:
    mcp = register_module(records_write, write_tool_context)
    out = await call(mcp, "accela_create_record_partial")(record_type="")
    assert out["error"] == "invalid_input"


# ---------------------------------------------------------------- finalize_record


@pytest.mark.asyncio
async def test_finalize_dry_run_marks_irreversible(write_tool_context) -> None:
    mcp = register_module(records_write, write_tool_context)
    out = await call(mcp, "accela_finalize_record")(record_id="ISLANDTON-1-2-3")
    assert out["preview"] is True
    assert out["irreversible"] is True
    assert out["method"] == "PUT"
    assert out["body"] == {"recordStatus": {"value": "Submitted"}}


@pytest.mark.asyncio
@respx.mock
async def test_finalize_confirmed(write_tool_context) -> None:
    respx.put("https://apis.test.example/v4/records/ISLANDTON-1-2-3").mock(
        return_value=Response(200, json={"status": 200})
    )
    mcp = register_module(records_write, write_tool_context)
    out = await call(mcp, "accela_finalize_record")(
        record_id="ISLANDTON-1-2-3",
        confirm=True,
    )
    assert out["result_status"] == 200
    assert out["result_id"] == "ISLANDTON-1-2-3"


# ----------------------------------------------------------------- update_record


@pytest.mark.asyncio
async def test_update_dry_run(write_tool_context) -> None:
    mcp = register_module(records_write, write_tool_context)
    out = await call(mcp, "accela_update_record")(
        record_id="ISLANDTON-1-2-3",
        updates={"description": "new description"},
    )
    assert out["preview"] is True
    assert out["body"] == {"description": "new description"}


@pytest.mark.asyncio
async def test_update_validates(write_tool_context) -> None:
    mcp = register_module(records_write, write_tool_context)
    out = await call(mcp, "accela_update_record")(record_id="X", updates={})
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
@respx.mock
async def test_update_confirmed(write_tool_context) -> None:
    route = respx.put("https://apis.test.example/v4/records/ISLANDTON-1-2-3").mock(
        return_value=Response(200, json={"status": 200})
    )
    mcp = register_module(records_write, write_tool_context)
    out = await call(mcp, "accela_update_record")(
        record_id="ISLANDTON-1-2-3",
        updates={"description": "new"},
        confirm=True,
    )
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"description": "new"}
    assert out["result_status"] == 200


@pytest.mark.asyncio
@respx.mock
async def test_update_precondition_fails_when_status_differs(write_tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-1-2-3").mock(
        return_value=Response(
            200,
            json={"result": [{"id": "X", "status": {"value": "Issued"}}]},
        )
    )
    mcp = register_module(records_write, write_tool_context)
    out = await call(mcp, "accela_update_record")(
        record_id="ISLANDTON-1-2-3",
        updates={"description": "x"},
        expected_status="Submitted",
        confirm=True,
    )
    assert out["error"] == "precondition_failed"
    assert out["current_status"] == "Issued"
    assert out["expected_status"] == "Submitted"


@pytest.mark.asyncio
@respx.mock
async def test_update_precondition_passes(write_tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-1-2-3").mock(
        return_value=Response(200, json={"result": [{"status": {"value": "Submitted"}}]})
    )
    respx.put("https://apis.test.example/v4/records/ISLANDTON-1-2-3").mock(
        return_value=Response(200, json={"status": 200})
    )
    mcp = register_module(records_write, write_tool_context)
    out = await call(mcp, "accela_update_record")(
        record_id="ISLANDTON-1-2-3",
        updates={"description": "x"},
        expected_status="Submitted",
        confirm=True,
    )
    assert out["result_status"] == 200


@pytest.mark.asyncio
async def test_kill_switch_off_refuses_writes(tool_context) -> None:
    mcp = register_module(records_write, tool_context)
    out = await call(mcp, "accela_create_record_partial")(
        record_type="Building/Residential/Alteration/NA",
        confirm=True,
    )
    assert out["error"] == "writes_disabled"
