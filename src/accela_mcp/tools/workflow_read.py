"""Workflow read tools — list tasks for a record and view their history."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import ToolContext, read_only_annotations, tool_call


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=read_only_annotations("List Workflow Tasks"))
    @tool_call("accela_list_workflow_tasks")
    async def accela_list_workflow_tasks(record_id: str) -> dict[str, Any]:
        """Lists workflow tasks for a record, including current status and
        assigned department/staff. The record's lifecycle moves through these
        tasks; their status is what governs whether other operations
        (inspections, fees, finalize) are allowed."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        result = await ctx.client.get(f"/v4/records/{record_id}/workflowTasks")
        return {"tasks": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("Get Workflow Task History"))
    @tool_call("accela_get_workflow_task_history")
    async def accela_get_workflow_task_history(record_id: str) -> dict[str, Any]:
        """Returns history of workflow task status changes for a record.
        Useful for compliance audits or troubleshooting why a record is stuck
        in a status."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        result = await ctx.client.get(f"/v4/records/{record_id}/workflowTasks/histories")
        return {"history": result.get("result") or []}
