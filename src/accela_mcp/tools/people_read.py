"""People read tools — contacts and licensed professionals."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import (
    ToolContext,
    clamp_limit,
    clamp_offset,
    tool_call,
)
from accela_mcp.utils.ids import join_ids


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool()
    @tool_call("accela_get_contact")
    async def accela_get_contact(contact_ids: list[str]) -> dict[str, Any]:
        """Retrieves one or more contacts by ID."""
        joined = join_ids(contact_ids)
        result = await ctx.client.get(f"/v4/contacts/{joined}")
        return {"contacts": result.get("result") or []}

    @mcp.tool()
    @tool_call("accela_search_contacts")
    async def accela_search_contacts(
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        contact_type: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Searches contacts by name, email, phone, or contact type. At least
        one search field is required. Returns a paginated list of contact
        summaries."""
        if not any([name, email, phone, contact_type]):
            raise ValueError("Provide at least one of name, email, phone, contact_type")
        body: dict[str, Any] = {
            "fullName": name,
            "email": email,
            "phone": phone,
            "type": {"value": contact_type} if contact_type else None,
        }
        body = {k: v for k, v in body.items() if v is not None}
        result = await ctx.client.post(
            "/v4/search/contacts",
            params={"limit": clamp_limit(limit), "offset": clamp_offset(offset)},
            json=body,
        )
        return {
            "contacts": result.get("result") or [],
            "page": result.get("page") or {},
        }

    @mcp.tool()
    @tool_call("accela_get_professional")
    async def accela_get_professional(professional_ids: list[str]) -> dict[str, Any]:
        """Retrieves one or more licensed professionals by ID, including
        license number and license type."""
        joined = join_ids(professional_ids)
        result = await ctx.client.get(f"/v4/professionals/{joined}")
        return {"professionals": result.get("result") or []}

    @mcp.tool()
    @tool_call("accela_search_professionals")
    async def accela_search_professionals(
        name: str | None = None,
        license_number: str | None = None,
        license_type: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Searches licensed professionals by name, license number, or license
        type. At least one search field is required."""
        if not any([name, license_number, license_type]):
            raise ValueError("Provide at least one of name, license_number, license_type")
        body: dict[str, Any] = {
            "fullName": name,
            "licenseNumber": license_number,
            "licenseType": license_type,
        }
        body = {k: v for k, v in body.items() if v is not None}
        result = await ctx.client.post(
            "/v4/search/professionals",
            params={"limit": clamp_limit(limit), "offset": clamp_offset(offset)},
            json=body,
        )
        return {
            "professionals": result.get("result") or [],
            "page": result.get("page") or {},
        }
