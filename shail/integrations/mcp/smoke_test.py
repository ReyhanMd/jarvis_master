"""Simple smoke tests for MCP provider/client."""

from typing import Any, Dict

from shail.integrations.mcp.provider import get_provider
from shail.integrations.mcp.client import MCPClient
from shail.integrations.register_all import register_all_tools

try:
    from fastmcp import Client as FastMCPClient
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False
    FastMCPClient = None  # type: ignore


def run_local_smoke() -> Dict[str, Any]:
    """Register tools locally and ensure discovery works."""
    provider = get_provider()
    register_all_tools(provider)

    @provider.register_tool
    def mcp_ping(value: str = "pong") -> Dict[str, str]:
        """Simple ping tool for MCP smoke tests."""
        return {"echo": value}

    client = MCPClient(provider=provider)
    tools = client.list_tools()
    schemas = client.discover_available_tools()
    return {
        "tool_names": [t.get("name") for t in tools],
        "schema_names": list(schemas.keys()),
    }


async def run_remote_smoke(server_url: str):
    """Connect to a running MCP server and list tools."""
    if not HAS_FASTMCP or not FastMCPClient:
        raise RuntimeError("fastmcp is required for remote smoke test")
    client = FastMCPClient(server_url)
    async with client:
        tools = await client.list_tools()
        return [t.name for t in tools]


if __name__ == "__main__":
    result = run_local_smoke()
    print("Local MCP smoke:", result)
