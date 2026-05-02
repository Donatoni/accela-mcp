"""Smoke tests against the real Accela sandbox.

They are gated on `ACCELA_INTEGRATION_TEST=1` (see conftest.py); CI does
not run them by default.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_get_agency_metadata(sandbox_client) -> None:
    result = await sandbox_client.get(f"/v4/agencies/{sandbox_client.agency}")
    # Shape varies; we only assert basic plausibility.
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_list_record_types_filtered_by_module(sandbox_client) -> None:
    result = await sandbox_client.get(
        "/v4/settings/records/types",
        params={"module": "Building", "limit": 10},
    )
    types = result.get("result") or []
    assert isinstance(types, list)
    if types:
        assert all(t.get("module") == "Building" for t in types)


@pytest.mark.asyncio
async def test_search_records_paginated(sandbox_client) -> None:
    result = await sandbox_client.get(
        "/v4/records",
        params={"module": "Building", "limit": 5},
    )
    assert "page" in result
    assert isinstance(result.get("result"), list)
