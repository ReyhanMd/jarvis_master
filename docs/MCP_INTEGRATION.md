# MCP Integration Documentation

## Overview

SHAIL uses the Model Context Protocol (MCP) as the universal foundation for tool integration. All tools, APIs, and integrations register with MCP for discovery and execution.

## Architecture

### MCP Provider

The `MCPProvider` (`shail/integrations/mcp/provider.py`) acts as the central registry for all tools. It uses FastMCP under the hood to provide MCP-compliant tool discovery.

### Tool Registration

All tools must register with the MCP provider:

```python
from shail.integrations.mcp.provider import get_provider

provider = get_provider()

@provider.register_tool
def my_tool(param: str) -> str:
    """Tool description."""
    return f"Result: {param}"
```

### Tool Discovery

SHAIL can discover all available tools:

```python
from shail.integrations.mcp import get_provider

provider = get_provider()
tools = provider.discover_tools()
```

## Current Integrations

- **FreeCAD**: CAD file reading and geometry querying
- **PyBullet**: Physics simulation setup and querying
- **File Loader**: Universal file loading (CAD, images, documents, code)
- **Google Drive**: File listing/download/upload (stub)
- **GitHub**: Repo cloning, file reading, commits (stub)
- **VS Code**: File opening and editing (stub)
- **Terminal**: Command execution
- **File System**: Directory operations and file watching

## Usage Example

```python
from shail.integrations.mcp import get_provider
from shail.integrations.tools.freecad import register_freecad_tools

provider = get_provider()
register_freecad_tools(provider)

# Discover tools
tools = provider.discover_tools()
print(f"Available tools: {list(tools.keys())}")
```

## Running the MCP server locally

1) Install FastMCP (if not already):
```
pip install fastmcp
```

2) Start the MCP server (stdio by default):
```
python -m shail.integrations.mcp.server --transport stdio
```
For HTTP/SSE:
```
python -m shail.integrations.mcp.server --transport http --host 127.0.0.1 --port 8005
```

The server automatically registers all SHAIL tool adapters before starting.

## Remote client usage (HTTP/stdio)

```python
import asyncio
from shail.integrations.mcp.client import MCPClient

async def main():
    client = MCPClient(server_url="http://127.0.0.1:8005")
    # list remotely available tools
    tools = await asyncio.to_thread(client.list_tools)
    print(tools)

asyncio.run(main())
```

If no `server_url` is provided, the client uses the in-process provider.

## Smoke test

Run a quick local smoke test (no server needed):
```
python -m shail.integrations.mcp.smoke_test
```

This registers all tools locally, adds a `mcp_ping` tool, and verifies discovery.
