from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import workflow_read

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register(tool_context) -> None:
    mcp = register_module(workflow_read, tool_context)
    assert tool_names(mcp) == {
        "accela_list_workflow_tasks",
        "accela_get_workflow_task_history",
    }


@pytest.mark.asyncio
@respx.mock
async def test_list_workflow_tasks(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-1-2-3/workflowTasks").mock(
        return_value=Response(200, json={"result": [{"id": "t1"}]})
    )
    mcp = register_module(workflow_read, tool_context)
    out = await call(mcp, "accela_list_workflow_tasks")(record_id="ISLANDTON-1-2-3")
    assert out["tasks"] == [{"id": "t1"}]


@pytest.mark.asyncio
@respx.mock
async def test_workflow_task_history(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-1-2-3/workflowTasks/histories").mock(
        return_value=Response(200, json={"result": [{"event": "advanced"}]})
    )
    mcp = register_module(workflow_read, tool_context)
    out = await call(mcp, "accela_get_workflow_task_history")(record_id="ISLANDTON-1-2-3")
    assert out["history"][0]["event"] == "advanced"


@pytest.mark.asyncio
async def test_validates_record_id(tool_context) -> None:
    mcp = register_module(workflow_read, tool_context)
    out = await call(mcp, "accela_list_workflow_tasks")(record_id="")
    assert out["error"] == "invalid_input"
