"""Reports tools — list and run agency-defined reports.

Reports are agency-configured exports/queries. `list_reports` is purely
informational; `run_report` does trigger server-side work but doesn't
mutate user-visible records, so we treat it as a read-style tool with
explicit parameter validation rather than wiring it through the
`write_tool` confirmation pattern.

If a particular agency's reports DO have side effects (some configure
SQL UPDATEs behind a "report"), the agency admin should not enable the
`reports` group — that's a misconfiguration on their side, not something
this MCP can detect ahead of time.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import ToolContext, tool_call


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool()
    @tool_call("accela_list_reports")
    async def accela_list_reports(
        module: str | None = None,
    ) -> dict[str, Any]:
        """Lists agency-defined reports the authenticated user can run.
        Optional `module` filter scopes to one Civic Platform module."""
        params: dict[str, Any] = {}
        if module:
            params["module"] = module
        result = await ctx.client.get("/v4/reports", params=params or None)
        return {"reports": result.get("result") or []}

    @mcp.tool()
    @tool_call("accela_run_report")
    async def accela_run_report(
        report_id: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Runs a report by ID with optional parameters. Returns the
        report's structured output (typically `{result: [...rows]}`)."""
        if not report_id or not str(report_id).strip():
            raise ValueError("report_id is required")
        body = {"parameters": parameters or {}}
        result = await ctx.client.post(f"/v4/reports/{report_id}/run", json=body)
        return result
