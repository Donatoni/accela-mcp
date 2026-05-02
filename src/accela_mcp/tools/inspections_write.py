"""Inspections write tools — schedule, reschedule, cancel, result, assign.

Five tools mapping to:

    POST /v4/records/{recordId}/inspections          (schedule)
    PUT  /v4/inspections/{ids}                       (reschedule, assign)
    PUT  /v4/inspections/{ids}/result                (result)
    PUT  /v4/inspections/{ids}                       (cancel — status update)

Every tool defaults to dry-run; only `confirm=True` actually mutates.

Status string conventions vary per agency. Tools take what the user types
and let Accela validate; the read-side `accela_get_inspection` plus
`accela_list_inspection_types` are the right places to discover what's
valid.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.safety import WritePreview, write_tool
from accela_mcp.tools._base import ToolContext, destructive_annotations


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=destructive_annotations("Schedule Inspection"))
    @write_tool("accela_schedule_inspection", ctx)
    async def accela_schedule_inspection(
        record_id: str,
        inspection_type: str,
        scheduled_date: str,
        scheduled_time: str | None = None,
        inspector_id: str | None = None,
        request_comment: str | None = None,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ Mutates Accela data. **Default is dry-run** — show the
        returned preview to the human user and only re-invoke with
        `confirm=True` after they approve.

        Schedules a new inspection on a record. `inspection_type` should
        match an entry from `accela_list_inspection_types`.
        `scheduled_date` is ISO format (`YYYY-MM-DD`); optional
        `scheduled_time` is `HH:MM` 24-hour."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        if not inspection_type or not inspection_type.strip():
            raise ValueError("inspection_type is required")
        if not scheduled_date or not scheduled_date.strip():
            raise ValueError("scheduled_date is required (YYYY-MM-DD)")

        body: dict[str, Any] = {
            "type": {"text": inspection_type},
            "scheduleDate": scheduled_date,
        }
        if scheduled_time:
            body["scheduleStartTime"] = scheduled_time
        if inspector_id:
            body["inspectorId"] = inspector_id
        if request_comment:
            body["requestComment"] = request_comment

        path = f"/v4/records/{record_id}/inspections"
        if not confirm:
            return WritePreview(
                tool="accela_schedule_inspection",
                method="POST",
                path=path,
                summary=(
                    f"Schedule {inspection_type!r} inspection on record {record_id!r} "
                    f"for {scheduled_date}" + (f" {scheduled_time}" if scheduled_time else "")
                ),
                body=body,
            )

        response = await ctx.client.post(path, json=body)
        return {
            "method": "POST",
            "path": path,
            "request_body": body,
            "result_status": int(response.get("status", 200)),
            "result_id": _result_inspection_id(response),
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }

    @mcp.tool(annotations=destructive_annotations("Reschedule Inspection"))
    @write_tool("accela_reschedule_inspection", ctx)
    async def accela_reschedule_inspection(
        inspection_id: str,
        scheduled_date: str,
        scheduled_time: str | None = None,
        comment: str | None = None,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ Mutates Accela data. **Default is dry-run** — show the
        returned preview to the human user and only re-invoke with
        `confirm=True` after they approve.

        Reschedules an existing inspection. `scheduled_date` is
        `YYYY-MM-DD`."""
        if not inspection_id or not str(inspection_id).strip():
            raise ValueError("inspection_id is required")
        if not scheduled_date:
            raise ValueError("scheduled_date is required (YYYY-MM-DD)")

        body: dict[str, Any] = {"scheduleDate": scheduled_date}
        if scheduled_time:
            body["scheduleStartTime"] = scheduled_time
        if comment:
            body["comment"] = comment

        path = f"/v4/inspections/{inspection_id}"
        if not confirm:
            return WritePreview(
                tool="accela_reschedule_inspection",
                method="PUT",
                path=path,
                summary=(
                    f"Reschedule inspection {inspection_id!r} → {scheduled_date}"
                    + (f" {scheduled_time}" if scheduled_time else "")
                ),
                body=body,
            )

        response = await ctx.client.put(path, json=body)
        return {
            "method": "PUT",
            "path": path,
            "request_body": body,
            "result_status": int(response.get("status", 200)),
            "result_id": str(inspection_id),
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }

    @mcp.tool(annotations=destructive_annotations("Cancel Inspection"))
    @write_tool("accela_cancel_inspection", ctx)
    async def accela_cancel_inspection(
        inspection_id: str,
        comment: str | None = None,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ Mutates Accela data. **Default is dry-run** — show the
        returned preview to the human user and only re-invoke with
        `confirm=True` after they approve.

        Cancels a scheduled inspection. Equivalent to a status update to
        `Cancelled`; some agencies use a different cancel verb — verify
        with `accela_list_inspection_types` if a call is rejected."""
        if not inspection_id or not str(inspection_id).strip():
            raise ValueError("inspection_id is required")

        body: dict[str, Any] = {"status": {"value": "Cancelled"}}
        if comment:
            body["comment"] = comment

        path = f"/v4/inspections/{inspection_id}"
        if not confirm:
            return WritePreview(
                tool="accela_cancel_inspection",
                method="PUT",
                path=path,
                summary=f"Cancel inspection {inspection_id!r}",
                body=body,
                irreversible=True,
            )

        response = await ctx.client.put(path, json=body)
        return {
            "method": "PUT",
            "path": path,
            "request_body": body,
            "result_status": int(response.get("status", 200)),
            "result_id": str(inspection_id),
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }

    @mcp.tool(annotations=destructive_annotations("Result Inspection"))
    @write_tool("accela_result_inspection", ctx)
    async def accela_result_inspection(
        inspection_id: str,
        result_value: str,
        result_comment: str | None = None,
        result_date: str | None = None,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ Mutates Accela data. **Default is dry-run** — show the
        returned preview to the human user and only re-invoke with
        `confirm=True` after they approve.

        Posts a result on an inspection (e.g. `Pass`, `Fail`,
        `Conditional`). Status strings are agency-defined — pull the valid
        list from `accela_list_inspection_types` first. `result_date` is
        `YYYY-MM-DD`; defaults to today server-side if omitted."""
        if not inspection_id or not str(inspection_id).strip():
            raise ValueError("inspection_id is required")
        if not result_value or not result_value.strip():
            raise ValueError("result_value is required")

        body: dict[str, Any] = {"value": result_value}
        if result_comment:
            body["comment"] = result_comment
        if result_date:
            body["resultDate"] = result_date

        path = f"/v4/inspections/{inspection_id}/result"
        if not confirm:
            return WritePreview(
                tool="accela_result_inspection",
                method="PUT",
                path=path,
                summary=(f"Post result {result_value!r} on inspection {inspection_id!r}"),
                body=body,
                irreversible=True,
            )

        response = await ctx.client.put(path, json=body)
        return {
            "method": "PUT",
            "path": path,
            "request_body": body,
            "result_status": int(response.get("status", 200)),
            "result_id": str(inspection_id),
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }

    @mcp.tool(annotations=destructive_annotations("Assign Inspection"))
    @write_tool("accela_assign_inspection", ctx)
    async def accela_assign_inspection(
        inspection_id: str,
        inspector_id: str,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ Mutates Accela data. **Default is dry-run** — show the
        returned preview to the human user and only re-invoke with
        `confirm=True` after they approve.

        Reassigns an inspection to a different inspector by user ID."""
        if not inspection_id or not str(inspection_id).strip():
            raise ValueError("inspection_id is required")
        if not inspector_id or not inspector_id.strip():
            raise ValueError("inspector_id is required")

        body: dict[str, Any] = {"inspectorId": inspector_id}
        path = f"/v4/inspections/{inspection_id}"
        if not confirm:
            return WritePreview(
                tool="accela_assign_inspection",
                method="PUT",
                path=path,
                summary=(f"Reassign inspection {inspection_id!r} to inspector {inspector_id!r}"),
                body=body,
            )

        response = await ctx.client.put(path, json=body)
        return {
            "method": "PUT",
            "path": path,
            "request_body": body,
            "result_status": int(response.get("status", 200)),
            "result_id": str(inspection_id),
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }


def _result_inspection_id(response: dict[str, Any]) -> str | None:
    """Pull a single inspection id out of a typical Accela create response."""
    result = response.get("result")
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            value = first.get("id")
            if value is not None:
                return str(value)
    if isinstance(result, dict):
        value = result.get("id")
        if value is not None:
            return str(value)
    return None
