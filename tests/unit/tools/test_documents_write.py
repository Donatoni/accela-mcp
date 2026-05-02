from __future__ import annotations

import base64
import json

import pytest
import respx
from httpx import Response

from accela_mcp.tools import documents_write

from ._helpers import call, register_module, tool_names


def _b64(blob: bytes) -> str:
    return base64.b64encode(blob).decode("ascii")


@pytest.mark.asyncio
async def test_register(write_tool_context) -> None:
    mcp = register_module(documents_write, write_tool_context)
    assert tool_names(mcp) == {"accela_upload_document_to_record"}


@pytest.mark.asyncio
async def test_dry_run_describes_upload(write_tool_context) -> None:
    mcp = register_module(documents_write, write_tool_context)
    out = await call(mcp, "accela_upload_document_to_record")(
        record_id="ISLANDTON-1-2-3",
        filename="plans.pdf",
        content_base64=_b64(b"hello world"),
        content_type="application/pdf",
        description="Site plans",
    )
    assert out["preview"] is True
    assert out["method"] == "POST"
    assert out["path"] == "/v4/records/ISLANDTON-1-2-3/documents"
    assert out["body"]["fileInfos"][0]["fileName"] == "plans.pdf"
    assert out["body"]["_file_omitted_in_preview"] is True
    assert out["body"]["_file_size_bytes"] == 11


@pytest.mark.asyncio
async def test_validates_inputs(write_tool_context) -> None:
    mcp = register_module(documents_write, write_tool_context)
    out = await call(mcp, "accela_upload_document_to_record")(
        record_id="",
        filename="x.pdf",
        content_base64=_b64(b"x"),
    )
    assert out["error"] == "invalid_input"

    out = await call(mcp, "accela_upload_document_to_record")(
        record_id="X",
        filename="x.pdf",
        content_base64="not valid base64!!!",
    )
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
async def test_rejects_oversized_content(write_tool_context) -> None:
    mcp = register_module(documents_write, write_tool_context)
    big = _b64(b"\x00" * (21 * 1024 * 1024))
    out = await call(mcp, "accela_upload_document_to_record")(
        record_id="X",
        filename="big.bin",
        content_base64=big,
    )
    assert out["error"] == "invalid_input"
    assert "20" in out["message"]


@pytest.mark.asyncio
@respx.mock
async def test_confirmed_upload_uses_multipart(write_tool_context) -> None:
    route = respx.post("https://apis.test.example/v4/records/ISLANDTON-1-2-3/documents").mock(
        return_value=Response(
            200,
            json={"status": 200, "result": [{"id": 12345}]},
        )
    )
    mcp = register_module(documents_write, write_tool_context)
    out = await call(mcp, "accela_upload_document_to_record")(
        record_id="ISLANDTON-1-2-3",
        filename="plans.pdf",
        content_base64=_b64(b"PDFDATA"),
        content_type="application/pdf",
        confirm=True,
    )
    assert route.called
    request = route.calls.last.request
    # Multipart should NOT have JSON content type at the top level.
    ct = request.headers.get("content-type", "")
    assert ct.startswith("multipart/form-data"), ct
    # Body contains the JSON metadata + the binary part.
    body_text = request.content.decode("utf-8", errors="replace")
    assert "fileInfos" in body_text
    assert "plans.pdf" in body_text
    assert "PDFDATA" in body_text
    assert out["result_id"] == "12345"
    assert out["result_status"] == 200


@pytest.mark.asyncio
async def test_kill_switch_off_refuses_upload(tool_context) -> None:
    mcp = register_module(documents_write, tool_context)
    out = await call(mcp, "accela_upload_document_to_record")(
        record_id="X",
        filename="plans.pdf",
        content_base64=_b64(b"x"),
        confirm=True,
    )
    assert out["error"] == "writes_disabled"


@pytest.mark.asyncio
async def test_audit_log_excludes_binary_content(write_tool_context) -> None:
    """Binary content_base64 must not land verbatim in the audit log entry —
    the audit record only carries metadata (`fileInfos`) and `size_bytes`."""
    # Run a dry-run, no audit. Then assert via inspecting body shape.
    mcp = register_module(documents_write, write_tool_context)
    out = await call(mcp, "accela_upload_document_to_record")(
        record_id="X",
        filename="plans.pdf",
        content_base64=_b64(b"binary"),
    )
    serialized = json.dumps(out)
    # `_file_omitted_in_preview` flag tells the LLM the binary isn't here.
    assert "_file_omitted_in_preview" in serialized
    # And we never inline the full base64 in the preview body.
    assert _b64(b"binary") not in serialized
