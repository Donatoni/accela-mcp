"""Accela MCP — a Model Context Protocol server for the Accela Construct API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("accela-mcp")
except PackageNotFoundError:  # pragma: no cover - editable install before metadata
    __version__ = "0.0.0+local"

__all__ = ["__version__"]
