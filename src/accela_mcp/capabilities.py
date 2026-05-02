"""Capability group catalog and YAML config loader.

The catalog is the source of truth for:
  * which group IDs are valid
  * which groups are on by default
  * which OAuth scopes each group needs
  * which Python module registers the group's tools

The YAML loader produces a `LoadedConfig` that the server consumes at start.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

GroupId = Literal[
    "discovery",
    "records_read",
    "records_write",
    "inspections_read",
    "inspections_write",
    "documents_read",
    "documents_write",
    "property_read",
    "people_read",
    "workflow_read",
    "workflow_write",
    "fees_read",
    "payments_read",
    "payments_write",
    "reference_data",
    "gis",
    "search",
    "reports",
    "admin_escape_hatch",
]

# fmt: off
_GROUP_CATALOG: dict[str, dict[str, Any]] = {
    "discovery": {
        "default_on": True, "always_on": True,
        "scopes": ["agencies", "settings", "records"],
        "module": "accela_mcp.tools.discovery",
        "description": "Capability listing, agency info, record-type metadata.",
    },
    "records_read": {
        "default_on": True,
        "scopes": ["records", "addresses", "parcels"],
        "module": "accela_mcp.tools.records_read",
        "description": "Search records, get record details and custom data.",
    },
    "records_write": {
        "default_on": False,
        "scopes": ["records"],
        "module": "accela_mcp.tools.records_write",
        "description": "Create / update records. Requires writes.enabled.",
    },
    "inspections_read": {
        "default_on": True,
        "scopes": ["inspections", "records"],
        "module": "accela_mcp.tools.inspections_read",
        "description": "Inspections, history, checklists.",
    },
    "inspections_write": {
        "default_on": False,
        "scopes": ["inspections"],
        "module": "accela_mcp.tools.inspections_write",
        "description": (
            "Schedule / reschedule / cancel / result / assign inspections. "
            "Requires writes.enabled."
        ),
    },
    "documents_read": {
        "default_on": True,
        "scopes": ["documents", "records"],
        "module": "accela_mcp.tools.documents_read",
        "description": "List record documents and download content.",
    },
    "documents_write": {
        "default_on": False,
        "scopes": ["documents"],
        "module": "accela_mcp.tools.documents_write",
        "description": "Upload documents to a record. Requires writes.enabled.",
    },
    "property_read": {
        "default_on": True,
        "scopes": ["addresses", "parcels", "owners"],
        "module": "accela_mcp.tools.property_read",
        "description": "Address, parcel, owner lookups.",
    },
    "people_read": {
        "default_on": True,
        "scopes": ["contacts", "professionals"],
        "module": "accela_mcp.tools.people_read",
        "description": "Contacts and licensed professionals.",
    },
    "workflow_read": {
        "default_on": True,
        "scopes": ["records"],
        "module": "accela_mcp.tools.workflow_read",
        "description": "Workflow tasks and history for a record.",
    },
    "workflow_write": {
        "default_on": False,
        "scopes": ["records"],
        "module": "accela_mcp.tools.workflow_write",
        "description": (
            "Advance / update workflow tasks on a record. Requires writes.enabled."
        ),
    },
    "fees_read": {
        "default_on": True,
        "scopes": ["records", "invoices"],
        "module": "accela_mcp.tools.fees_read",
        "description": "Fees, fee estimates, invoices.",
    },
    "payments_read": {
        "default_on": False,
        "scopes": ["payments"],
        "module": "accela_mcp.tools.payments_read",
        "description": "Read payments on a record.",
    },
    "payments_write": {
        "default_on": False,
        "scopes": ["payments"],
        "module": "accela_mcp.tools.payments_write",
        "description": (
            "Initialize and commit citizen payments. Requires writes.enabled "
            "AND payments.real_money_allowed."
        ),
    },
    "reference_data": {
        "default_on": True,
        "scopes": ["settings", "agencies"],
        "module": "accela_mcp.tools.reference_data",
        "description": "Lookup tables: types, statuses, departments, fees.",
    },
    "gis": {
        "default_on": False,
        "scopes": ["gis"],
        "module": "accela_mcp.tools.gis",
        "description": "Geocoding and reverse-geocoding helpers.",
    },
    "search": {
        "default_on": True,
        "scopes": [
            "global_search", "records", "contacts", "addresses", "parcels"
        ],
        "module": "accela_mcp.tools.search",
        "description": "Cross-entity global search.",
    },
    "reports": {
        "default_on": False,
        "scopes": ["reports"],
        "module": "accela_mcp.tools.reports",
        "description": "List and run agency-defined reports.",
    },
    "admin_escape_hatch": {
        "default_on": False,
        "scopes": [],  # operator declares
        "module": "accela_mcp.tools.admin_escape",
        "description": "accela_raw_request — gated by path/method allowlist.",
    },
}
# fmt: on


def all_group_ids() -> list[str]:
    return list(_GROUP_CATALOG.keys())


def default_groups() -> set[str]:
    return {gid for gid, meta in _GROUP_CATALOG.items() if meta.get("default_on")}


def always_on_groups() -> set[str]:
    return {gid for gid, meta in _GROUP_CATALOG.items() if meta.get("always_on")}


def group_meta(group_id: str) -> dict[str, Any]:
    if group_id not in _GROUP_CATALOG:
        raise KeyError(f"unknown capability group: {group_id!r}")
    return _GROUP_CATALOG[group_id]


def scopes_for(groups: set[str]) -> list[str]:
    """Return the union of OAuth scopes needed by the enabled groups."""
    out: set[str] = set()
    for g in groups:
        out.update(group_meta(g)["scopes"])
    # `get_civicid_profile` is auto-included by Accela; don't request it.
    out.discard("get_civicid_profile")
    return sorted(out)


# ---------------------------------------------------------------------- pydantic


class RateLimitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_retries: int = Field(default=3, ge=0, le=10)
    base_backoff_seconds: float = Field(default=1.0, gt=0)
    max_backoff_seconds: float = Field(default=60.0, gt=0)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "console"] = "json"


class CacheConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_data_ttl_seconds: int = Field(default=3600, ge=0)


class AdminConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_request_allowed_paths: list[str] = Field(default_factory=list)
    raw_request_allowed_methods: list[Literal["GET", "POST", "PUT", "DELETE"]] = Field(
        default_factory=lambda: ["GET"]
    )

    @field_validator("raw_request_allowed_paths")
    @classmethod
    def _at_least_one_pattern(cls, v: list[str]) -> list[str]:
        for pattern in v:
            if not pattern:
                raise ValueError("admin.raw_request_allowed_paths must not contain empty strings")
        return v


class WritesConfig(BaseModel):
    """Master kill-switch and audit config for write tools.

    `enabled` defaults to false even when an operator lists a `*_write`
    group in `enabled_groups`. The MCP refuses to start in that mismatched
    state — fail loud rather than fail silent.

    `agency_environment_allowed`, when set, restricts confirmed writes to
    listed environments (e.g., `["TEST"]`). Useful for staging an MCP
    deployment that's ready for sandbox writes but not yet PROD.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    audit_log_path: Path | None = None
    agency_environment_allowed: list[str] = Field(default_factory=list)


class PaymentsConfig(BaseModel):
    """Extra gate on top of the writes kill-switch for the payments group.

    Even with `writes.enabled: true`, `payments_write` will not call
    `/commit` (the irreversible step) unless `real_money_allowed` is true.
    Setting `real_money_allowed: true` for a PROD-like environment
    additionally requires `i_understand_this_spends_real_money: true` —
    intentional friction.
    """

    model_config = ConfigDict(extra="forbid")

    real_money_allowed: bool = False
    i_understand_this_spends_real_money: bool = False


class Capabilities(BaseModel):
    """Validated `capabilities.yaml` document."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    agency: str = Field(..., min_length=1)
    environment: str = Field(..., min_length=1)
    enabled_groups: list[str] | None = None
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)
    writes: WritesConfig = Field(default_factory=WritesConfig)
    payments: PaymentsConfig = Field(default_factory=PaymentsConfig)

    @field_validator("enabled_groups")
    @classmethod
    def _validate_groups(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        catalog = _GROUP_CATALOG
        bad = [g for g in v if g not in catalog]
        if bad:
            raise ValueError(
                f"unknown capability group(s): {bad!r}. Valid groups: {sorted(catalog.keys())}"
            )
        return v

    @model_validator(mode="after")
    def _admin_allowlist_required_when_enabled(self) -> Capabilities:
        groups = self.resolved_groups()
        if "admin_escape_hatch" in groups and not self.admin.raw_request_allowed_paths:
            raise ValueError(
                "admin_escape_hatch is enabled but admin.raw_request_allowed_paths "
                "is empty. Provide an explicit regex allowlist."
            )
        return self

    @model_validator(mode="after")
    def _writes_kill_switch_required(self) -> Capabilities:
        """Refuse to start when a write group is listed but writes are off.

        Fail-loud: an operator who pasted `records_write` into the YAML and
        forgot to flip `writes.enabled` would otherwise see the group
        register but every confirmed call get refused at runtime. Better to
        catch it once at boot.
        """
        groups = self.resolved_groups()
        write_groups = {g for g in groups if g.endswith("_write")}
        if write_groups and not self.writes.enabled:
            raise ValueError(
                f"Capability group(s) {sorted(write_groups)!r} are enabled but "
                "`writes.enabled` is false. Either remove those groups from "
                "`enabled_groups` or set `writes.enabled: true` in capabilities.yaml."
            )
        return self

    @model_validator(mode="after")
    def _payments_real_money_friction(self) -> Capabilities:
        """Require the no-typo flag before letting payments_write hit /commit.

        Setting `payments.real_money_allowed: true` against an environment
        whose name contains `PROD` requires also setting
        `i_understand_this_spends_real_money: true` in the same file. This
        is deliberate friction — the kind of thing that prevents a stray
        edit from authorizing live transactions.
        """
        if (
            self.payments.real_money_allowed
            and "PROD" in self.environment.upper()
            and not self.payments.i_understand_this_spends_real_money
        ):
            raise ValueError(
                "payments.real_money_allowed is true against an environment "
                f"that looks like production ({self.environment!r}). To proceed, "
                "also set payments.i_understand_this_spends_real_money: true. "
                "This is intentional friction."
            )
        return self

    def resolved_groups(self) -> set[str]:
        """Final set of enabled groups after applying always-on rules."""
        base = set(self.enabled_groups) if self.enabled_groups is not None else default_groups()
        base |= always_on_groups()
        return base


@dataclass
class LoadedConfig:
    """The capabilities document plus a few derived conveniences."""

    capabilities: Capabilities
    enabled_groups: set[str] = field(default_factory=set)
    scopes: list[str] = field(default_factory=list)


class CapabilityConfigError(RuntimeError):
    """Raised when capabilities.yaml is missing, malformed, or invalid."""


def load_capabilities(path: Path) -> LoadedConfig:
    """Read and validate `capabilities.yaml`. Raise on any problem."""
    if not path.exists():
        raise CapabilityConfigError(
            f"capabilities config not found at {path}. "
            "Copy `capabilities.yaml.example` and edit, or set ACCELA_MCP_CONFIG_PATH."
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise CapabilityConfigError(f"failed to parse YAML at {path}: {e}") from e

    if not isinstance(raw, dict):
        raise CapabilityConfigError(
            f"capabilities config at {path} must be a mapping at the top level"
        )

    try:
        caps = Capabilities.model_validate(raw)
    except ValidationError as e:
        raise CapabilityConfigError(f"capabilities config invalid:\n{e}") from e

    enabled = caps.resolved_groups()
    return LoadedConfig(
        capabilities=caps,
        enabled_groups=enabled,
        scopes=scopes_for(enabled),
    )


def get_tools_by_group_for(enabled: set[str]) -> dict[str, list[str]]:
    """Static map of group→tool-names — used by `accela_list_capabilities`.

    The list is hand-maintained because importing tool modules to read their
    decorated names would force-instantiate the entire MCP. Cheap and clear.
    """
    catalog: dict[str, list[str]] = {
        "discovery": [
            "accela_list_capabilities",
            "accela_get_agency",
            "accela_describe_record_metadata",
        ],
        "records_read": [
            "accela_search_records",
            "accela_get_record",
            "accela_get_my_records",
            "accela_get_record_custom_data",
        ],
        "inspections_read": [
            "accela_list_inspections_for_record",
            "accela_get_inspection",
            "accela_get_inspection_history",
            "accela_get_inspection_checklists",
        ],
        "documents_read": [
            "accela_list_record_documents",
            "accela_download_document",
        ],
        "property_read": [
            "accela_get_address",
            "accela_search_addresses",
            "accela_get_parcel",
            "accela_get_owners_for_parcel",
        ],
        "people_read": [
            "accela_get_contact",
            "accela_search_contacts",
            "accela_get_professional",
            "accela_search_professionals",
        ],
        "workflow_read": [
            "accela_list_workflow_tasks",
            "accela_get_workflow_task_history",
        ],
        "fees_read": [
            "accela_list_record_fees",
            "accela_estimate_record_fees",
            "accela_list_record_invoices",
        ],
        "reference_data": [
            "accela_list_record_types",
            "accela_list_inspection_types",
            "accela_list_record_statuses",
            "accela_list_departments",
            "accela_list_fee_schedules",
        ],
        "search": ["accela_global_search"],
        "admin_escape_hatch": ["accela_raw_request"],
        # Write groups — every tool defaults to dry-run; pass confirm=true
        # to actually mutate.
        "records_write": [
            "accela_create_record_partial",
            "accela_finalize_record",
            "accela_update_record",
        ],
        "inspections_write": [
            "accela_schedule_inspection",
            "accela_reschedule_inspection",
            "accela_cancel_inspection",
            "accela_result_inspection",
            "accela_assign_inspection",
        ],
        "documents_write": ["accela_upload_document_to_record"],
        "workflow_write": ["accela_update_workflow_task"],
        "payments_read": ["accela_list_record_payments"],
        "payments_write": [
            "accela_initiate_payment",
            "accela_commit_payment",
        ],
        "gis": ["accela_geocode", "accela_reverse_geocode"],
        "reports": ["accela_list_reports", "accela_run_report"],
    }
    return {g: catalog.get(g, []) for g in sorted(enabled) if g in catalog}


__all__ = [
    "AdminConfig",
    "CacheConfig",
    "Capabilities",
    "CapabilityConfigError",
    "LoadedConfig",
    "LoggingConfig",
    "PaymentsConfig",
    "RateLimitConfig",
    "WritesConfig",
    "all_group_ids",
    "default_groups",
    "get_tools_by_group_for",
    "group_meta",
    "load_capabilities",
    "scopes_for",
]
