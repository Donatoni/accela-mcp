"""GIS tools — geocode and reverse-geocode helpers.

Both are read-only — `gis` doesn't include any write tools. They go
through the GIS scope on the access token; require `gis` group enabled
in capabilities.yaml.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import ToolContext, read_only_annotations, tool_call


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=read_only_annotations("Geocode"))
    @tool_call("accela_geocode")
    async def accela_geocode(
        address: str | None = None,
        street: str | None = None,
        city: str | None = None,
        state: str | None = None,
        postal_code: str | None = None,
    ) -> dict[str, Any]:
        """Forward-geocode an address to lat/long coordinates. Pass either a
        free-form `address` or any combination of street/city/state/postal_code.
        At least one must be provided."""
        if not any([address, street, city, state, postal_code]):
            raise ValueError(
                "At least one of address, street, city, state, postal_code is required"
            )
        params: dict[str, Any] = {}
        if address:
            params["address"] = address
        if street:
            params["street"] = street
        if city:
            params["city"] = city
        if state:
            params["state"] = state
        if postal_code:
            params["postalCode"] = postal_code

        result = await ctx.client.get("/v4/gis/geocode", params=params)
        return {"matches": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("Reverse Geocode"))
    @tool_call("accela_reverse_geocode")
    async def accela_reverse_geocode(
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:
        """Reverse-geocode a lat/long pair to the nearest known address(es)
        in the agency's GIS layer."""
        if latitude is None or longitude is None:
            raise ValueError("latitude and longitude are required")
        params = {"latitude": float(latitude), "longitude": float(longitude)}
        result = await ctx.client.get("/v4/gis/reverseGeocode", params=params)
        return {"matches": result.get("result") or []}
