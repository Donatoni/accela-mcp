"""Records read tools — search, get, custom data."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.api.pagination import SEARCH_MAX_PAGE, auto_paginate_collect
from accela_mcp.tools._base import (
    ToolContext,
    clamp_limit,
    clamp_max_results,
    clamp_offset,
    first_result,
    tool_call,
)

ALLOWED_EXPANSIONS = frozenset(
    {
        "addresses",
        "contacts",
        "parcels",
        "owners",
        "professionals",
        "customForms",
        "customTables",
    }
)


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool()
    @tool_call("accela_search_records")
    async def accela_search_records(
        module: str | None = None,
        record_type: str | None = None,
        status: str | None = None,
        opened_date_from: str | None = None,
        opened_date_to: str | None = None,
        custom_id: str | None = None,
        address: str | None = None,
        parcel_number: str | None = None,
        limit: int = 25,
        offset: int = 0,
        auto_paginate: bool = True,
        max_results: int = 1000,
    ) -> dict[str, Any]:
        """Searches records by criteria. Use for finding records by status,
        type, date range, address, parcel, or custom ID. Returns a list of
        record summaries — call `accela_get_record` for full details. Dates
        are ISO format (YYYY-MM-DD). `record_type` is the 4-part path
        `Module/Group/Type/SubType`.

        By default the tool auto-paginates and returns up to `max_results`
        (default 1000). When the cap is hit and more results exist, the
        response includes a `continuation` cursor — surface that to the user
        and ask whether to keep paginating before calling again with
        `offset=continuation.next_offset`. Set `auto_paginate=False` to
        fetch a single page (`limit` records, capped at 100)."""
        base_params: dict[str, Any] = {
            "module": module,
            "type": record_type,
            "status": status,
            "openedDateFrom": opened_date_from,
            "openedDateTo": opened_date_to,
            "customId": custom_id,
            "address": address,
            "parcelNumber": parcel_number,
        }
        start_offset = clamp_offset(offset)

        if auto_paginate:
            cap = clamp_max_results(max_results)

            async def fetch(off: int, lim: int) -> dict[str, Any]:
                return await ctx.client.get(
                    "/v4/records",
                    params={**base_params, "offset": off, "limit": lim},
                )

            result = await auto_paginate_collect(
                fetch,
                page_size=SEARCH_MAX_PAGE,
                max_results=cap,
                start_offset=start_offset,
            )
            warnings: list[str] = []
            if result.continuation:
                warnings.append(
                    f"Returned {len(result.items)} records and more are available. "
                    f"Ask the user whether to continue; if yes, call again with "
                    f"offset={result.continuation['next_offset']} or raise "
                    f"max_results."
                )
            return {
                "records": result.items,
                "page": result.last_page,
                "warnings": warnings or None,
                "continuation": result.continuation,
            }

        params = {
            **base_params,
            "limit": clamp_limit(limit),
            "offset": start_offset,
        }
        single = await ctx.client.get("/v4/records", params=params)
        page = single.get("page") or {}
        records = single.get("result") or []
        warnings = []
        if len(records) >= 100 and page.get("hasmore"):
            warnings.append(
                "Reached the 100-record search cap. Refine your filters or "
                "set auto_paginate=True (the default) to fetch more results."
            )
        return {
            "records": records,
            "page": page,
            "warnings": warnings or None,
            "continuation": None,
        }

    @mcp.tool()
    @tool_call("accela_get_record")
    async def accela_get_record(
        record_id: str,
        expand: list[str] | None = None,
    ) -> dict[str, Any]:
        """Retrieves a single record by ID. Use `expand` to inline sub-objects
        (`addresses`, `contacts`, `parcels`, `owners`, `professionals`,
        `customForms`, `customTables`) in one call instead of separate fetches.
        The `record_id` is the full prefixed ID, e.g.,
        `ISLANDTON-14CAP-00000-000I4`."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")

        params: dict[str, Any] = {}
        if expand:
            unknown = sorted(set(expand) - ALLOWED_EXPANSIONS)
            if unknown:
                raise ValueError(
                    f"unknown expand keys: {unknown!r}. Valid keys: {sorted(ALLOWED_EXPANSIONS)}"
                )
            params["expand"] = ",".join(expand)

        payload = await ctx.client.get(f"/v4/records/{record_id}", params=params)
        record = first_result(payload)
        if record is None:
            return {"error": "not_found", "record_id": record_id}
        return record

    @mcp.tool()
    @tool_call("accela_get_my_records")
    async def accela_get_my_records(
        limit: int = 25,
        offset: int = 0,
        auto_paginate: bool = True,
        max_results: int = 1000,
    ) -> dict[str, Any]:
        """Returns records associated with the authenticated user (creator,
        assignee, or contact). By default auto-paginates up to `max_results`
        (default 1000) and surfaces a `continuation` cursor when more results
        exist — ask the user before continuing past the cap. Set
        `auto_paginate=False` to fetch a single page."""
        start_offset = clamp_offset(offset)

        if auto_paginate:
            cap = clamp_max_results(max_results)

            async def fetch(off: int, lim: int) -> dict[str, Any]:
                return await ctx.client.get(
                    "/v4/records/mine", params={"offset": off, "limit": lim}
                )

            result = await auto_paginate_collect(
                fetch,
                page_size=SEARCH_MAX_PAGE,
                max_results=cap,
                start_offset=start_offset,
            )
            warnings: list[str] = []
            if result.continuation:
                warnings.append(
                    f"Returned {len(result.items)} records and more are available. "
                    f"Ask the user whether to continue; if yes, call again with "
                    f"offset={result.continuation['next_offset']} or raise "
                    f"max_results."
                )
            return {
                "records": result.items,
                "page": result.last_page,
                "warnings": warnings or None,
                "continuation": result.continuation,
            }

        single = await ctx.client.get(
            "/v4/records/mine",
            params={"limit": clamp_limit(limit), "offset": start_offset},
        )
        return {
            "records": single.get("result") or [],
            "page": single.get("page") or {},
            "warnings": None,
            "continuation": None,
        }

    @mcp.tool()
    @tool_call("accela_get_record_custom_data")
    async def accela_get_record_custom_data(record_id: str) -> dict[str, Any]:
        """Reads agency-specific custom form and custom table data for a
        record. The shape depends on the agency's configuration — call
        `accela_describe_record_metadata` first if unsure about field names.
        Custom forms and tables are fetched in parallel."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")

        forms, tables = await asyncio.gather(
            ctx.client.get(f"/v4/records/{record_id}/customForms"),
            ctx.client.get(f"/v4/records/{record_id}/customTables"),
            return_exceptions=True,
        )
        return {
            "custom_forms": (
                forms
                if not isinstance(forms, BaseException)
                else {"error": "fetch_failed", "message": str(forms)}
            ),
            "custom_tables": (
                tables
                if not isinstance(tables, BaseException)
                else {"error": "fetch_failed", "message": str(tables)}
            ),
        }
