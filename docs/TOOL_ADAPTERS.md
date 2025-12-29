# Tool Adapters Documentation

## Overview

Tool adapters allow SHAIL to interact with external tools and services via MCP. Each adapter follows a consistent pattern for registration and discovery.

## Adapter Structure

All adapters follow this structure:

```python
class ToolAdapter:
    def __init__(self):
        self.name = "tool_name"
        self.category = "category"
    
    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "capabilities": [...],
        }
```

## Current Adapters

### Engineering Tools

- **FreeCAD** (`shail/integrations/tools/freecad/`): CAD file reading and geometry querying
- **PyBullet** (`shail/integrations/tools/pybullet/`): Physics simulation

### Utility Tools

- **File Loader** (`shail/integrations/tools/file_loader/`): Universal file loading

### API Integrations (Stubs)

- **Google Drive** (`shail/integrations/apis/google_drive/`): File operations (OAuth required)
- **GitHub** (`shail/integrations/apis/github/`): Repository operations (OAuth required)

### Local App Integrations (Stubs)

- **VS Code** (`shail/integrations/local/vscode/`): Code editing
- **Terminal** (`shail/integrations/local/terminal/`): Command execution
- **File System** (`shail/integrations/local/filesystem/`): File operations

## Registration

Adapters register their tools with MCP:

```python
from shail.integrations.mcp.provider import get_provider
from shail.integrations.tools.freecad import register_freecad_tools

provider = get_provider()
register_freecad_tools(provider)
```

## Demo Scenarios

1. **"Hey SHAIL, discover available tools"**
   - SHAIL uses MCP to list all registered tools
   - Displays tools by category

2. **"Hey SHAIL, load a FreeCAD file"**
   - SHAIL discovers FreeCAD adapter via MCP
   - Uses adapter to read file
   - Stores file state in RAG memory

3. **"Hey SHAIL, improve your FreeCAD adapter"**
   - SHAIL uses self-modification tools
   - Proposes improvement via SelfImproveAgent
   - Creates patch and requests approval
