"""Inspections read tools — list for record, detail, history, checklists."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import (
    ToolContext,
    clamp_limit,
    clamp_offset,
    read_only_annotations,
    tool_call,
)
from accela_mcp.utils.ids import join_ids


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=read_only_annotations("List Inspections for Record"))
    @tool_call("accela_list_inspections_for_record")
    async def accela_list_inspections_for_record(
        record_id: str,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Lists inspections associated with a record. Use this when
        investigating a permit's inspection history or planning the next
        inspection."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        result = await ctx.client.get(
            f"/v4/records/{record_id}/inspections",
            params={"limit": clamp_limit(limit), "offset": clamp_offset(offset)},
        )
        return {
            "inspections": result.get("result") or [],
            "page": result.get("page") or {},
        }

    @mcp.tool(annotations=read_only_annotations("Get Inspection"))
    @tool_call("accela_get_inspection")
    async def accela_get_inspection(inspection_ids: list[str]) -> dict[str, Any]:
        """Retrieves full details for one or more inspections by ID, including
        assigned inspector, scheduled date, status, and result. Pass numeric
        inspection IDs as strings."""
        joined = join_ids(inspection_ids)
        result = await ctx.client.get(f"/v4/inspections/{joined}")
        return {"inspections": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("Get Inspection History"))
    @tool_call("accela_get_inspection_history")
    async def accela_get_inspection_history(inspection_ids: list[str]) -> dict[str, Any]:
        """Returns the audit history for one or more inspections — status
        changes, scheduling changes, result entries. Use for compliance audits
        or troubleshooting."""
        joined = join_ids(inspection_ids)
        result = await ctx.client.get(f"/v4/inspections/{joined}/histories")
        return {"history": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("Get Inspection Checklists"))
    @tool_call("accela_get_inspection_checklists")
    async def accela_get_inspection_checklists(inspection_id: str) -> dict[str, Any]:
        """Returns the checklists and checklist items associated with an
        inspection, including pass/fail status on each item. Items per
        checklist are fetched in parallel; per-tool concurrency is capped to
        avoid hammering the rate limiter."""
        if not inspection_id or not inspection_id.strip():
            raise ValueError("inspection_id is required")

        checklists_payload = await ctx.client.get(f"/v4/inspections/{inspection_id}/checklists")
        checklists = checklists_payload.get("result") or []

        # Fetch items per checklist with bounded concurrency.
        semaphore = asyncio.Semaphore(5)

        async def _fetch_items(checklist_id: str | int) -> list[dict[str, Any]]:
            async with semaphore:
                items_payload = await ctx.client.get(
                    f"/v4/inspections/{inspection_id}/checklists/{checklist_id}/items"
                )
                return items_payload.get("result") or []

        results = await asyncio.gather(
            *[_fetch_items(cl["id"]) for cl in checklists if cl.get("id") is not None],
            return_exceptions=True,
        )
        for cl, items in zip(checklists, results, strict=False):
            if isinstance(items, BaseException):
                cl["items"] = {"error": "fetch_failed", "message": str(items)}
            else:
                cl["items"] = items

        return {"checklists": checklists}
