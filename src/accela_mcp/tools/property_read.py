"""Property read tools — addresses, parcels, owners (the APO triad)."""

from __future__ import annotations

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

ALLOWED_PARCEL_EXPANSIONS = frozenset({"addresses", "owners", "records"})


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool()
    @tool_call("accela_get_address")
    async def accela_get_address(address_id: str) -> dict[str, Any]:
        """Retrieves an address record (formatted address, geo coordinates if
        available, status). The `address_id` is Accela's internal numeric ID
        as a string."""
        if not address_id or not address_id.strip():
            raise ValueError("address_id is required")
        payload = await ctx.client.get(f"/v4/addresses/{address_id}")
        result = first_result(payload)
        if result is None:
            return {"error": "not_found", "address_id": address_id}
        return result

    @mcp.tool()
    @tool_call("accela_search_addresses")
    async def accela_search_addresses(
        street: str | None = None,
        city: str | None = None,
        state: str | None = None,
        postal_code: str | None = None,
        limit: int = 25,
        offset: int = 0,
        auto_paginate: bool = True,
        max_results: int = 1000,
    ) -> dict[str, Any]:
        """Searches the agency's address master by street, city, state, and/or
        postal code. At least one search field is required. By default
        auto-paginates up to `max_results` (default 1000); when the cap is
        hit and more results exist, the response includes a `continuation`
        cursor — surface that and ask the user before paginating further.
        Set `auto_paginate=False` to fetch a single page."""
        if not any([street, city, state, postal_code]):
            raise ValueError("Provide at least one of street, city, state, postal_code")
        body: dict[str, Any] = {
            "streetName": street,
            "city": city,
            "state": {"value": state} if state else None,
            "postalCode": postal_code,
        }
        body = {k: v for k, v in body.items() if v is not None}
        start_offset = clamp_offset(offset)

        if auto_paginate:
            cap = clamp_max_results(max_results)

            async def fetch(off: int, lim: int) -> dict[str, Any]:
                return await ctx.client.post(
                    "/v4/search/addresses",
                    params={"offset": off, "limit": lim},
                    json=body,
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
                    f"Returned {len(result.items)} addresses and more are available. "
                    f"Ask the user whether to continue; if yes, call again with "
                    f"offset={result.continuation['next_offset']} or raise "
                    f"max_results."
                )
            return {
                "addresses": result.items,
                "page": result.last_page,
                "warnings": warnings or None,
                "continuation": result.continuation,
            }

        single = await ctx.client.post(
            "/v4/search/addresses",
            params={"limit": clamp_limit(limit), "offset": start_offset},
            json=body,
        )
        return {
            "addresses": single.get("result") or [],
            "page": single.get("page") or {},
            "warnings": None,
            "continuation": None,
        }

    @mcp.tool()
    @tool_call("accela_get_parcel")
    async def accela_get_parcel(
        parcel_id: str,
        expand: list[str] | None = None,
    ) -> dict[str, Any]:
        """Retrieves a parcel by Accela parcel ID. Use `expand` to inline
        related sub-objects (`addresses`, `owners`, `records`)."""
        if not parcel_id or not parcel_id.strip():
            raise ValueError("parcel_id is required")

        params: dict[str, Any] = {}
        if expand:
            unknown = sorted(set(expand) - ALLOWED_PARCEL_EXPANSIONS)
            if unknown:
                raise ValueError(
                    f"unknown expand keys: {unknown!r}. "
                    f"Valid keys: {sorted(ALLOWED_PARCEL_EXPANSIONS)}"
                )
            params["expand"] = ",".join(expand)

        payload = await ctx.client.get(f"/v4/parcels/{parcel_id}", params=params)
        result = first_result(payload)
        if result is None:
            return {"error": "not_found", "parcel_id": parcel_id}
        return result

    @mcp.tool()
    @tool_call("accela_get_owners_for_parcel")
    async def accela_get_owners_for_parcel(parcel_id: str) -> dict[str, Any]:
        """Lists owners associated with a parcel."""
        if not parcel_id or not parcel_id.strip():
            raise ValueError("parcel_id is required")
        result = await ctx.client.get(f"/v4/parcels/{parcel_id}/owners")
        return {"owners": result.get("result") or []}
