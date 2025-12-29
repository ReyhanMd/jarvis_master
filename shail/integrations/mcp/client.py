"""MCP Client for SHAIL.

This module provides a client interface for SHAIL to discover and interact
with tools via the Model Context Protocol.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from fastmcp import Client as FastMCPClient
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False
    FastMCPClient = None  # type: ignore


def _run_coro(coro):
    """Run an async coroutine from sync code."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.ensure_future(coro, loop=loop)
        return loop.run_until_complete(coro)


class MCPClient:
    """
    MCP Client for SHAIL to discover and use tools.
    
    This client allows SHAIL to:
    - Discover available tools from MCP servers
    - Call tools via MCP
    - Introspect tool capabilities
    
    Local mode works with a provided MCPProvider instance.
    Remote mode uses FastMCP client transports when available.
    """
    
    def __init__(
        self,
        server_url: Optional[str] = None,
        provider: Optional[Any] = None,
    ):
        """
        Initialize the MCP client.
        
        Args:
            server_url: Optional URL/path for remote MCP server (None for local)
            provider: Optional local MCPProvider instance for direct access
        """
        self.server_url = server_url
        self.provider = provider
        logger.info(f"Initialized MCP Client (server: {server_url or 'local'})")
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """
        List all available tools.
        
        Returns:
            List of tool information dictionaries
        """
        if self.provider:
            return self.provider.list_tools()
        
        if self.server_url and HAS_FASTMCP:
            tools = _run_coro(self._list_tools_remote())
            # If running inside an event loop, _run_coro returns a Task; handle that.
            if asyncio.isfuture(tools):
                tools = _run_coro(tools)
            return tools or []
        
        if self.server_url and not HAS_FASTMCP:
            logger.warning("FastMCP not installed; cannot reach remote MCP server.")
        
        logger.warning("No provider or server_url configured for MCPClient.")
        return []
    
    def discover_available_tools(self) -> Dict[str, Any]:
        """
        Discover all available tools and their capabilities.
        
        Returns:
            Dictionary mapping tool names to their schemas
        """
        if self.provider:
            return self.provider.discover_tools()
        
        if self.server_url and HAS_FASTMCP:
            schemas = _run_coro(self._discover_remote_tools())
            if asyncio.isfuture(schemas):
                schemas = _run_coro(schemas)
            return schemas or {}
        
        if self.server_url and not HAS_FASTMCP:
            logger.warning("FastMCP not installed; cannot reach remote MCP server.")
        
        return {}
    
    async def _list_tools_remote(self) -> List[Dict[str, Any]]:
        """Async helper to list tools from a remote MCP server."""
        if not HAS_FASTMCP or not self.server_url:
            return []
        client = FastMCPClient(self.server_url)
        async with client:
            tools = await client.list_tools()
            return [
                {
                    "name": t.name,
                    "description": getattr(t, "description", "") or "",
                    "category": getattr(t, "tags", None),
                }
                for t in tools
            ]
    
    async def _discover_remote_tools(self) -> Dict[str, Any]:
        """Async helper to discover tool schemas from a remote MCP server."""
        if not HAS_FASTMCP or not self.server_url:
            return {}
        client = FastMCPClient(self.server_url)
        async with client:
            tools = await client.list_tools()
            result: Dict[str, Any] = {}
            for t in tools:
                result[t.name] = {
                    "name": t.name,
                    "description": getattr(t, "description", "") or "",
                    "parameters": getattr(t, "input_schema", {}) or {},
                    "category": getattr(t, "tags", None),
                }
            return result


# Helper function for local tool discovery (without remote connection)
def discover_local_tools(provider: Any) -> Dict[str, Any]:
    """
    Discover tools from a local MCP provider without establishing a connection.
    
    Args:
        provider: MCPProvider instance
        
    Returns:
        Dictionary mapping tool names to their schemas
    """
    if hasattr(provider, "discover_tools"):
        return provider.discover_tools()
    
    # Fallback: use schema discovery
    from shail.integrations.mcp.schema import discover_tool_schemas
    
    schemas = discover_tool_schemas(provider)
    result = {}
    
    for schema in schemas:
        result[schema.name] = schema.to_dict()
    
    return result
