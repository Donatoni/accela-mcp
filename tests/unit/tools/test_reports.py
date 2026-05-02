from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.tools import reports

from ._helpers import call, register_module, tool_names


@pytest.mark.asyncio
async def test_register(tool_context) -> None:
    mcp = register_module(reports, tool_context)
    assert tool_names(mcp) == {"accela_list_reports", "accela_run_report"}


@pytest.mark.asyncio
@respx.mock
async def test_list_reports(tool_context) -> None:
    respx.get("https://apis.test.example/v4/reports").mock(
        return_value=Response(200, json={"result": [{"id": "R1", "name": "By Module"}]})
    )
    mcp = register_module(reports, tool_context)
    out = await call(mcp, "accela_list_reports")()
    assert out["reports"] == [{"id": "R1", "name": "By Module"}]


@pytest.mark.asyncio
@respx.mock
async def test_list_reports_with_module(tool_context) -> None:
    route = respx.get("https://apis.test.example/v4/reports").mock(
        return_value=Response(200, json={"result": []})
    )
    mcp = register_module(reports, tool_context)
    await call(mcp, "accela_list_reports")(module="Building")
    assert "module=Building" in str(route.calls.last.request.url)


@pytest.mark.asyncio
@respx.mock
async def test_run_report(tool_context) -> None:
    respx.post("https://apis.test.example/v4/reports/R1/run").mock(
        return_value=Response(200, json={"result": [{"row": 1}]})
    )
    mcp = register_module(reports, tool_context)
    out = await call(mcp, "accela_run_report")(report_id="R1", parameters={"x": 1})
    assert out["result"] == [{"row": 1}]


@pytest.mark.asyncio
async def test_run_report_validates(tool_context) -> None:
    mcp = register_module(reports, tool_context)
    out = await call(mcp, "accela_run_report")(report_id="")
    assert out["error"] == "invalid_input"
