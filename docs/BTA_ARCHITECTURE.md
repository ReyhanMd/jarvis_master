# SHAIL Basic Tool Adapter (BTA) Architecture

## Universal pattern
- **Registration/Discovery**: Each adapter exposes tools via MCP (`register_tool`, `register_provider`), discovered through `register_all_tools`.
- **Metadata**: `tool_name`, `category`, `description`, `risk` (low/medium/high), `requires_approval`.
- **Safety hooks**: High-risk actions (OS/system, arbitrary command exec) are marked for approval; medium-risk for mutating APIs; low-risk for read-only.
- **Logging**: Tool usage is logged at adapter level; MCP provider tracks registered tools and metadata.

## Risk tiers (guidance)
- **Low**: Read-only info, listing, basic queries.
- **Medium**: Mutating project/API state (e.g., clone repo, POST/PUT requests).
- **High**: OS/system impact (shell exec, input control, app launch/close) — requires approval.

## Adapter specializations (examples)
- **Engineering/CAD/Simulation**: SolidWorks, FreeCAD, PyBullet, MATLAB, Simulink, KiCad, Octave.
- **APIs**: Google Drive, GitHub, REST/GraphQL.
- **Local apps**: VS Code/Cursor, Terminal, File System.
- **OS control**: Window manager, gestures; optionally wrap accessibility/capture services as tools (with approvals).

## Integration points
- **MCP**: All tools registered via `register_all_tools`, metadata available to planners/agents.
- **RAG/Self-mod**: Tool outputs can be ingested to RAG; approval gates apply to high-risk tools.
- **Platform strategy**: Feature flags per platform; local MCP by default; remote MCP only with auth/safety.

## Testing
- **Per adapter**: discovery + one read-only call.
- **Integration**: register_all → list tools → call a safe tool.
- **Safety**: ensure high-risk tools are flagged `requires_approval`.
