from __future__ import annotations

from pathlib import Path

import pytest

from accela_mcp.capabilities import (
    CapabilityConfigError,
    all_group_ids,
    always_on_groups,
    default_groups,
    get_tools_by_group_for,
    group_meta,
    load_capabilities,
    scopes_for,
)


class TestCatalog:
    def test_all_groups_have_required_keys(self) -> None:
        for gid in all_group_ids():
            meta = group_meta(gid)
            assert "default_on" in meta
            assert "scopes" in meta
            assert "description" in meta

    def test_discovery_is_always_on(self) -> None:
        assert "discovery" in always_on_groups()

    def test_writes_default_off(self) -> None:
        for gid in [
            "records_write",
            "inspections_write",
            "documents_write",
            "workflow_write",
            "payments_read",
            "payments_write",
            "admin_escape_hatch",
        ]:
            assert gid not in default_groups()

    def test_scopes_for_dedups_and_drops_civicid(self) -> None:
        s = scopes_for({"discovery", "records_read"})
        assert "records" in s
        assert "agencies" in s
        assert "get_civicid_profile" not in s


class TestLoadCapabilities:
    def test_minimal_valid(self, tmp_path: Path) -> None:
        cfg = tmp_path / "capabilities.yaml"
        cfg.write_text("version: 1\nagency: NULLISLAND\nenvironment: TEST\n")
        loaded = load_capabilities(cfg)
        assert loaded.capabilities.agency == "NULLISLAND"
        # Defaults applied + always-on rules.
        assert "discovery" in loaded.enabled_groups
        assert "records_read" in loaded.enabled_groups

    def test_explicit_groups_replace_defaults(self, tmp_path: Path) -> None:
        cfg = tmp_path / "capabilities.yaml"
        cfg.write_text(
            "version: 1\nagency: NULLISLAND\nenvironment: TEST\nenabled_groups:\n  - records_read\n"
        )
        loaded = load_capabilities(cfg)
        # discovery and auth still added because always-on
        assert loaded.enabled_groups == {"auth", "discovery", "records_read"}

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(CapabilityConfigError):
            load_capabilities(tmp_path / "nope.yaml")

    def test_unknown_group_rejected(self, tmp_path: Path) -> None:
        cfg = tmp_path / "capabilities.yaml"
        cfg.write_text("version: 1\nagency: X\nenvironment: TEST\nenabled_groups:\n  - made_up\n")
        with pytest.raises(CapabilityConfigError):
            load_capabilities(cfg)

    def test_admin_escape_requires_allowlist(self, tmp_path: Path) -> None:
        cfg = tmp_path / "capabilities.yaml"
        cfg.write_text(
            "version: 1\nagency: X\nenvironment: TEST\nenabled_groups:\n  - admin_escape_hatch\n"
        )
        with pytest.raises(CapabilityConfigError):
            load_capabilities(cfg)

    def test_admin_escape_with_allowlist_ok(self, tmp_path: Path) -> None:
        cfg = tmp_path / "capabilities.yaml"
        cfg.write_text(
            "version: 1\nagency: X\nenvironment: TEST\n"
            "enabled_groups:\n  - admin_escape_hatch\n"
            "admin:\n"
            "  raw_request_allowed_paths:\n"
            "    - '^/v4/records.*$'\n"
        )
        loaded = load_capabilities(cfg)
        assert "admin_escape_hatch" in loaded.enabled_groups

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "capabilities.yaml"
        cfg.write_text(":\nthis: [is broken")
        with pytest.raises(CapabilityConfigError):
            load_capabilities(cfg)

    def test_top_level_must_be_mapping(self, tmp_path: Path) -> None:
        cfg = tmp_path / "capabilities.yaml"
        cfg.write_text("- one\n- two\n")
        with pytest.raises(CapabilityConfigError):
            load_capabilities(cfg)


class TestGetToolsByGroupFor:
    def test_returns_tool_lists(self) -> None:
        out = get_tools_by_group_for({"discovery", "records_read"})
        assert "discovery" in out
        assert "accela_get_agency" in out["discovery"]
        assert "accela_search_records" in out["records_read"]

    def test_unknown_groups_filtered_out(self) -> None:
        out = get_tools_by_group_for({"discovery", "made_up"})
        assert "made_up" not in out
