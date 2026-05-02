"""People read tools — contacts and licensed professionals."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.api.pagination import SEARCH_MAX_PAGE, auto_paginate_collect
from accela_mcp.tools._base import (
    ToolContext,
    clamp_limit,
    clamp_max_results,
    clamp_offset,
    read_only_annotations,
    tool_call,
)
from accela_mcp.utils.ids import join_ids


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=read_only_annotations("Get Contact"))
    @tool_call("accela_get_contact")
    async def accela_get_contact(contact_ids: list[str]) -> dict[str, Any]:
        """Retrieves one or more contacts by ID."""
        joined = join_ids(contact_ids)
        result = await ctx.client.get(f"/v4/contacts/{joined}")
        return {"contacts": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("Search Contacts"))
    @tool_call("accela_search_contacts")
    async def accela_search_contacts(
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        contact_type: str | None = None,
        limit: int = 25,
        offset: int = 0,
        auto_paginate: bool = True,
        max_results: int = 1000,
    ) -> dict[str, Any]:
        """Searches contacts by name, email, phone, or contact type. At least
        one search field is required. By default auto-paginates up to
        `max_results` (default 1000); when the cap is hit and more results
        exist, the response includes a `continuation` cursor — surface that
        and ask the user before paginating further. Set
        `auto_paginate=False` to fetch a single page."""
        if not any([name, email, phone, contact_type]):
            raise ValueError("Provide at least one of name, email, phone, contact_type")
        body: dict[str, Any] = {
            "fullName": name,
            "email": email,
            "phone": phone,
            "type": {"value": contact_type} if contact_type else None,
        }
        body = {k: v for k, v in body.items() if v is not None}
        start_offset = clamp_offset(offset)

        if auto_paginate:
            cap = clamp_max_results(max_results)

            async def fetch(off: int, lim: int) -> dict[str, Any]:
                return await ctx.client.post(
                    "/v4/search/contacts",
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
                    f"Returned {len(result.items)} contacts and more are available. "
                    f"Ask the user whether to continue; if yes, call again with "
                    f"offset={result.continuation['next_offset']} or raise "
                    f"max_results."
                )
            return {
                "contacts": result.items,
                "page": result.last_page,
                "warnings": warnings or None,
                "continuation": result.continuation,
            }

        single = await ctx.client.post(
            "/v4/search/contacts",
            params={"limit": clamp_limit(limit), "offset": start_offset},
            json=body,
        )
        return {
            "contacts": single.get("result") or [],
            "page": single.get("page") or {},
            "warnings": None,
            "continuation": None,
        }

    @mcp.tool(annotations=read_only_annotations("Get Professional"))
    @tool_call("accela_get_professional")
    async def accela_get_professional(professional_ids: list[str]) -> dict[str, Any]:
        """Retrieves one or more licensed professionals by ID, including
        license number and license type."""
        joined = join_ids(professional_ids)
        result = await ctx.client.get(f"/v4/professionals/{joined}")
        return {"professionals": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("Search Professionals"))
    @tool_call("accela_search_professionals")
    async def accela_search_professionals(
        name: str | None = None,
        license_number: str | None = None,
        license_type: str | None = None,
        limit: int = 25,
        offset: int = 0,
        auto_paginate: bool = True,
        max_results: int = 1000,
    ) -> dict[str, Any]:
        """Searches licensed professionals by name, license number, or license
        type. At least one search field is required. By default auto-paginates
        up to `max_results` (default 1000); when the cap is hit and more
        results exist, the response includes a `continuation` cursor —
        surface that and ask the user before paginating further. Set
        `auto_paginate=False` to fetch a single page."""
        if not any([name, license_number, license_type]):
            raise ValueError("Provide at least one of name, license_number, license_type")
        body: dict[str, Any] = {
            "fullName": name,
            "licenseNumber": license_number,
            "licenseType": license_type,
        }
        body = {k: v for k, v in body.items() if v is not None}
        start_offset = clamp_offset(offset)

        if auto_paginate:
            cap = clamp_max_results(max_results)

            async def fetch(off: int, lim: int) -> dict[str, Any]:
                return await ctx.client.post(
                    "/v4/search/professionals",
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
                    f"Returned {len(result.items)} professionals and more are available. "
                    f"Ask the user whether to continue; if yes, call again with "
                    f"offset={result.continuation['next_offset']} or raise "
                    f"max_results."
                )
            return {
                "professionals": result.items,
                "page": result.last_page,
                "warnings": warnings or None,
                "continuation": result.continuation,
            }

        single = await ctx.client.post(
            "/v4/search/professionals",
            params={"limit": clamp_limit(limit), "offset": start_offset},
            json=body,
        )
        return {
            "professionals": single.get("result") or [],
            "page": single.get("page") or {},
            "warnings": None,
            "continuation": None,
        }
