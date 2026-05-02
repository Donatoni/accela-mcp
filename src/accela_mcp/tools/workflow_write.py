"""Workflow write tools — advance / update workflow tasks on a record.

One tool today: `accela_update_workflow_task`. Maps to:

    PUT /v4/records/{recordId}/workflowTasks

Per the Accela docs, the body is an array of workflow-task updates. The
common case from an LLM is "advance task X to status Y" on one record, so
the tool takes a single task at a time and submits it as a one-element
array.

Like every write tool in this package: defaults to dry-run. Set
`confirm=True` only after surfacing the preview to the human user.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.safety import WritePreview, write_tool
from accela_mcp.tools._base import ToolContext, destructive_annotations


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=destructive_annotations("Update Workflow Task"))
    @write_tool("accela_update_workflow_task", ctx)
    async def accela_update_workflow_task(
        record_id: str,
        task_id: str,
        status: str,
        comment: str | None = None,
        days: int | None = None,
        hours: int | None = None,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ Mutates Accela data. **Default is dry-run** — show the returned
        preview to the human user and only re-invoke with `confirm=True`
        after they approve.

        Updates a single workflow task on a record (e.g., "Plan Review →
        Approved"). Triggers any agency EMSE before/after-event scripts
        attached to that task. Use `accela_list_workflow_tasks` first to
        discover task IDs and valid statuses; do not guess status strings
        from display text — they vary per agency."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        if not task_id or not str(task_id).strip():
            raise ValueError("task_id is required")
        if not status or not str(status).strip():
            raise ValueError("status is required")

        body: list[dict[str, Any]] = [
            {
                "id": str(task_id),
                "status": {"value": status},
            }
        ]
        if comment:
            body[0]["comment"] = comment
        if days is not None:
            body[0]["days"] = days
        if hours is not None:
            body[0]["hours"] = hours

        path = f"/v4/records/{record_id}/workflowTasks"
        if not confirm:
            return WritePreview(
                tool="accela_update_workflow_task",
                method="PUT",
                path=path,
                summary=(
                    f"Update workflow task {task_id!r} on record {record_id!r} → status {status!r}"
                ),
                body=body,
            )

        response = await ctx.client.put(path, json=body)
        return {
            "method": "PUT",
            "path": path,
            "request_body": body,
            "result_status": int(response.get("status", 200)),
            "result_id": str(task_id),
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }
