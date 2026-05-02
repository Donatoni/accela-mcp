from __future__ import annotations

import base64

import pytest
import respx
from httpx import Response

from accela_mcp.tools import documents_read

from ._helpers import call, register_module


@pytest.mark.asyncio
@respx.mock
async def test_list_record_documents(tool_context) -> None:
    respx.get("https://apis.test.example/v4/records/ISLANDTON-1-2-3/documents").mock(
        return_value=Response(
            200,
            json={"result": [{"id": "1", "fileName": "site.pdf", "fileSize": 1234}]},
        )
    )
    mcp = register_module(documents_read, tool_context)
    out = await call(mcp, "accela_list_record_documents")(record_id="ISLANDTON-1-2-3")
    assert out["documents"][0]["fileName"] == "site.pdf"


@pytest.mark.asyncio
@respx.mock
async def test_download_document_returns_base64(tool_context) -> None:
    respx.get("https://apis.test.example/v4/documents/42/download").mock(
        return_value=Response(
            200,
            content=b"file-bytes",
            headers={
                "content-type": "application/pdf",
                "content-disposition": 'attachment; filename="site.pdf"',
            },
        )
    )
    mcp = register_module(documents_read, tool_context)
    out = await call(mcp, "accela_download_document")(document_id="42")
    assert base64.b64decode(out["content_base64"]) == b"file-bytes"
    assert out["content_type"] == "application/pdf"
    assert out["filename"] == "site.pdf"
    assert out["size_bytes"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_download_document_too_large(tool_context, monkeypatch) -> None:
    monkeypatch.setattr(documents_read, "MAX_DOWNLOAD_BYTES", 5)
    respx.get("https://apis.test.example/v4/documents/42/download").mock(
        return_value=Response(
            200, content=b"way too many bytes", headers={"content-type": "text/plain"}
        )
    )
    mcp = register_module(documents_read, tool_context)
    out = await call(mcp, "accela_download_document")(document_id="42")
    assert out["error"] == "document_too_large"


@pytest.mark.asyncio
@respx.mock
async def test_download_document_with_thumbnail(tool_context) -> None:
    respx.get("https://apis.test.example/v4/documents/42/download").mock(
        return_value=Response(
            200,
            content=b"main",
            headers={"content-type": "image/png"},
        )
    )
    respx.get("https://apis.test.example/v4/documents/42/thumbnail").mock(
        return_value=Response(
            200,
            content=b"thumb",
            headers={"content-type": "image/jpeg"},
        )
    )
    mcp = register_module(documents_read, tool_context)
    out = await call(mcp, "accela_download_document")(document_id="42", include_thumbnail=True)
    assert base64.b64decode(out["thumbnail_base64"]) == b"thumb"
    assert out["thumbnail_content_type"] == "image/jpeg"


@pytest.mark.asyncio
@respx.mock
async def test_download_document_thumbnail_failure_is_soft(tool_context) -> None:
    respx.get("https://apis.test.example/v4/documents/42/download").mock(
        return_value=Response(
            200,
            content=b"main",
            headers={"content-type": "image/png"},
        )
    )
    respx.get("https://apis.test.example/v4/documents/42/thumbnail").mock(
        return_value=Response(404, json={"code": "not_found", "message": "no thumb"})
    )
    mcp = register_module(documents_read, tool_context)
    out = await call(mcp, "accela_download_document")(document_id="42", include_thumbnail=True)
    assert "thumbnail_base64" not in out
    assert "thumbnail_error" in out


@pytest.mark.asyncio
async def test_download_document_validates_id(tool_context) -> None:
    mcp = register_module(documents_read, tool_context)
    out = await call(mcp, "accela_download_document")(document_id=" ")
    assert out["error"] == "invalid_input"
