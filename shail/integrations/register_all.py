"""Utility to register all SHAIL tools with the MCP provider."""

import importlib
import logging
from typing import List, Tuple

from shail.integrations.mcp.provider import (
    MCPProvider,
    get_provider,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
)

logger = logging.getLogger(__name__)


def _registrars() -> List[Tuple[str, str, str]]:
    """Return (name, module, function) tuples for tool registration."""
    return [
        ("freecad", "shail.integrations.tools.freecad.adapter", "register_freecad_tools"),
        ("pybullet", "shail.integrations.tools.pybullet.adapter", "register_pybullet_tools"),
        ("file_loader", "shail.integrations.tools.file_loader.adapter", "register_file_loader_tools"),
        ("solidworks", "shail.integrations.tools.solidworks.adapter", "register_solidworks_tools"),
        ("matlab", "shail.integrations.tools.matlab.adapter", "register_matlab_tools"),
        ("simulink", "shail.integrations.tools.simulink.adapter", "register_simulink_tools"),
        ("kicad", "shail.integrations.tools.kicad.adapter", "register_kicad_tools"),
        ("octave", "shail.integrations.tools.octave.adapter", "register_octave_tools"),
        ("google_drive", "shail.integrations.apis.google_drive.adapter", "register_google_drive_tools"),
        ("github", "shail.integrations.apis.github.adapter", "register_github_tools"),
        ("vscode", "shail.integrations.local.vscode.adapter", "register_vscode_tools"),
        ("terminal", "shail.integrations.local.terminal.adapter", "register_terminal_tools"),
        ("filesystem", "shail.integrations.local.filesystem.adapter", "register_filesystem_tools"),
    ]


def register_all_tools(provider: MCPProvider = None) -> None:
    """Register all available tools with the given provider."""
    provider = provider or get_provider()
    for name, module_path, func_name in _registrars():
        try:
            module = importlib.import_module(module_path)
            registrar = getattr(module, func_name, None)
            if registrar:
                registrar(provider)
                logger.info("Registered %s tools via MCP", name)
                _apply_policy(provider)
            else:
                logger.warning("Registrar %s not found in %s", func_name, module_path)
        except ImportError as exc:
            logger.warning("Skipping %s registration (import error): %s", name, exc)
        except Exception as exc:
            logger.warning("Failed to register %s tools: %s", name, exc)


def _apply_policy(provider: MCPProvider) -> None:
    """
    Apply safety/risk policy to known tool names.
    
    This is intentionally coarse: it can be refined per adapter as they mature.
    """
    # High-risk: system command execution
    provider.update_tool_metadata(
        "execute_terminal_command",
        risk=RISK_HIGH,
        requires_approval=True,
        category="local",
    )

    # Medium-risk: mutating API calls (if/when implemented)
    provider.update_tool_metadata(
        "rest_post",
        risk=RISK_MEDIUM,
        requires_approval=False,
        category="api",
    )
    provider.update_tool_metadata(
        "rest_put" if provider.get_tool("rest_put") else "rest_post",
        risk=RISK_MEDIUM,
        requires_approval=False,
        category="api",
    )
    provider.update_tool_metadata(
        "clone_github_repo",
        risk=RISK_MEDIUM,
        requires_approval=True,
        category="api",
    )

    # Default low-risk tags where not set
    for tool in provider.list_tools():
        name = tool["name"]
        meta = provider._registered_tools.get(name, {})  # type: ignore[attr-defined]
        if "risk" not in meta:
            provider.update_tool_metadata(name, risk=RISK_LOW)
