from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import people_read

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register_creates_four_tools(tool_context) -> None:
    mcp = register_module(people_read, tool_context)
    assert tool_names(mcp) == {
        "accela_get_contact",
        "accela_search_contacts",
        "accela_get_professional",
        "accela_search_professionals",
    }


@pytest.mark.asyncio
@respx.mock
async def test_get_contact(tool_context) -> None:
    respx.get("https://apis.test.example/v4/contacts/1,2").mock(
        return_value=Response(200, json={"result": [{"id": "1"}, {"id": "2"}]})
    )
    mcp = register_module(people_read, tool_context)
    out = await call(mcp, "accela_get_contact")(contact_ids=["1", "2"])
    assert len(out["contacts"]) == 2


@pytest.mark.asyncio
@respx.mock
async def test_search_contacts_requires_at_least_one_field(tool_context) -> None:
    mcp = register_module(people_read, tool_context)
    out = await call(mcp, "accela_search_contacts")()
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
@respx.mock
async def test_search_contacts_by_email(tool_context) -> None:
    respx.post("https://apis.test.example/v4/search/contacts").mock(
        return_value=Response(200, json={"result": [{"id": "x"}], "page": {"hasmore": False}})
    )
    mcp = register_module(people_read, tool_context)
    out = await call(mcp, "accela_search_contacts")(email="alice@example.com")
    assert out["contacts"] == [{"id": "x"}]
    assert out["continuation"] is None


@pytest.mark.asyncio
@respx.mock
async def test_search_contacts_returns_continuation_at_cap(tool_context) -> None:
    respx.post("https://apis.test.example/v4/search/contacts").mock(
        return_value=Response(
            200,
            json={
                "page": {"offset": 0, "limit": 100, "hasmore": True},
                "result": [{"id": str(i)} for i in range(100)],
            },
        )
    )
    mcp = register_module(people_read, tool_context)
    out = await call(mcp, "accela_search_contacts")(email="alice@example.com", max_results=200)
    assert len(out["contacts"]) == 200
    assert out["continuation"] == {"next_offset": 200, "max_results_cap": 200}


@pytest.mark.asyncio
@respx.mock
async def test_get_professional(tool_context) -> None:
    respx.get("https://apis.test.example/v4/professionals/A1").mock(
        return_value=Response(200, json={"result": [{"id": "A1", "licenseNumber": "12345"}]})
    )
    mcp = register_module(people_read, tool_context)
    out = await call(mcp, "accela_get_professional")(professional_ids=["A1"])
    assert out["professionals"][0]["licenseNumber"] == "12345"


@pytest.mark.asyncio
@respx.mock
async def test_search_professionals_by_license_number(tool_context) -> None:
    respx.post("https://apis.test.example/v4/search/professionals").mock(
        return_value=Response(200, json={"result": [{"id": "p1"}], "page": {"hasmore": False}})
    )
    mcp = register_module(people_read, tool_context)
    out = await call(mcp, "accela_search_professionals")(license_number="12345")
    assert out["professionals"] == [{"id": "p1"}]
    assert out["continuation"] is None


@pytest.mark.asyncio
@respx.mock
async def test_search_professionals_single_page_mode(tool_context) -> None:
    route = respx.post("https://apis.test.example/v4/search/professionals").mock(
        return_value=Response(
            200,
            json={
                "page": {"offset": 0, "limit": 100, "hasmore": True},
                "result": [{"id": str(i)} for i in range(100)],
            },
        )
    )
    mcp = register_module(people_read, tool_context)
    out = await call(mcp, "accela_search_professionals")(
        license_number="12345", auto_paginate=False, limit=100
    )
    # Single page: only one HTTP call regardless of hasmore.
    assert route.call_count == 1
    assert len(out["professionals"]) == 100
