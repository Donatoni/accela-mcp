from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
import respx
from httpx import Response

from accela_mcp.api.client import AccelaClient
from accela_mcp.capabilities import (
    AdminConfig,
    Capabilities,
    LoadedConfig,
    scopes_for,
)
from accela_mcp.settings import Settings
from accela_mcp.tools import admin_escape
from accela_mcp.tools._base import ToolContext
from accela_mcp.utils.cache import TTLCache

from ._helpers import call, register_module


@pytest_asyncio.fixture
async def admin_context(
    settings: Settings,
    client: AccelaClient,
) -> ToolContext:
    enabled = {"discovery", "admin_escape_hatch"}
    caps = Capabilities(
        version=1,
        agency="NULLISLAND",
        environment="TEST",
        enabled_groups=sorted(enabled),
        admin=AdminConfig(
            raw_request_allowed_paths=[r"^/v4/records(/.*)?$", r"^/v4/settings/.*$"],
            raw_request_allowed_methods=["GET", "POST"],
        ),
    )
    config = LoadedConfig(
        capabilities=caps,
        enabled_groups=enabled,
        scopes=scopes_for(enabled),
    )
    cache: TTLCache[dict[str, Any]] = TTLCache(ttl_seconds=60)
    return ToolContext(settings=settings, config=config, client=client, reference_cache=cache)


@pytest.mark.asyncio
@respx.mock
async def test_raw_request_allowed_get(admin_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-1-2-3").mock(
        return_value=Response(200, json={"result": [{"id": "x"}]})
    )
    mcp = register_module(admin_escape, admin_context)
    out = await call(mcp, "accela_raw_request")(method="GET", path="/v4/records/ISLANDTON-1-2-3")
    assert out == {"result": [{"id": "x"}]}


@pytest.mark.asyncio
async def test_raw_request_path_not_in_allowlist(admin_context) -> None:
    mcp = register_module(admin_escape, admin_context)
    out = await call(mcp, "accela_raw_request")(method="GET", path="/v4/inspections/1")
    assert out["error"] == "invalid_input"
    assert "allowlist" in out["message"]


@pytest.mark.asyncio
async def test_raw_request_method_not_in_allowlist(admin_context) -> None:
    mcp = register_module(admin_escape, admin_context)
    out = await call(mcp, "accela_raw_request")(method="DELETE", path="/v4/records/X")
    assert out["error"] == "invalid_input"
    assert "method" in out["message"].lower()


@pytest.mark.asyncio
async def test_raw_request_path_traversal_rejected(admin_context) -> None:
    mcp = register_module(admin_escape, admin_context)
    out = await call(mcp, "accela_raw_request")(method="GET", path="/v4/records/../../etc/passwd")
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
async def test_raw_request_non_v4_path_rejected(admin_context) -> None:
    mcp = register_module(admin_escape, admin_context)
    out = await call(mcp, "accela_raw_request")(method="GET", path="/v3/records/X")
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
async def test_raw_request_unknown_method_rejected(admin_context) -> None:
    mcp = register_module(admin_escape, admin_context)
    out = await call(mcp, "accela_raw_request")(method="WHAT", path="/v4/records/X")
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
@respx.mock
async def test_raw_request_post_with_body(admin_context) -> None:
    respx.post("https://apis.test.example/v4/records").mock(
        return_value=Response(200, json={"id": "new"})
    )
    mcp = register_module(admin_escape, admin_context)
    out = await call(mcp, "accela_raw_request")(
        method="POST",
        path="/v4/records",
        body={"description": "test"},
    )
    assert out == {"id": "new"}
