"""Discovery tools — always enabled.

Three tools:
  * `accela_list_capabilities` — what's enabled in this server.
  * `accela_get_agency` — connected agency metadata.
  * `accela_describe_record_metadata` — agency-specific schema for a record
    or record-type. Critical to call before reading/writing custom data.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.capabilities import get_tools_by_group_for
from accela_mcp.tools._base import ToolContext, tool_call


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool()
    @tool_call("accela_list_capabilities")
    async def accela_list_capabilities() -> dict[str, Any]:
        """Lists which capability groups and tools are currently enabled, plus the
        connected agency and environment. Use this when a user asks what the
        assistant can do with Accela."""
        return {
            "agency": ctx.client.agency,
            "environment": ctx.client.environment,
            "app_id": ctx.settings.app_id,
            "scopes": ctx.tokens_scope_list(),
            "enabled_groups": sorted(ctx.config.enabled_groups),
            "tools_by_group": get_tools_by_group_for(ctx.config.enabled_groups),
        }

    @mcp.tool()
    @tool_call("accela_get_agency")
    async def accela_get_agency() -> dict[str, Any]:
        """Retrieves the connected agency's metadata: name, address, configured
        environments, country, state. Returns the raw Accela `agencies/{name}`
        payload."""
        return await ctx.client.get(f"/v4/agencies/{ctx.client.agency}")

    @mcp.tool()
    @tool_call("accela_describe_record_metadata")
    async def accela_describe_record_metadata(
        record_id: str | None = None,
        record_type: str | None = None,
    ) -> dict[str, Any]:
        """Discovers the agency-specific schema (custom forms, custom tables,
        required fields) for an existing record or a record type. Call this
        BEFORE attempting to read or write custom data — agency configurations
        vary. Provide exactly one of `record_id` or `record_type`. The
        `record_type` format is `Module/Group/Type/SubType`."""
        if not record_id and not record_type:
            raise ValueError("Provide either record_id or record_type")
        if record_id and record_type:
            raise ValueError("Provide only one of record_id or record_type")

        out: dict[str, Any] = {}
        if record_type:
            out["create_describe"] = await ctx.client.get(
                "/v4/records/describe/create",
                params={"type": record_type},
            )
            return out

        # record_id path: parallel-fetch the two metadata endpoints.
        forms_meta, tables_meta = await asyncio.gather(
            ctx.client.get(f"/v4/records/{record_id}/customForms/meta"),
            ctx.client.get(f"/v4/records/{record_id}/customTables/meta"),
            return_exceptions=True,
        )

        out["custom_forms_meta"] = (
            forms_meta if not isinstance(forms_meta, BaseException) else _err_dict(forms_meta)
        )
        out["custom_tables_meta"] = (
            tables_meta if not isinstance(tables_meta, BaseException) else _err_dict(tables_meta)
        )
        return out


def _err_dict(exc: BaseException) -> dict[str, Any]:
    return {"error": "metadata_fetch_failed", "message": str(exc)}
