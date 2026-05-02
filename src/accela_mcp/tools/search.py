"""Cross-entity global search."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import ToolContext, clamp_limit, read_only_annotations, tool_call


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=read_only_annotations("Global Search"))
    @tool_call("accela_global_search")
    async def accela_global_search(query: str, limit: int = 25) -> dict[str, Any]:
        """Free-text search across records, addresses, parcels, contacts,
        professionals, and inspections. Use when the user has a keyword and
        isn't sure which entity type they're looking for. Limit defaults to 25
        and is capped at 100. The result groups matches by entity type."""
        if not query or not query.strip():
            raise ValueError("query is required")
        result = await ctx.client.get(
            "/v4/search/global",
            params={"q": query.strip(), "limit": clamp_limit(limit)},
        )
        return {
            "results": result.get("result") or [],
            "page": result.get("page") or {},
        }
