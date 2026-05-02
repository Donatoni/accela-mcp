"""Reference data tools — record types, statuses, departments, fee schedules.

These endpoints change rarely, so we cache responses with the configured TTL
(default 1 h). Every tool exposes `cache_bypass: bool = False` to force a
fresh fetch when the operator suspects their agency just reconfigured.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import ToolContext, read_only_annotations, tool_call


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    cache = ctx.reference_cache
    agency = ctx.client.agency
    env = ctx.client.environment

    async def _get(
        path: str, params: dict[str, Any] | None, *, cache_bypass: bool
    ) -> dict[str, Any]:
        cache_key = cache.make_key(agency, env, path, params)
        if cache_bypass:
            cache.invalidate(cache_key)
        return await cache.get_or_set(
            cache_key,
            lambda: ctx.client.get(path, params=params),
        )

    @mcp.tool(annotations=read_only_annotations("List Record Types"))
    @tool_call("accela_list_record_types")
    async def accela_list_record_types(
        module: str | None = None,
        cache_bypass: bool = False,
    ) -> dict[str, Any]:
        """Lists configured record types. Optionally filter by `module`
        (e.g., `Building`, `ServiceRequest`, `Licenses`). Use this to discover
        what kinds of records exist in this agency before searching or
        creating. Cached with the server's reference-data TTL."""
        result = await _get(
            "/v4/settings/records/types",
            {"module": module} if module else None,
            cache_bypass=cache_bypass,
        )
        return {"record_types": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("List Inspection Types"))
    @tool_call("accela_list_inspection_types")
    async def accela_list_inspection_types(
        module: str | None = None,
        group: str | None = None,
        cache_bypass: bool = False,
    ) -> dict[str, Any]:
        """Lists configured inspection types. Optionally filter by `module`
        and/or inspection `group`. Cached."""
        params: dict[str, Any] = {}
        if module:
            params["module"] = module
        if group:
            params["group"] = group
        result = await _get(
            "/v4/settings/inspections/types",
            params or None,
            cache_bypass=cache_bypass,
        )
        return {"inspection_types": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("List Record Statuses"))
    @tool_call("accela_list_record_statuses")
    async def accela_list_record_statuses(
        module: str | None = None,
        cache_bypass: bool = False,
    ) -> dict[str, Any]:
        """Lists configured record statuses. Optionally filter by `module`.
        Cached."""
        result = await _get(
            "/v4/settings/records/statuses",
            {"module": module} if module else None,
            cache_bypass=cache_bypass,
        )
        return {"statuses": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("List Departments"))
    @tool_call("accela_list_departments")
    async def accela_list_departments(
        cache_bypass: bool = False,
    ) -> dict[str, Any]:
        """Lists agency departments (used for assignment lookups). Cached."""
        result = await _get("/v4/settings/departments", None, cache_bypass=cache_bypass)
        return {"departments": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("List Fee Schedules"))
    @tool_call("accela_list_fee_schedules")
    async def accela_list_fee_schedules(
        cache_bypass: bool = False,
    ) -> dict[str, Any]:
        """Lists configured fee schedules. Cached."""
        result = await _get("/v4/settings/fees", None, cache_bypass=cache_bypass)
        return {"fee_schedules": result.get("result") or []}
