"""Payments read tools — list payments on a record.

Pure read; no money moves. Useful for reconciling fees and answering
"what's been paid?"-type questions before any decision to charge again.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import ToolContext, tool_call


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool()
    @tool_call("accela_list_record_payments")
    async def accela_list_record_payments(record_id: str) -> dict[str, Any]:
        """Lists payments associated with a record (amounts, methods,
        timestamps, references). Read-only — no money moves. Use before
        any decision about fees or follow-up charges."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        result = await ctx.client.get(f"/v4/records/{record_id}/payments")
        return {"payments": result.get("result") or []}
