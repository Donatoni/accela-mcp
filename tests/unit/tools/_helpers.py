"""Helpers for testing tools registered via the FastMCP decorator."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.tools._base import ToolContext


def make_mcp() -> FastMCP:
    return FastMCP("accela-mcp-test")


def register_module(mod: Any, ctx: ToolContext) -> FastMCP:
    """Register the module's tools on a fresh FastMCP and return it."""
    mcp = make_mcp()
    mod.register(mcp, ctx)
    return mcp


def call(mcp: FastMCP, name: str) -> Callable[..., Any]:
    """Return the underlying async function for tool `name`."""
    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None, f"tool {name!r} not registered"
    return tool.fn


def tool_names(mcp: FastMCP) -> set[str]:
    return set(mcp._tool_manager._tools.keys())
