"""Documents write tools — upload a document to a record.

Uses the legacy `POST /v4/records/{recordId}/documents` endpoint, which is
multipart/form-data with two parts: a `fileInfos` JSON array of metadata
and one or more `uploadedFile` binary parts. The newer ACDS chunked
upload service is out of scope for this version (a separate group later).

The tool accepts base64-encoded content inline so an LLM can pass through
small files captured elsewhere in the conversation. Larger files (>20 MB
inline) are refused — Accela's gateway and the MCP transport both choke
on bigger payloads. For those, the agency UI is the right path.
"""

from __future__ import annotations

import base64
from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.safety import WritePreview, write_tool
from accela_mcp.tools._base import ToolContext, destructive_annotations

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB raw — under the 25 MB inline-download cap


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=destructive_annotations("Upload Document to Record"))
    @write_tool("accela_upload_document_to_record", ctx)
    async def accela_upload_document_to_record(
        record_id: str,
        filename: str,
        content_base64: str,
        content_type: str = "application/octet-stream",
        description: str | None = None,
        document_category: str | None = None,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ Mutates Accela data. **Default is dry-run** — show the
        returned preview to the human user and only re-invoke with
        `confirm=True` after they approve.

        Uploads a document to a record. Pass file content as base64 in
        `content_base64`. Files larger than 20 MB are refused — for those,
        upload via the agency's UI. `document_category` is agency-defined;
        check the agency's documents settings for valid values."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        if not filename or not filename.strip():
            raise ValueError("filename is required")
        if not content_base64:
            raise ValueError("content_base64 is required")

        try:
            raw = base64.b64decode(content_base64, validate=True)
        except (ValueError, TypeError) as e:
            raise ValueError(f"content_base64 is not valid base64: {e}") from e

        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError(
                f"File is {len(raw)} bytes; refusing to upload more than "
                f"{MAX_UPLOAD_BYTES} bytes inline. Use the agency UI for larger files."
            )

        file_info: dict[str, Any] = {
            "serviceProviderCode": ctx.client.agency,
            "fileName": filename,
            "type": content_type,
        }
        if description:
            file_info["description"] = description
        if document_category:
            file_info["category"] = document_category

        path = f"/v4/records/{record_id}/documents"

        if not confirm:
            return WritePreview(
                tool="accela_upload_document_to_record",
                method="POST",
                path=path,
                summary=(
                    f"Upload {filename!r} ({len(raw)} bytes, {content_type}) "
                    f"to record {record_id!r}"
                ),
                body={
                    "fileInfos": [file_info],
                    "_file_size_bytes": len(raw),
                    "_file_omitted_in_preview": True,
                },
            )

        # Multipart payload: a JSON `fileInfos` part + one binary part.
        files = {
            "fileInfos": (None, _serialize_file_infos([file_info]), "application/json"),
            "uploadedFile": (filename, raw, content_type),
        }
        response = await ctx.client.request(
            "POST",
            path,
            files=files,
        )
        return {
            "method": "POST",
            "path": path,
            "request_body": {"fileInfos": [file_info], "size_bytes": len(raw)},
            "result_status": int(response.get("status", 200)),
            "result_id": _document_id(response),
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }


def _serialize_file_infos(infos: list[dict[str, Any]]) -> str:
    import json as _json

    return _json.dumps(infos)


def _document_id(response: dict[str, Any]) -> str | None:
    result = response.get("result")
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            value = first.get("id") or first.get("documentId")
            if value is not None:
                return str(value)
    if isinstance(result, dict):
        value = result.get("id") or result.get("documentId")
        if value is not None:
            return str(value)
    return None
