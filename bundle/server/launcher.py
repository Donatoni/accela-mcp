"""MCPB entry point — runs the Accela MCP server over stdio.

This wraps `accela_mcp.server.serve_async` so the bundle benefits from
auto-key bootstrapping (`ensure_mcp_key`) and the bootstrap-mode tools
(`accela_auth_status`, `accela_login`) when the user hasn't logged in yet.

Kept deliberately small. The host runs this as `uv run server/launcher.py`,
which resolves the project's dependencies from the bundled pyproject.toml
on first start (cached thereafter).
"""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    try:
        from accela_mcp.server import serve_async
    except ImportError as e:  # pragma: no cover — defensive
        print(f"Failed to import accela_mcp: {e}", file=sys.stderr)
        sys.exit(1)
    asyncio.run(serve_async())


if __name__ == "__main__":
    main()
