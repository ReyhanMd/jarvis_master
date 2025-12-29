"""
Bulk Permission System - One-time approval for common operations.

Users can approve a set of common permissions at startup,
then only new/dangerous operations require individual approval.
"""

from typing import Set, Dict
from shail.safety.permission_manager import PermissionManager

# Pre-defined permission categories
PERMISSION_CATEGORIES = {
    "desktop_control": {
        "tools": ["move_mouse", "click_mouse", "type_text", "press_key", "scroll_mouse"],
        "description": "Mouse and keyboard control"
    },
    "window_management": {
        "tools": ["focus_window", "open_app", "close_app"],
        "description": "Opening/closing apps and focusing windows"
    },
    "file_operations": {
        "tools": ["read_file", "write_file", "list_dir"],
        "description": "Reading and writing files"
    },
    "system_info": {
        "tools": ["get_active_window", "get_running_apps", "get_screen_info"],
        "description": "Viewing system state (read-only)"
    }
}

# Set of tools that are always approved (no permission needed)
_approved_tools: Set[str] = set()

# Set of tools that require individual approval even if category is approved
_always_require_approval: Set[str] = {
    "run_command",  # Shell commands are always dangerous
    "delete_file",  # Deletions are always dangerous
}


def approve_category(category: str) -> bool:
    """
    Approve all tools in a category.
    
    Args:
        category: One of the keys from PERMISSION_CATEGORIES
        
    Returns:
        True if category exists and was approved
    """
    if category not in PERMISSION_CATEGORIES:
        return False
    
    for tool in PERMISSION_CATEGORIES[category]["tools"]:
        _approved_tools.add(tool)
    
    return True


def approve_tool(tool_name: str) -> None:
    """Approve a specific tool."""
    _approved_tools.add(tool_name)


def is_approved(tool_name: str) -> bool:
    """
    Check if a tool is pre-approved.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        True if tool is in approved list and not in always-require list
    """
    if tool_name in _always_require_approval:
        return False
    return tool_name in _approved_tools


def get_permission_summary() -> Dict[str, str]:
    """Get a summary of all permission categories for UI display."""
    return {
        cat: info["description"] 
        for cat, info in PERMISSION_CATEGORIES.items()
    }


def get_approved_tools() -> Set[str]:
    """Get the set of currently approved tools."""
    return _approved_tools.copy()

