"""Fees read tools — list fees, estimate, list invoices."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import ToolContext, read_only_annotations, tool_call


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=read_only_annotations("List Record Fees"))
    @tool_call("accela_list_record_fees")
    async def accela_list_record_fees(record_id: str) -> dict[str, Any]:
        """Lists fees assessed on a record, with line items, amounts, paid
        amounts, and balance per fee."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        result = await ctx.client.get(f"/v4/records/{record_id}/fees")
        return {"fees": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("Estimate Record Fees"))
    @tool_call("accela_estimate_record_fees")
    async def accela_estimate_record_fees(
        record_id: str,
        fees: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Estimates fees for a record without committing them. Useful for
        \"what would this cost?\" queries. The optional `fees` array, when
        provided, lets you simulate fee additions; the structure depends on
        the agency's fee schedule and is documented per-endpoint by Accela."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        body: list[dict[str, Any]] = list(fees) if fees else []
        result = await ctx.client.put(f"/v4/records/{record_id}/fees/estimate", json=body)
        return result

    @mcp.tool(annotations=read_only_annotations("List Record Invoices"))
    @tool_call("accela_list_record_invoices")
    async def accela_list_record_invoices(record_id: str) -> dict[str, Any]:
        """Lists invoices issued for a record. Each invoice typically groups
        one or more fees that were billed together."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        result = await ctx.client.get(f"/v4/records/{record_id}/invoices")
        return {"invoices": result.get("result") or []}
