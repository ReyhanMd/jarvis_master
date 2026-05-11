"""
MCP provider registry — single source of truth for which providers
are connectable and how chat/active-fetch routes to them.

Each provider exports an object that conforms to MCPProvider in base.py.
"""

from typing import Optional

from apps.shail.mcp.base import MCPProvider
from apps.shail.mcp.drive import drive_provider
from apps.shail.mcp.github import github_provider
from apps.shail.mcp.notion import notion_provider
from apps.shail.mcp.gmail import gmail_provider

PROVIDERS: dict = {
    "drive":  drive_provider,
    "github": github_provider,
    "notion": notion_provider,
    "gmail":  gmail_provider,
}


def get_provider(name: str) -> Optional[MCPProvider]:
    return PROVIDERS.get(name)


__all__ = ["PROVIDERS", "get_provider", "MCPProvider"]
