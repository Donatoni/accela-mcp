"""Records write tools — create (partial + finalize) and update.

Three tools:

  * `accela_create_record_partial` — POST `/v4/records?status=draft` (or
    similar). Creates an incomplete record. The intent is that the LLM
    pauses here, lets the user verify everything looks right, and then
    calls `finalize_record` separately. This is by design — single-shot
    creation is the easiest place to mass-create wrong records.
  * `accela_finalize_record` — PUT `/v4/records/{id}` to flip the record
    out of draft. Distinct call so the LLM has a clear pause boundary.
  * `accela_update_record` — PUT `/v4/records/{id}` for general updates.
    Supports `expected_status` precondition guard.

Every tool is dry-run by default.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.api.errors import AccelaAPIError
from accela_mcp.safety import WritePreview, write_tool
from accela_mcp.tools._base import ToolContext, destructive_annotations


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(annotations=destructive_annotations("Create Record (Partial)"))
    @write_tool("accela_create_record_partial", ctx)
    async def accela_create_record_partial(
        record_type: str,
        description: str | None = None,
        short_notes: str | None = None,
        addresses: list[dict[str, Any]] | None = None,
        contacts: list[dict[str, Any]] | None = None,
        parcels: list[dict[str, Any]] | None = None,
        custom_forms: list[dict[str, Any]] | None = None,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ Mutates Accela data. **Default is dry-run** — show the
        returned preview to the human user and only re-invoke with
        `confirm=True` after they approve.

        Creates a *partial* (draft) record. Two-step on purpose: the LLM
        should call this, surface the new record's ID and shape to the
        user, and only then call `accela_finalize_record` after the human
        verifies. Reduces the blast radius of misclassified record types.

        `record_type` is the canonical 4-part path
        `Module/Group/Type/SubType`. Always check
        `accela_describe_record_metadata` first — agency-specific custom
        forms have hidden required fields."""
        if not record_type or not record_type.strip():
            raise ValueError("record_type is required")

        body: dict[str, Any] = {"type": {"id": _record_type_to_id(record_type)}}
        if description:
            body["description"] = description
        if short_notes:
            body["shortNotes"] = short_notes
        if addresses:
            body["addresses"] = addresses
        if contacts:
            body["contacts"] = contacts
        if parcels:
            body["parcels"] = parcels
        if custom_forms:
            body["customForms"] = custom_forms

        path = "/v4/records"
        params = {"status": "draft"}

        if not confirm:
            return WritePreview(
                tool="accela_create_record_partial",
                method="POST",
                path=path,
                summary=f"Create draft record of type {record_type!r}",
                body=body,
                query_params=params,
            )

        response = await ctx.client.post(path, params=params, json=body)
        return {
            "method": "POST",
            "path": path,
            "request_body": body,
            "result_status": int(response.get("status", 200)),
            "result_id": _result_id(response),
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }

    @mcp.tool(annotations=destructive_annotations("Finalize Record"))
    @write_tool("accela_finalize_record", ctx)
    async def accela_finalize_record(
        record_id: str,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ Mutates Accela data. **Default is dry-run** — show the
        returned preview to the human user and only re-invoke with
        `confirm=True` after they approve.

        Promotes a draft record to a fully-submitted record. After this,
        the record is visible to staff and starts triggering workflow.
        Once finalized, you can't easily revert."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")

        body = {"recordStatus": {"value": "Submitted"}}
        path = f"/v4/records/{record_id}"

        if not confirm:
            return WritePreview(
                tool="accela_finalize_record",
                method="PUT",
                path=path,
                summary=(
                    f"Finalize draft record {record_id!r} — moves it to Submitted "
                    "and starts agency workflow"
                ),
                body=body,
                irreversible=True,
            )

        response = await ctx.client.put(path, json=body)
        return {
            "method": "PUT",
            "path": path,
            "request_body": body,
            "result_status": int(response.get("status", 200)),
            "result_id": record_id,
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }

    @mcp.tool(annotations=destructive_annotations("Update Record"))
    @write_tool("accela_update_record", ctx)
    async def accela_update_record(
        record_id: str,
        updates: dict[str, Any],
        expected_status: str | None = None,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ Mutates Accela data. **Default is dry-run** — show the
        returned preview to the human user and only re-invoke with
        `confirm=True` after they approve.

        Updates fields on an existing record. `updates` is a partial
        record body (top-level fields like `description`, `shortNotes`,
        `assignedToDepartment`, etc.). `expected_status` is a precondition
        guard: if set and the record's current status doesn't match, the
        update is refused — protects against the LLM updating the wrong
        record after a misread."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty object")

        path = f"/v4/records/{record_id}"

        if confirm and expected_status:
            current = await _read_record_status(ctx, record_id)
            if current is not None and current.lower() != expected_status.lower():
                return {
                    "error": "precondition_failed",
                    "message": (
                        f"expected_status was {expected_status!r} but the "
                        f"record's current status is {current!r}. Refusing to "
                        "update — verify with the user that this is the right "
                        "record before retrying."
                    ),
                    "record_id": record_id,
                    "current_status": current,
                    "expected_status": expected_status,
                }

        if not confirm:
            return WritePreview(
                tool="accela_update_record",
                method="PUT",
                path=path,
                summary=(
                    f"Update record {record_id!r} fields: {sorted(updates.keys())}"
                    + (f" (precondition: status == {expected_status!r})" if expected_status else "")
                ),
                body=updates,
            )

        response = await ctx.client.put(path, json=updates)
        return {
            "method": "PUT",
            "path": path,
            "request_body": updates,
            "result_status": int(response.get("status", 200)),
            "result_id": record_id,
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }


def _record_type_to_id(value: str) -> str:
    """Convert a `Module/Group/Type/SubType` path into Accela's `id` form
    (`Module-Group-Type-SubType`). Accept either form on input."""
    if "/" in value:
        return value.replace("/", "-")
    return value


def _result_id(response: dict[str, Any]) -> str | None:
    result = response.get("result")
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            value = first.get("id")
            if value is not None:
                return str(value)
    if isinstance(result, dict):
        value = result.get("id")
        if value is not None:
            return str(value)
    return None


async def _read_record_status(ctx: ToolContext, record_id: str) -> str | None:
    """Best-effort read of the record's current status for the precondition
    check. Returns None if the read fails — we don't want a flaky read to
    permanently block writes; the operator can always re-call without
    `expected_status`."""
    try:
        payload = await ctx.client.get(f"/v4/records/{record_id}")
    except AccelaAPIError:
        return None
    result = payload.get("result")
    item = None
    if isinstance(result, list) and result:
        item = result[0]
    elif isinstance(result, dict):
        item = result
    if not isinstance(item, dict):
        return None
    status = item.get("status")
    if isinstance(status, dict):
        value = status.get("value") or status.get("text")
        return str(value) if value is not None else None
    if isinstance(status, str):
        return status
    return None
