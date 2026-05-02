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
        "module": None,  # not implemented in v1
        "description": "Create / update records (v2).",
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
        "module": None,
        "description": "Schedule / reschedule / cancel / result inspections (v2).",
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
        "module": None,
        "description": "Upload documents to a record (v2).",
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
        "module": None,
        "description": "Advance / update workflow tasks (v2).",
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
        "module": None,
        "description": "Read payments on a record (v2).",
    },
    "payments_write": {
        "default_on": False,
        "scopes": ["payments"],
        "module": None,
        "description": "Initialize and commit citizen payments (v2).",
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
        "module": None,
        "description": "Geocoding / reverse geocoding (v2).",
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
        "module": None,
        "description": "Run agency-defined reports (v2).",
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
    }
    return {g: catalog.get(g, []) for g in sorted(enabled) if g in catalog}


__all__ = [
    "AdminConfig",
    "CacheConfig",
    "Capabilities",
    "CapabilityConfigError",
    "LoadedConfig",
    "LoggingConfig",
    "RateLimitConfig",
    "all_group_ids",
    "default_groups",
    "get_tools_by_group_for",
    "group_meta",
    "load_capabilities",
    "scopes_for",
]
