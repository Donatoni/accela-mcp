from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from accela_mcp.tools import workflow_write

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register(write_tool_context) -> None:
    mcp = register_module(workflow_write, write_tool_context)
    assert tool_names(mcp) == {"accela_update_workflow_task"}


@pytest.mark.asyncio
async def test_dry_run_returns_preview(write_tool_context) -> None:
    mcp = register_module(workflow_write, write_tool_context)
    out = await call(mcp, "accela_update_workflow_task")(
        record_id="ISLANDTON-1-2-3",
        task_id="42",
        status="Approved",
    )
    assert out["preview"] is True
    assert out["confirmation_required"] is True
    assert out["method"] == "PUT"
    assert out["path"] == "/v4/records/ISLANDTON-1-2-3/workflowTasks"
    assert out["body"][0]["id"] == "42"
    assert out["body"][0]["status"]["value"] == "Approved"


@pytest.mark.asyncio
async def test_dry_run_includes_optional_fields(write_tool_context) -> None:
    mcp = register_module(workflow_write, write_tool_context)
    out = await call(mcp, "accela_update_workflow_task")(
        record_id="ISLANDTON-1-2-3",
        task_id="42",
        status="Approved",
        comment="Reviewed and approved",
        days=2,
        hours=4,
    )
    body = out["body"][0]
    assert body["comment"] == "Reviewed and approved"
    assert body["days"] == 2
    assert body["hours"] == 4


@pytest.mark.asyncio
@respx.mock
async def test_confirmed_call_hits_api(write_tool_context, tmp_path) -> None:
    route = respx.put("https://apis.test.example/v4/records/ISLANDTON-1-2-3/workflowTasks").mock(
        return_value=Response(200, json={"status": 200, "result": [{"id": "42"}]})
    )
    mcp = register_module(workflow_write, write_tool_context)
    out = await call(mcp, "accela_update_workflow_task")(
        record_id="ISLANDTON-1-2-3",
        task_id="42",
        status="Approved",
        confirm=True,
    )
    assert route.called
    assert out["result_status"] == 200
    assert out["result_id"] == "42"
    sent = json.loads(route.calls.last.request.content)
    assert sent[0]["status"]["value"] == "Approved"


@pytest.mark.asyncio
@respx.mock
async def test_confirmed_call_writes_audit_log(write_tool_context, tmp_path) -> None:
    respx.put("https://apis.test.example/v4/records/ISLANDTON-1-2-3/workflowTasks").mock(
        return_value=Response(200, json={"status": 200, "result": [{"id": "42"}]})
    )
    mcp = register_module(workflow_write, write_tool_context)
    await call(mcp, "accela_update_workflow_task")(
        record_id="ISLANDTON-1-2-3",
        task_id="42",
        status="Approved",
        confirm=True,
    )
    audit_path = write_tool_context.audit_log.path
    lines = audit_path.read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["tool"] == "accela_update_workflow_task"
    assert parsed["method"] == "PUT"
    assert parsed["result_id"] == "42"


@pytest.mark.asyncio
async def test_validates_required_fields(write_tool_context) -> None:
    mcp = register_module(workflow_write, write_tool_context)
    out = await call(mcp, "accela_update_workflow_task")(
        record_id="",
        task_id="42",
        status="Approved",
    )
    assert out["error"] == "invalid_input"
    out = await call(mcp, "accela_update_workflow_task")(
        record_id="X",
        task_id="",
        status="Approved",
    )
    assert out["error"] == "invalid_input"
    out = await call(mcp, "accela_update_workflow_task")(
        record_id="X",
        task_id="42",
        status="",
    )
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
async def test_kill_switch_off_refuses_confirmed_call(tool_context) -> None:
    """`tool_context` uses the read-only loaded_config, so writes.enabled=false."""
    mcp = register_module(workflow_write, tool_context)
    out = await call(mcp, "accela_update_workflow_task")(
        record_id="ISLANDTON-1-2-3",
        task_id="42",
        status="Approved",
        confirm=True,
    )
    assert out["error"] == "writes_disabled"
