"""Documents read tools — list documents on a record and download content."""

from __future__ import annotations

import base64
from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import ToolContext, read_only_annotations, tool_call

# Keep base64 payloads bounded so we don't fill the MCP transport with huge
# binaries. Tools should refuse to return more than this; for big files the
# operator can wire up an out-of-band fetch path. 25 MB raw → ~33 MB base64.
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=read_only_annotations("List Record Documents"))
    @tool_call("accela_list_record_documents")
    async def accela_list_record_documents(record_id: str) -> dict[str, Any]:
        """Lists documents attached to a record (filenames, types, sizes,
        upload metadata). Does NOT download content — use
        `accela_download_document` with a returned document ID for that."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        result = await ctx.client.get(f"/v4/records/{record_id}/documents")
        return {"documents": result.get("result") or []}

    @mcp.tool(annotations=read_only_annotations("Download Document"))
    @tool_call("accela_download_document")
    async def accela_download_document(
        document_id: str,
        include_thumbnail: bool = False,
    ) -> dict[str, Any]:
        """Downloads a document's binary content. Returns base64-encoded bytes
        plus content-type. Files larger than 25 MB are refused — fetch the
        record's metadata via `accela_list_record_documents` to see the size
        first. Optionally returns a base64 thumbnail when `include_thumbnail`
        is true (best-effort; non-image documents typically have none)."""
        if not document_id or not document_id.strip():
            raise ValueError("document_id is required")

        response = await ctx.client.request_raw("GET", f"/v4/documents/{document_id}/download")
        content = response.content
        if len(content) > MAX_DOWNLOAD_BYTES:
            return {
                "error": "document_too_large",
                "message": (
                    f"Document is {len(content)} bytes; refusing to inline more "
                    f"than {MAX_DOWNLOAD_BYTES} bytes via this tool."
                ),
                "document_id": document_id,
                "size_bytes": len(content),
            }

        out: dict[str, Any] = {
            "document_id": document_id,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "content_type": response.headers.get("content-type", "application/octet-stream"),
            "size_bytes": len(content),
        }
        # Try to extract a filename from Content-Disposition.
        disp = response.headers.get("content-disposition") or ""
        if "filename=" in disp:
            out["filename"] = disp.split("filename=", 1)[1].strip().strip('"').split(";")[0].strip()

        if include_thumbnail:
            try:
                thumb_resp = await ctx.client.request_raw(
                    "GET", f"/v4/documents/{document_id}/thumbnail"
                )
                if thumb_resp.content and len(thumb_resp.content) <= MAX_DOWNLOAD_BYTES:
                    out["thumbnail_base64"] = base64.b64encode(thumb_resp.content).decode("ascii")
                    out["thumbnail_content_type"] = thumb_resp.headers.get(
                        "content-type", "image/jpeg"
                    )
            except Exception as e:
                out["thumbnail_error"] = str(e)

        return out
