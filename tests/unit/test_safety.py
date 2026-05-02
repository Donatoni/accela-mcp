"""Unit tests for the write-tool safety scaffolding.

Covers the `WritePreview`/`write_tool` decorator behaviors, the `AuditLog`
file format, and the YAML cross-field validators that fail-loud when an
operator enables a write group without flipping the master kill-switch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from accela_mcp.capabilities import (
    Capabilities,
    PaymentsConfig,
    WritesConfig,
)
from accela_mcp.safety import (
    AuditLog,
    WritePreview,
    write_tool,
)

# ---------------------------------------------------------------- WritePreview


def test_write_preview_to_dict_shape() -> None:
    preview = WritePreview(
        tool="accela_update_record",
        method="PUT",
        path="/v4/records/X",
        summary="Update X status to Closed",
        body={"status": {"value": "Closed"}},
        irreversible=False,
    )
    out = preview.to_dict()
    assert out["preview"] is True
    assert out["confirmation_required"] is True
    assert out["tool"] == "accela_update_record"
    assert out["method"] == "PUT"
    assert out["body"] == {"status": {"value": "Closed"}}
    assert "confirm=True" in out["next_step"]


# -------------------------------------------------------------------- AuditLog


def test_audit_log_creates_file_with_0600_on_unix(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.log"
    AuditLog(audit_path)
    assert audit_path.exists()
    import os

    if os.name != "nt":
        mode = audit_path.stat().st_mode & 0o777
        assert mode == 0o600


def test_audit_log_writes_jsonline(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.log"
    audit = AuditLog(audit_path)
    audit.record(
        tool="accela_update_record",
        method="PUT",
        path="/v4/records/X",
        agency="NULLISLAND",
        environment="TEST",
        params={"record_id": "X", "confirm": True},
        body={"status": {"value": "Closed"}},
        result_status=200,
        result_id="X",
        trace_id="trace-xyz",
        duration_ms=42,
    )
    lines = audit_path.read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["tool"] == "accela_update_record"
    assert parsed["method"] == "PUT"
    assert parsed["agency"] == "NULLISLAND"
    assert parsed["environment"] == "TEST"
    assert parsed["params"]["record_id"] == "X"
    assert parsed["result_status"] == 200
    assert parsed["trace_id"] == "trace-xyz"
    assert parsed["body"] == {"status": {"value": "Closed"}}


def test_audit_log_redacts_secrets(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.log"
    audit = AuditLog(audit_path)
    audit.record(
        tool="accela_create_record_partial",
        method="POST",
        path="/v4/records",
        agency="NULLISLAND",
        environment="TEST",
        params={"access_token": "supersecret123", "type": "Building"},
        body={"contact": {"email": "alice@example.com", "first_name": "Alice"}},
        result_status=201,
    )
    parsed = json.loads(audit_path.read_text().strip().splitlines()[0])
    assert parsed["params"]["access_token"] == "***REDACTED***"
    # PII keys get partially masked, not stripped.
    assert parsed["body"]["contact"]["email"] != "alice@example.com"
    assert parsed["body"]["contact"]["email"].startswith("al")


def test_audit_log_no_path_falls_back_to_logger(tmp_path: Path) -> None:
    audit = AuditLog(None)
    # Should not raise; goes to structured logs only.
    audit.record(
        tool="accela_cancel_inspection",
        method="PUT",
        path="/v4/inspections/1",
        agency="NULLISLAND",
        environment="TEST",
        params={},
        body=None,
        result_status=200,
    )


# -------------------------------------------------------------- write_tool decorator


class _StubClient:
    def __init__(self, agency: str = "NULLISLAND", environment: str = "TEST") -> None:
        self.agency = agency
        self.environment = environment


class _StubCtx:
    def __init__(
        self,
        *,
        writes_enabled: bool = True,
        audit: AuditLog | None = None,
        agency_environment_allowed: list[str] | None = None,
        agency: str = "NULLISLAND",
        environment: str = "TEST",
    ) -> None:
        self.client = _StubClient(agency=agency, environment=environment)
        self.audit_log = audit
        self.writes_config = WritesConfig(
            enabled=writes_enabled,
            agency_environment_allowed=agency_environment_allowed or [],
        )


@pytest.mark.asyncio
async def test_write_tool_dry_run_returns_preview() -> None:
    ctx = _StubCtx()

    @write_tool("test_tool", ctx)
    async def my_tool(*, value: str, confirm: bool = False) -> Any:
        if not confirm:
            return WritePreview(
                tool="test_tool",
                method="PUT",
                path="/v4/something",
                summary=f"Set value to {value}",
                body={"value": value},
            )
        return {
            "result_status": 200,
            "method": "PUT",
            "path": "/v4/something",
        }

    out = await my_tool(value="x", confirm=False)
    assert out["preview"] is True
    assert out["confirmation_required"] is True
    assert out["body"] == {"value": "x"}


@pytest.mark.asyncio
async def test_write_tool_confirmed_call_passes_through() -> None:
    ctx = _StubCtx()

    @write_tool("test_tool", ctx)
    async def my_tool(*, confirm: bool = False) -> Any:
        return {
            "result_status": 200,
            "method": "PUT",
            "path": "/v4/something",
            "result_id": "ID1",
            "trace_id": "trace-1",
        }

    out = await my_tool(confirm=True)
    assert out["result_status"] == 200
    assert out["result_id"] == "ID1"


@pytest.mark.asyncio
async def test_write_tool_kill_switch_off_refuses_confirmed_call() -> None:
    ctx = _StubCtx(writes_enabled=False)

    @write_tool("test_tool", ctx)
    async def my_tool(*, confirm: bool = False) -> Any:
        # Should never be called when kill switch is off.
        raise AssertionError("write executed despite kill switch being off")

    out = await my_tool(confirm=True)
    assert out["error"] == "writes_disabled"
    assert "writes.enabled" in out["message"]


@pytest.mark.asyncio
async def test_write_tool_environment_not_allowed() -> None:
    ctx = _StubCtx(
        writes_enabled=True,
        agency_environment_allowed=["TEST"],
        environment="PROD",
    )

    @write_tool("test_tool", ctx)
    async def my_tool(*, confirm: bool = False) -> Any:
        raise AssertionError("write executed despite env allowlist mismatch")

    out = await my_tool(confirm=True)
    assert out["error"] == "writes_disabled"
    assert out["environment"] == "PROD"


@pytest.mark.asyncio
async def test_write_tool_audit_logs_confirmed_success(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.log")
    ctx = _StubCtx(audit=audit)

    @write_tool("test_tool", ctx)
    async def my_tool(*, confirm: bool = False) -> Any:
        return {
            "method": "POST",
            "path": "/v4/foo",
            "result_status": 201,
            "result_id": "Z1",
            "trace_id": "abc",
        }

    await my_tool(confirm=True)
    lines = (tmp_path / "audit.log").read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["tool"] == "test_tool"
    assert parsed["method"] == "POST"
    assert parsed["path"] == "/v4/foo"
    assert parsed["result_status"] == 201
    assert parsed["result_id"] == "Z1"


@pytest.mark.asyncio
async def test_write_tool_dry_run_does_not_audit(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.log")
    ctx = _StubCtx(audit=audit)

    @write_tool("test_tool", ctx)
    async def my_tool(*, confirm: bool = False) -> Any:
        return WritePreview(
            tool="test_tool",
            method="POST",
            path="/v4/foo",
            summary="Would create foo",
        )

    await my_tool(confirm=False)
    assert (tmp_path / "audit.log").read_text() == ""


@pytest.mark.asyncio
async def test_write_tool_invalid_input_returns_structured_error() -> None:
    ctx = _StubCtx()

    @write_tool("test_tool", ctx)
    async def my_tool(*, confirm: bool = False) -> Any:
        raise ValueError("bad input")

    out = await my_tool(confirm=False)
    assert out["error"] == "invalid_input"
    assert out["message"] == "bad input"


@pytest.mark.asyncio
async def test_write_tool_money_warning_in_preview() -> None:
    ctx = _StubCtx()

    @write_tool("test_tool", ctx, affects_money=True)
    async def my_tool(*, confirm: bool = False) -> Any:
        return WritePreview(
            tool="test_tool",
            method="POST",
            path="/v4/payments",
            summary="Charge $50",
        )

    out = await my_tool(confirm=False)
    assert out["affects_money"] is True
    assert any("financial" in w.lower() for w in (out.get("warnings") or []))


# ----------------------------------------------------- capabilities cross-validators


def test_writes_kill_switch_required_for_write_groups() -> None:
    with pytest.raises(ValidationError) as exc:
        Capabilities(
            version=1,
            agency="NULLISLAND",
            environment="TEST",
            enabled_groups=["records_read", "records_write"],
        )
    assert "writes.enabled" in str(exc.value)


def test_writes_enabled_allows_write_group() -> None:
    caps = Capabilities(
        version=1,
        agency="NULLISLAND",
        environment="TEST",
        enabled_groups=["records_read", "records_write"],
        writes=WritesConfig(enabled=True),
    )
    assert "records_write" in caps.resolved_groups()


def test_payments_real_money_against_prod_requires_friction_flag() -> None:
    with pytest.raises(ValidationError) as exc:
        Capabilities(
            version=1,
            agency="MYCITY",
            environment="PROD",
            enabled_groups=["payments_write"],
            writes=WritesConfig(enabled=True),
            payments=PaymentsConfig(real_money_allowed=True),
        )
    assert "i_understand_this_spends_real_money" in str(exc.value)


def test_payments_real_money_in_prod_with_friction_flag_ok() -> None:
    caps = Capabilities(
        version=1,
        agency="MYCITY",
        environment="PROD",
        enabled_groups=["payments_write"],
        writes=WritesConfig(enabled=True),
        payments=PaymentsConfig(
            real_money_allowed=True,
            i_understand_this_spends_real_money=True,
        ),
    )
    assert caps.payments.real_money_allowed is True


def test_payments_real_money_in_test_does_not_need_friction_flag() -> None:
    caps = Capabilities(
        version=1,
        agency="NULLISLAND",
        environment="TEST",
        enabled_groups=["payments_write"],
        writes=WritesConfig(enabled=True),
        payments=PaymentsConfig(real_money_allowed=True),
    )
    assert caps.payments.real_money_allowed is True
