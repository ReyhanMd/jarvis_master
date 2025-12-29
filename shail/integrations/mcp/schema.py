"""MCP schema discovery and tool introspection.

This module provides mechanisms for discovering and introspecting tools
registered with the MCP provider.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import inspect
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolSchema:
    """Schema for an MCP tool."""
    
    name: str
    description: str
    parameters: Dict[str, Any]
    returns: Optional[Dict[str, Any]] = None
    category: Optional[str] = None
    provider: Optional[str] = None  # Which adapter/provider this tool belongs to
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert schema to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
            "category": self.category,
            "provider": self.provider,
        }


def discover_tool_schemas(provider: Any) -> List[ToolSchema]:
    """
    Discover all tools from an MCP provider and extract their schemas.
    
    Args:
        provider: MCP provider instance (FastMCP server or similar)
        
    Returns:
        List of ToolSchema objects
    """
    schemas = []
    
    try:
        # If it's a FastMCP server, get tools from tool manager
        if hasattr(provider, 'tool_manager'):
            tool_manager = provider.tool_manager
            if hasattr(tool_manager, 'tools'):
                for tool_name, tool in tool_manager.tools.items():
                    schema = _extract_tool_schema(tool, tool_name)
                    if schema:
                        schemas.append(schema)
        
        # Fallback: try to get tools via introspection
        elif hasattr(provider, 'list_tools'):
            tools = provider.list_tools()
            for tool_info in tools:
                schema = ToolSchema(
                    name=tool_info.get("name", ""),
                    description=tool_info.get("description", ""),
                    parameters=tool_info.get("parameters", {}),
                    returns=tool_info.get("returns"),
                    category=tool_info.get("category"),
                    provider=tool_info.get("provider"),
                )
                schemas.append(schema)
    
    except Exception as e:
        logger.error(f"Error discovering tool schemas: {e}")
    
    return schemas


def _extract_tool_schema(tool: Any, tool_name: str) -> Optional[ToolSchema]:
    """Extract schema from a tool object."""
    try:
        # Try to get description from docstring or tool attribute
        description = ""
        if hasattr(tool, "description"):
            description = tool.description
        elif hasattr(tool, "__doc__") and tool.__doc__:
            description = tool.__doc__.strip()
        
        # Extract parameters from function signature
        parameters = {}
        if hasattr(tool, "function"):
            func = tool.function
            sig = inspect.signature(func)
            for param_name, param in sig.parameters.items():
                param_info = {
                    "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any",
                    "required": param.default == inspect.Parameter.empty,
                }
                if param.default != inspect.Parameter.empty:
                    param_info["default"] = param.default
                parameters[param_name] = param_info
        
        # Try to get return type
        returns = None
        if hasattr(tool, "function"):
            func = tool.function
            sig = inspect.signature(func)
            if sig.return_annotation != inspect.Signature.empty:
                returns = {"type": str(sig.return_annotation)}
        
        return ToolSchema(
            name=tool_name,
            description=description,
            parameters=parameters,
            returns=returns,
        )
    
    except Exception as e:
        logger.warning(f"Could not extract schema for tool {tool_name}: {e}")
        return None


def introspect_tool(tool_name: str, provider: Any) -> Optional[ToolSchema]:
    """
    Introspect a specific tool by name.
    
    Args:
        tool_name: Name of the tool to introspect
        provider: MCP provider instance
        
    Returns:
        ToolSchema if found, None otherwise
    """
    schemas = discover_tool_schemas(provider)
    for schema in schemas:
        if schema.name == tool_name:
            return schema
    return None
