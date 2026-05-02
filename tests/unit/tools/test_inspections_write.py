from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from accela_mcp.tools import inspections_write

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register(write_tool_context) -> None:
    mcp = register_module(inspections_write, write_tool_context)
    assert tool_names(mcp) == {
        "accela_schedule_inspection",
        "accela_reschedule_inspection",
        "accela_cancel_inspection",
        "accela_result_inspection",
        "accela_assign_inspection",
    }


# ---------------------------------------------------------------------- schedule


@pytest.mark.asyncio
async def test_schedule_dry_run(write_tool_context) -> None:
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_schedule_inspection")(
        record_id="ISLANDTON-1-2-3",
        inspection_type="Initial",
        scheduled_date="2026-06-01",
        scheduled_time="09:00",
        inspector_id="JSMITH",
        request_comment="Please call ahead",
    )
    assert out["preview"] is True
    assert out["method"] == "POST"
    assert out["path"] == "/v4/records/ISLANDTON-1-2-3/inspections"
    assert out["body"]["scheduleDate"] == "2026-06-01"
    assert out["body"]["scheduleStartTime"] == "09:00"
    assert out["body"]["inspectorId"] == "JSMITH"
    assert out["body"]["requestComment"] == "Please call ahead"


@pytest.mark.asyncio
@respx.mock
async def test_schedule_confirmed(write_tool_context) -> None:
    route = respx.post("https://apis.test.example/v4/records/ISLANDTON-1-2-3/inspections").mock(
        return_value=Response(
            200,
            json={"status": 200, "result": [{"id": 999, "type": {"value": "Initial"}}]},
        )
    )
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_schedule_inspection")(
        record_id="ISLANDTON-1-2-3",
        inspection_type="Initial",
        scheduled_date="2026-06-01",
        confirm=True,
    )
    assert route.called
    assert out["result_status"] == 200
    assert out["result_id"] == "999"


@pytest.mark.asyncio
async def test_schedule_validates(write_tool_context) -> None:
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_schedule_inspection")(
        record_id="",
        inspection_type="Initial",
        scheduled_date="2026-06-01",
    )
    assert out["error"] == "invalid_input"


# ------------------------------------------------------------------- reschedule


@pytest.mark.asyncio
async def test_reschedule_dry_run(write_tool_context) -> None:
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_reschedule_inspection")(
        inspection_id="999",
        scheduled_date="2026-06-15",
    )
    assert out["preview"] is True
    assert out["body"]["scheduleDate"] == "2026-06-15"


@pytest.mark.asyncio
@respx.mock
async def test_reschedule_confirmed(write_tool_context) -> None:
    respx.put("https://apis.test.example/v4/inspections/999").mock(
        return_value=Response(200, json={"status": 200, "result": [{"id": 999}]})
    )
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_reschedule_inspection")(
        inspection_id="999",
        scheduled_date="2026-06-15",
        confirm=True,
    )
    assert out["result_status"] == 200
    assert out["result_id"] == "999"


# ----------------------------------------------------------------------- cancel


@pytest.mark.asyncio
async def test_cancel_dry_run_marks_irreversible(write_tool_context) -> None:
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_cancel_inspection")(inspection_id="999")
    assert out["preview"] is True
    assert out["irreversible"] is True


@pytest.mark.asyncio
@respx.mock
async def test_cancel_confirmed(write_tool_context) -> None:
    route = respx.put("https://apis.test.example/v4/inspections/999").mock(
        return_value=Response(200, json={"status": 200, "result": [{"id": 999}]})
    )
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_cancel_inspection")(
        inspection_id="999",
        comment="Owner requested",
        confirm=True,
    )
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent["status"]["value"] == "Cancelled"
    assert sent["comment"] == "Owner requested"
    assert out["result_id"] == "999"


# ----------------------------------------------------------------------- result


@pytest.mark.asyncio
async def test_result_dry_run(write_tool_context) -> None:
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_result_inspection")(
        inspection_id="999",
        result_value="Pass",
        result_comment="All clear",
    )
    assert out["preview"] is True
    assert out["irreversible"] is True
    assert out["body"]["value"] == "Pass"
    assert out["body"]["comment"] == "All clear"


@pytest.mark.asyncio
@respx.mock
async def test_result_confirmed(write_tool_context) -> None:
    respx.put("https://apis.test.example/v4/inspections/999/result").mock(
        return_value=Response(200, json={"status": 200})
    )
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_result_inspection")(
        inspection_id="999",
        result_value="Pass",
        confirm=True,
    )
    assert out["result_status"] == 200
    assert out["result_id"] == "999"


# ----------------------------------------------------------------------- assign


@pytest.mark.asyncio
async def test_assign_dry_run(write_tool_context) -> None:
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_assign_inspection")(
        inspection_id="999",
        inspector_id="JSMITH",
    )
    assert out["preview"] is True
    assert out["body"]["inspectorId"] == "JSMITH"


@pytest.mark.asyncio
@respx.mock
async def test_assign_confirmed(write_tool_context) -> None:
    respx.put("https://apis.test.example/v4/inspections/999").mock(
        return_value=Response(200, json={"status": 200})
    )
    mcp = register_module(inspections_write, write_tool_context)
    out = await call(mcp, "accela_assign_inspection")(
        inspection_id="999",
        inspector_id="JSMITH",
        confirm=True,
    )
    assert out["result_status"] == 200


# ------------------------------------------------------------------- kill switch


@pytest.mark.asyncio
async def test_kill_switch_off_refuses_writes(tool_context) -> None:
    mcp = register_module(inspections_write, tool_context)
    out = await call(mcp, "accela_schedule_inspection")(
        record_id="X",
        inspection_type="Initial",
        scheduled_date="2026-06-01",
        confirm=True,
    )
    assert out["error"] == "writes_disabled"
