from __future__ import annotations

from pathlib import Path

import pytest

from accela_mcp.capabilities import (
    CapabilityConfigError,
    all_group_ids,
    always_on_groups,
    apply_env_overrides,
    default_groups,
    env_group_var,
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


class TestApplyEnvOverrides:
    """Covers the v0.5.0 simplification: ACCELA_GROUP_* per-group toggles
    are gone; ACCELA_WRITES_ENABLED is the single switch that registers /
    unregisters every write group."""

    def _baseline(self, tmp_path: Path):
        cfg = tmp_path / "capabilities.yaml"
        cfg.write_text("version: 1\nagency: NULLISLAND\nenvironment: TEST\n")
        return load_capabilities(cfg)

    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in [
            "ACCELA_AGENCY",
            "ACCELA_ENVIRONMENT",
            "ACCELA_WRITES_ENABLED",
            "ACCELA_PAYMENTS_REAL_MONEY_ALLOWED",
        ]:
            monkeypatch.delenv(var, raising=False)
        # Also clear any legacy per-group env vars so a stray host doesn't
        # leak in (these are no-ops in 0.5.0+).
        for gid in all_group_ids():
            monkeypatch.delenv(env_group_var(gid), raising=False)

    def test_no_env_returns_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_env(monkeypatch)
        baseline = self._baseline(tmp_path)
        out = apply_env_overrides(baseline)
        assert out.capabilities.agency == "NULLISLAND"
        assert out.enabled_groups == baseline.enabled_groups
        assert out.capabilities.writes.enabled is False

    def test_agency_and_environment_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_env(monkeypatch)
        monkeypatch.setenv("ACCELA_AGENCY", "DELAND")
        monkeypatch.setenv("ACCELA_ENVIRONMENT", "PROD")

        out = apply_env_overrides(self._baseline(tmp_path))
        assert out.capabilities.agency == "DELAND"
        assert out.capabilities.environment == "PROD"

    def test_blank_env_does_not_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # MCPB hosts often pass empty strings for fields the user left blank.
        self._clear_env(monkeypatch)
        monkeypatch.setenv("ACCELA_AGENCY", "")
        monkeypatch.setenv("ACCELA_ENVIRONMENT", "  ")

        out = apply_env_overrides(self._baseline(tmp_path))
        assert out.capabilities.agency == "NULLISLAND"
        assert out.capabilities.writes.enabled is False

    def test_writes_master_on_registers_every_write_group(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The single Allow Write Tools switch must add every *_write
        group AND set writes.enabled — both halves move together so the
        kill-switch validator passes."""
        self._clear_env(monkeypatch)
        monkeypatch.setenv("ACCELA_WRITES_ENABLED", "true")

        out = apply_env_overrides(self._baseline(tmp_path))
        write_groups = {g for g in out.enabled_groups if g.endswith("_write")}
        assert write_groups == {
            "records_write",
            "inspections_write",
            "documents_write",
            "workflow_write",
            "payments_write",
        }
        assert out.capabilities.writes.enabled is True

    def test_writes_master_off_strips_write_groups(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If a YAML lists write groups but the host master is off, the
        override layer should drop them (so the kill-switch validator
        doesn't reject the merged config)."""
        self._clear_env(monkeypatch)
        cfg = tmp_path / "capabilities.yaml"
        # Pre-populate YAML with both write groups + writes.enabled (so
        # load_capabilities accepts it), then turn the master off via env.
        cfg.write_text(
            "version: 1\n"
            "agency: NULLISLAND\n"
            "environment: TEST\n"
            "enabled_groups:\n"
            "  - records_read\n"
            "  - records_write\n"
            "writes:\n"
            "  enabled: true\n"
        )
        loaded = load_capabilities(cfg)
        monkeypatch.setenv("ACCELA_WRITES_ENABLED", "false")

        out = apply_env_overrides(loaded)
        assert "records_write" not in out.enabled_groups
        assert out.capabilities.writes.enabled is False

    def test_payments_real_money_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_env(monkeypatch)
        monkeypatch.setenv("ACCELA_PAYMENTS_REAL_MONEY_ALLOWED", "true")

        out = apply_env_overrides(self._baseline(tmp_path))
        assert out.capabilities.payments.real_money_allowed is True

    def test_legacy_group_env_vars_are_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pre-0.5.0 bundles set ACCELA_GROUP_* env vars; 0.5.0+ ignores
        them so users who upgrade with a stale config don't see surprise
        registrations."""
        self._clear_env(monkeypatch)
        monkeypatch.setenv("ACCELA_GROUP_REPORTS", "true")
        monkeypatch.setenv("ACCELA_GROUP_RECORDS_WRITE", "true")

        out = apply_env_overrides(self._baseline(tmp_path))
        assert "reports" not in out.enabled_groups
        assert "records_write" not in out.enabled_groups
        assert out.capabilities.writes.enabled is False


class TestEnvGroupVarHelper:
    def test_format(self) -> None:
        # Helper retained for migration tooling even though apply_env_overrides
        # no longer reads these env vars.
        assert env_group_var("records_read") == "ACCELA_GROUP_RECORDS_READ"
        assert env_group_var("admin_escape_hatch") == "ACCELA_GROUP_ADMIN_ESCAPE_HATCH"
