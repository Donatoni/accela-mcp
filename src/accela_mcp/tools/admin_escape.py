"""The `accela_raw_request` escape hatch.

Off by default. When enabled, the operator MUST provide a regex allowlist
(`admin.raw_request_allowed_paths`). We additionally enforce an HTTP-method
allowlist (default GET only) so a misconfigured path allowlist can't enable
destructive verbs.

Every call is logged at INFO with full method, path, and status (params and
body are PII-scrubbed by the structlog redaction processor).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from accela_mcp.observability.logging_config import get_logger
from accela_mcp.tools._base import ToolContext, destructive_annotations, tool_call
from accela_mcp.utils.ids import is_safe_api_path

log = get_logger(__name__)

HttpMethod = Literal["GET", "POST", "PUT", "DELETE"]


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    admin_cfg = ctx.config.capabilities.admin
    compiled_patterns = [re.compile(p) for p in admin_cfg.raw_request_allowed_paths]
    allowed_methods = set(admin_cfg.raw_request_allowed_methods)

    @mcp.tool(annotations=destructive_annotations("Raw API Request"))
    @tool_call("accela_raw_request")
    async def accela_raw_request(
        method: HttpMethod,
        path: str,
        query_params: dict[str, Any] | None = None,
        body: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        """Sends an arbitrary request to the Accela API. Use ONLY for
        endpoints not covered by other tools. The MCP attaches auth headers
        and the configured agency/environment automatically. Path must start
        with `/v4/` and match the operator-configured regex allowlist; method
        must be in the configured allowlist (default `GET` only). Every call
        is audit-logged."""
        method_upper = (method or "").upper()
        if method_upper not in {"GET", "POST", "PUT", "DELETE"}:
            raise ValueError(f"method must be one of GET/POST/PUT/DELETE, got {method!r}")
        if method_upper not in allowed_methods:
            raise ValueError(
                f"HTTP method {method_upper!r} is not in the operator's allowlist "
                f"({sorted(allowed_methods)}). Update capabilities.yaml to permit it."
            )
        if not is_safe_api_path(path):
            raise ValueError(
                f"path {path!r} is not a valid /v4/... API path "
                "(traversal sequences and non-/v4 paths are refused)"
            )
        if not any(p.search(path) for p in compiled_patterns):
            raise ValueError(
                f"path {path!r} does not match the operator's configured allowlist "
                f"(admin.raw_request_allowed_paths)"
            )

        log.info(
            "raw_request_audit",
            method=method_upper,
            path=path,
            agency=ctx.client.agency,
            environment=ctx.client.environment,
            has_body=body is not None,
            param_keys=sorted((query_params or {}).keys()),
        )

        return await ctx.client.request(
            method_upper,
            path,
            params=query_params,
            json=body,
        )
