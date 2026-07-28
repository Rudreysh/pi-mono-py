"""MCP (Model Context Protocol) integration -- placeholder.

The TypeScript codebase hosts a full in-process MCP runtime that discovers,
connects to, and orchestrates MCP servers as tool providers. The Python port
does **not** include an in-process MCP host.

What is missing vs. TS:

* ``McpClient`` / ``McpManager`` -- lifecycle management for child MCP server
  processes, stdio/SSE transports, capability negotiation, and tool/resource
  dispatch.
* ``McpToolWrapper`` -- adapters that expose MCP tools as standard agent tools
  (parameter schema normalization, result formatting, timeout/abort handling).
* ``mcp-config.json`` discovery and validation.

If you need MCP tools today, either:

1. Use the TypeScript pi binary (``npx @anthropic-ai/pi``) which ships the full
   MCP runtime, or
2. Run an external MCP client and connect via the extension ``api.exec()``
   bridge.

This package exists so other Python modules can import a stable interface
without conditional imports scattered across the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class McpToolDefinition:
    """Placeholder for an MCP-discovered tool definition."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


class McpClient:
    """Placeholder MCP client interface.

    All methods raise NotImplementedError; see module docstring.
    """

    async def connect(self, config: dict[str, Any]) -> None:
        raise NotImplementedError("In-process MCP runtime is not available in the Python port")

    async def disconnect(self) -> None:
        raise NotImplementedError("In-process MCP runtime is not available in the Python port")

    async def list_tools(self) -> list[McpToolDefinition]:
        raise NotImplementedError("In-process MCP runtime is not available in the Python port")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        raise NotImplementedError("In-process MCP runtime is not available in the Python port")

    @property
    def is_connected(self) -> bool:
        return False
