from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
import respx
from httpx import Response

from accela_mcp.capabilities import (
    Capabilities,
    LoadedConfig,
    PaymentsConfig,
    WritesConfig,
    scopes_for,
)
from accela_mcp.safety import AuditLog
from accela_mcp.tools import payments_write
from accela_mcp.tools._base import ToolContext
from accela_mcp.utils.cache import TTLCache

from ._helpers import call, register_module, tool_names


@pytest.fixture
def payments_disabled_config() -> LoadedConfig:
    """writes.enabled=true but payments.real_money_allowed=false."""
    enabled = {"discovery", "payments_write"}
    caps = Capabilities(
        version=1,
        agency="NULLISLAND",
        environment="TEST",
        enabled_groups=sorted(enabled),
        writes=WritesConfig(enabled=True),
        payments=PaymentsConfig(real_money_allowed=False),
    )
    return LoadedConfig(
        capabilities=caps,
        enabled_groups=enabled,
        scopes=scopes_for(enabled),
    )


@pytest_asyncio.fixture
async def payments_disabled_ctx(settings, payments_disabled_config, client, tmp_path):
    cache: TTLCache[dict[str, Any]] = TTLCache(ttl_seconds=60)
    audit = AuditLog(tmp_path / "audit.log")
    return ToolContext(
        settings=settings,
        config=payments_disabled_config,
        client=client,
        reference_cache=cache,
        audit_log=audit,
    )


@pytest.mark.asyncio
async def test_register(write_tool_context) -> None:
    mcp = register_module(payments_write, write_tool_context)
    assert tool_names(mcp) == {
        "accela_initiate_payment",
        "accela_commit_payment",
    }


# ---------------------------------------------------------------- initiate


@pytest.mark.asyncio
async def test_initiate_dry_run_marks_money(write_tool_context) -> None:
    mcp = register_module(payments_write, write_tool_context)
    out = await call(mcp, "accela_initiate_payment")(
        record_id="ISLANDTON-1-2-3",
        amount=50.0,
        payment_method="creditCard",
    )
    assert out["preview"] is True
    assert out["affects_money"] is True
    assert out["body"]["amount"] == 50.0
    assert out["body"]["currency"] == "USD"


@pytest.mark.asyncio
async def test_initiate_validates(write_tool_context) -> None:
    mcp = register_module(payments_write, write_tool_context)
    out = await call(mcp, "accela_initiate_payment")(
        record_id="X",
        amount=0,
        payment_method="creditCard",
    )
    assert out["error"] == "invalid_input"


@pytest.mark.asyncio
@respx.mock
async def test_initiate_confirmed(write_tool_context) -> None:
    respx.post("https://apis.test.example/v4/payments").mock(
        return_value=Response(200, json={"status": 200, "result": [{"id": "PAY1"}]})
    )
    mcp = register_module(payments_write, write_tool_context)
    out = await call(mcp, "accela_initiate_payment")(
        record_id="ISLANDTON-1-2-3",
        amount=50.0,
        payment_method="creditCard",
        confirm=True,
    )
    assert out["result_status"] == 200
    assert out["result_id"] == "PAY1"


# ----------------------------------------------------------------- commit


@pytest.mark.asyncio
async def test_commit_dry_run_warns_when_disabled(payments_disabled_ctx) -> None:
    mcp = register_module(payments_write, payments_disabled_ctx)
    out = await call(mcp, "accela_commit_payment")(payment_id="PAY1")
    assert out["preview"] is True
    assert out["irreversible"] is True
    assert any("real_money_allowed" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_commit_confirmed_refused_without_real_money(payments_disabled_ctx) -> None:
    mcp = register_module(payments_write, payments_disabled_ctx)
    out = await call(mcp, "accela_commit_payment")(
        payment_id="PAY1",
        confirm=True,
    )
    assert out["error"] == "payments_disabled"
    assert out["payment_id"] == "PAY1"


@pytest.mark.asyncio
@respx.mock
async def test_commit_confirmed_with_real_money(write_tool_context) -> None:
    """write_tool_context's PaymentsConfig has real_money_allowed=True."""
    respx.post("https://apis.test.example/v4/payments/PAY1/commit").mock(
        return_value=Response(200, json={"status": 200})
    )
    mcp = register_module(payments_write, write_tool_context)
    out = await call(mcp, "accela_commit_payment")(
        payment_id="PAY1",
        confirm=True,
    )
    assert out["result_status"] == 200
    assert out["result_id"] == "PAY1"


@pytest.mark.asyncio
async def test_kill_switch_off_refuses_commit(tool_context) -> None:
    mcp = register_module(payments_write, tool_context)
    out = await call(mcp, "accela_commit_payment")(
        payment_id="PAY1",
        confirm=True,
    )
    assert out["error"] == "writes_disabled"
