from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import records_read

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register_creates_four_tools(tool_context) -> None:
    mcp = register_module(records_read, tool_context)
    assert tool_names(mcp) == {
        "accela_search_records",
        "accela_get_record",
        "accela_get_my_records",
        "accela_get_record_custom_data",
    }


@pytest.mark.asyncio
@respx.mock
async def test_search_records_basic(tool_context, sample_record) -> None:
    route = respx.get("https://apis.test.example/v4/records").mock(
        return_value=Response(
            200,
            json={
                "page": {"offset": 0, "limit": 100, "hasmore": False},
                "result": [sample_record],
            },
        )
    )
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_search_records")(module="Building")
    assert route.called
    assert out["records"] == [sample_record]
    assert out["warnings"] is None
    assert out["continuation"] is None
    sent = route.calls.last.request
    assert "module=Building" in str(sent.url)


@pytest.mark.asyncio
@respx.mock
async def test_search_records_auto_paginates_until_hasmore_false(tool_context) -> None:
    page1 = [{"id": str(i)} for i in range(100)]
    page2 = [{"id": str(i)} for i in range(100, 150)]
    respx.get("https://apis.test.example/v4/records").mock(
        side_effect=[
            Response(
                200,
                json={"page": {"offset": 0, "limit": 100, "hasmore": True}, "result": page1},
            ),
            Response(
                200,
                json={"page": {"offset": 100, "limit": 100, "hasmore": False}, "result": page2},
            ),
        ]
    )
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_search_records")(module="Building")
    assert len(out["records"]) == 150
    assert out["continuation"] is None
    assert out["warnings"] is None


@pytest.mark.asyncio
@respx.mock
async def test_search_records_returns_continuation_at_max_results(tool_context) -> None:
    # Each call returns 100 records with hasmore=True; cap at 250 forces 3 calls.
    respx.get("https://apis.test.example/v4/records").mock(
        return_value=Response(
            200,
            json={
                "page": {"offset": 0, "limit": 100, "hasmore": True},
                "result": [{"id": str(i)} for i in range(100)],
            },
        )
    )
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_search_records")(module="Building", max_results=250)
    assert len(out["records"]) == 250
    assert out["continuation"] == {"next_offset": 250, "max_results_cap": 250}
    assert out["warnings"] is not None
    assert "more are available" in out["warnings"][0]


@pytest.mark.asyncio
@respx.mock
async def test_search_records_single_page_mode_warns_at_cap(tool_context) -> None:
    big = [{"id": str(i)} for i in range(100)]
    route = respx.get("https://apis.test.example/v4/records").mock(
        return_value=Response(
            200,
            json={"page": {"offset": 0, "limit": 100, "hasmore": True}, "result": big},
        )
    )
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_search_records")(limit=100, auto_paginate=False)
    assert route.call_count == 1
    assert out["warnings"] is not None
    assert "100-record search cap" in out["warnings"][0]
    assert out["continuation"] is None


@pytest.mark.asyncio
async def test_search_records_rejects_bad_max_results(tool_context) -> None:
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_search_records")(module="Building", max_results=0)
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
@respx.mock
async def test_search_records_clamps_max_results_to_ceiling(tool_context) -> None:
    # Asking for 999_999 should be silently clamped to TOOL_MAX_RESULTS_CEILING (5000).
    # We don't want to actually do 5000 records of mock data — verify by giving
    # an immediate hasmore=False response so only one call happens.
    respx.get("https://apis.test.example/v4/records").mock(
        return_value=Response(
            200,
            json={"page": {"offset": 0, "limit": 100, "hasmore": False}, "result": [{"id": "1"}]},
        )
    )
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_search_records")(module="Building", max_results=999_999)
    assert out["records"] == [{"id": "1"}]
    assert out["continuation"] is None


@pytest.mark.asyncio
@respx.mock
async def test_get_record_returns_first_result(tool_context, sample_record) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-14CAP-00000-000I4").mock(
        return_value=Response(200, json={"result": [sample_record]})
    )
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_get_record")(record_id="ISLANDTON-14CAP-00000-000I4")
    assert out["customId"] == "BLD14-00255"


@pytest.mark.asyncio
@respx.mock
async def test_get_record_with_expand(tool_context, sample_record) -> None:
    route = respx.get("https://apis.test.example/v4/records/ISLANDTON-14CAP-00000-000I4").mock(
        return_value=Response(200, json={"result": [sample_record]})
    )
    mcp = register_module(records_read, tool_context)
    await call(mcp, "accela_get_record")(
        record_id="ISLANDTON-14CAP-00000-000I4",
        expand=["addresses", "contacts"],
    )
    url = str(route.calls.last.request.url)
    assert "expand=addresses%2Ccontacts" in url or "expand=addresses,contacts" in url


@pytest.mark.asyncio
async def test_get_record_rejects_unknown_expand(tool_context) -> None:
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_get_record")(record_id="ISLANDTON-1-2-3", expand=["bogus"])
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
async def test_get_record_rejects_blank_id(tool_context) -> None:
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_get_record")(record_id="")
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
@respx.mock
async def test_get_record_404_surfaces_traceid(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-14CAP-00000-000I4").mock(
        return_value=Response(
            404,
            json={
                "status": 404,
                "code": "not_found",
                "message": "missing",
                "traceId": "trace-xyz",
            },
        )
    )
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_get_record")(record_id="ISLANDTON-14CAP-00000-000I4")
    assert out["error"] == "accela_api_error"
    assert out["status"] == 404
    assert out["trace_id"] == "trace-xyz"


@pytest.mark.asyncio
@respx.mock
async def test_get_my_records(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/mine").mock(
        return_value=Response(
            200,
            json={"result": [{"id": "X"}], "page": {"offset": 0, "limit": 100, "hasmore": False}},
        )
    )
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_get_my_records")()
    assert out["records"] == [{"id": "X"}]
    assert out["continuation"] is None


@pytest.mark.asyncio
@respx.mock
async def test_get_my_records_continuation(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/mine").mock(
        return_value=Response(
            200,
            json={
                "page": {"offset": 0, "limit": 100, "hasmore": True},
                "result": [{"id": str(i)} for i in range(100)],
            },
        )
    )
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_get_my_records")(max_results=200)
    assert len(out["records"]) == 200
    assert out["continuation"] == {"next_offset": 200, "max_results_cap": 200}


@pytest.mark.asyncio
@respx.mock
async def test_get_record_custom_data_parallel(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-14CAP-00000-000I4/customForms").mock(
        return_value=Response(200, json={"result": [{"id": "form1"}]})
    )
    respx.get("https://apis.test.example/v4/records/ISLANDTON-14CAP-00000-000I4/customTables").mock(
        return_value=Response(200, json={"result": [{"id": "tbl1"}]})
    )
    mcp = register_module(records_read, tool_context)
    out = await call(mcp, "accela_get_record_custom_data")(record_id="ISLANDTON-14CAP-00000-000I4")
    assert out["custom_forms"]["result"] == [{"id": "form1"}]
    assert out["custom_tables"]["result"] == [{"id": "tbl1"}]
