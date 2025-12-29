"""MCP (Model Context Protocol) integration for SHAIL.

This module provides the foundation for universal tool integration via MCP.
All tools, APIs, and integrations register with MCP for discovery and execution.
"""

from shail.integrations.mcp.client import MCPClient
from shail.integrations.mcp.provider import MCPProvider
from shail.integrations.mcp.schema import ToolSchema, discover_tool_schemas

__all__ = [
    "MCPClient",
    "MCPProvider",
    "ToolSchema",
    "discover_tool_schemas",
]
