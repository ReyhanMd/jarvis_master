"""MCP Provider stub for SHAIL.

This module provides the MCP provider that allows tools to register
and be discovered via the Model Context Protocol.
"""

import logging
from typing import Any, Dict, List, Optional

# Risk levels for tool execution
RISK_LOW = "low"           # read-only, informational
RISK_MEDIUM = "medium"     # state changes in app/project, not OS-wide
RISK_HIGH = "high"         # OS/system changes, code execution, privileged actions

try:
    from fastmcp import FastMCP
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False
    FastMCP = None  # type: ignore

logger = logging.getLogger(__name__)


class MCPProvider:
    """
    MCP Provider for SHAIL that manages tool registration and discovery.
    
    This acts as a central registry for all tools, APIs, and integrations
    that SHAIL can use. All tools must register with this provider to be
    discoverable via MCP.
    """
    
    def __init__(self, name: str = "SHAIL"):
        """Initialize the MCP provider.
        
        Args:
            name: Name of the MCP server
        """
        self.name = name
        self._has_fastmcp = bool(HAS_FASTMCP and FastMCP)
        if self._has_fastmcp:
            self.server = FastMCP(name)
        else:
            self.server = None
            logger.warning("FastMCP not available - using stub implementation")
        self._registered_tools: Dict[str, Any] = {}
        self._registered_providers: Dict[str, Any] = {}
        logger.info(f"Initialized MCP Provider: {name}")
    
    def register_tool(
        self,
        tool_func: callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        risk: str = RISK_LOW,
        requires_approval: bool = False,
    ) -> str:
        """
        Register a tool with the MCP provider.
        
        Args:
            tool_func: The function to register as a tool
            name: Optional name for the tool (defaults to function name)
            description: Optional description (defaults to docstring)
            category: Optional category (e.g., "engineering", "api", "local")
            
        Returns:
            The registered tool name
        """
        tool_name = name or tool_func.__name__
        
        # Register with FastMCP server if available
        if self.server:
            self.server.tool(tool_func)
        
        # Store metadata
        self._registered_tools[tool_name] = {
            "func": tool_func,
            "name": tool_name,
            "description": description or (tool_func.__doc__ or ""),
            "category": category,
            "risk": risk,
            "requires_approval": requires_approval,
        }
        
        logger.info(f"Registered tool: {tool_name} (category: {category})")
        return tool_name
    
    def register_provider(
        self,
        provider_name: str,
        provider_instance: Any,
        category: Optional[str] = None,
    ):
        """
        Register an adapter/provider that exposes multiple tools.
        
        Args:
            provider_name: Name of the provider (e.g., "freecad", "github")
            provider_instance: The provider/adapter instance
            category: Category of the provider
        """
        self._registered_providers[provider_name] = {
            "instance": provider_instance,
            "category": category,
        }
        logger.info(f"Registered provider: {provider_name} (category: {category})")
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """
        List all registered tools.
        
        Returns:
            List of tool information dictionaries
        """
        tools = []
        
        # Get tools from FastMCP server if available
        if self.server and hasattr(self.server, 'tool_manager'):
            for tool_name, tool in self.server.tool_manager.tools.items():
                tools.append({
                    "name": tool_name,
                    "description": getattr(tool, "description", ""),
                    "category": self._registered_tools.get(tool_name, {}).get("category"),
                })
        
        # Also include directly registered tools
        for tool_name, tool_info in self._registered_tools.items():
            if not any(t.get("name") == tool_name for t in tools):
                tools.append({
                    "name": tool_name,
                    "description": tool_info.get("description", ""),
                    "category": tool_info.get("category"),
                    "risk": tool_info.get("risk", RISK_LOW),
                    "requires_approval": tool_info.get("requires_approval", False),
                })
        
        return tools
    
    def list_providers(self) -> List[str]:
        """
        List all registered providers.
        
        Returns:
            List of provider names
        """
        return list(self._registered_providers.keys())
    
    def get_tool(self, tool_name: str) -> Optional[callable]:
        """
        Get a registered tool by name.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            The tool function if found, None otherwise
        """
        tool_info = self._registered_tools.get(tool_name)
        if tool_info:
            return tool_info["func"]
        return None
    
    def get_provider(self, provider_name: str) -> Optional[Any]:
        """
        Get a registered provider by name.
        
        Args:
            provider_name: Name of the provider
            
        Returns:
            The provider instance if found, None otherwise
        """
        provider_info = self._registered_providers.get(provider_name)
        if provider_info:
            return provider_info["instance"]
        return None

    def update_tool_metadata(
        self,
        tool_name: str,
        *,
        description: Optional[str] = None,
        category: Optional[str] = None,
        risk: Optional[str] = None,
        requires_approval: Optional[bool] = None,
    ) -> None:
        """
        Update metadata for a registered tool (risk, approvals, description).
        Useful for applying policy after registration.
        """
        info = self._registered_tools.get(tool_name)
        if not info:
            return
        if description is not None:
            info["description"] = description
        if category is not None:
            info["category"] = category
        if risk is not None:
            info["risk"] = risk
        if requires_approval is not None:
            info["requires_approval"] = requires_approval
    
    def discover_tools(self) -> Dict[str, Any]:
        """
        Discover all available tools and their schemas.
        
        Returns:
            Dictionary mapping tool names to their schemas
        """
        from shail.integrations.mcp.schema import discover_tool_schemas
        
        result = {}
        
        # Discover from FastMCP server if available
        if self.server:
            schemas = discover_tool_schemas(self.server)
            for schema in schemas:
                result[schema.name] = schema.to_dict()
        
        # Also include directly registered tools
        for tool_name, tool_info in self._registered_tools.items():
            if tool_name not in result:
                result[tool_name] = {
                    "name": tool_name,
                    "description": tool_info.get("description", ""),
                    "parameters": {},
                    "category": tool_info.get("category"),
                    "risk": tool_info.get("risk", RISK_LOW),
                    "requires_approval": tool_info.get("requires_approval", False),
                }
        
        return result
    
    def run(self, transport: str = "stdio", **kwargs):
        """
        Run the MCP server.
        
        Args:
            transport: Transport type ("stdio", "http", "sse")
            **kwargs: Additional arguments for the server
        """
        if not self.server:
            msg = (
                "Cannot run MCP server - FastMCP not available. "
                "Install fastmcp (pip install fastmcp) to enable transports."
            )
            logger.error(msg)
            raise RuntimeError(msg)
        logger.info(f"Starting MCP server with transport: {transport}")
        self.server.run(transport=transport, **kwargs)

    @property
    def has_fastmcp(self) -> bool:
        """Return True if FastMCP is installed and server is available."""
        return self._has_fastmcp


# Global MCP provider instance
_provider: Optional[MCPProvider] = None


def get_provider() -> MCPProvider:
    """Get or create the global MCP provider instance."""
    global _provider
    if _provider is None:
        _provider = MCPProvider()
    return _provider


def reset_provider():
    """Reset the global provider (useful for testing)."""
    global _provider
    _provider = None
