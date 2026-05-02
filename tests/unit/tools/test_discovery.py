from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import discovery

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register_creates_three_tools(tool_context) -> None:
    mcp = register_module(discovery, tool_context)
    assert tool_names(mcp) == {
        "accela_list_capabilities",
        "accela_get_agency",
        "accela_describe_record_metadata",
    }


@pytest.mark.asyncio
async def test_list_capabilities_reports_state(tool_context) -> None:
    mcp = register_module(discovery, tool_context)
    out = await call(mcp, "accela_list_capabilities")()
    assert out["agency"] == "NULLISLAND"
    assert out["environment"] == "TEST"
    assert "discovery" in out["enabled_groups"]
    assert "accela_get_agency" in out["tools_by_group"]["discovery"]


@pytest.mark.asyncio
@respx.mock
async def test_get_agency_calls_v4_agencies(tool_context) -> None:
    respx.get("https://apis.test.example/v4/agencies/NULLISLAND").mock(
        return_value=Response(200, json={"name": "NULLISLAND", "country": "US"})
    )
    mcp = register_module(discovery, tool_context)
    out = await call(mcp, "accela_get_agency")()
    assert out["name"] == "NULLISLAND"


@pytest.mark.asyncio
@respx.mock
async def test_describe_metadata_by_record_type(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/describe/create").mock(
        return_value=Response(200, json={"required": ["module"]})
    )
    mcp = register_module(discovery, tool_context)
    fn = call(mcp, "accela_describe_record_metadata")
    out = await fn(record_type="Building/Residential/Alteration/NA")
    assert out["create_describe"]["required"] == ["module"]


@pytest.mark.asyncio
@respx.mock
async def test_describe_metadata_by_record_id(tool_context) -> None:
    respx.get(
        "https://apis.test.example/v4/records/ISLANDTON-14CAP-00000-000I4/customForms/meta"
    ).mock(return_value=Response(200, json={"forms": []}))
    respx.get(
        "https://apis.test.example/v4/records/ISLANDTON-14CAP-00000-000I4/customTables/meta"
    ).mock(return_value=Response(200, json={"tables": []}))
    mcp = register_module(discovery, tool_context)
    out = await call(mcp, "accela_describe_record_metadata")(
        record_id="ISLANDTON-14CAP-00000-000I4"
    )
    assert "custom_forms_meta" in out
    assert "custom_tables_meta" in out


@pytest.mark.asyncio
async def test_describe_metadata_requires_one_arg(tool_context) -> None:
    mcp = register_module(discovery, tool_context)
    out = await call(mcp, "accela_describe_record_metadata")()
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
async def test_describe_metadata_rejects_both_args(tool_context) -> None:
    mcp = register_module(discovery, tool_context)
    out = await call(mcp, "accela_describe_record_metadata")(
        record_id="ISLANDTON-1-2-3", record_type="Building/Residential/Alteration/NA"
    )
    assert out["error"] == "invalid_input"
