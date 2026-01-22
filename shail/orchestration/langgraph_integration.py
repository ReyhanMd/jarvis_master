"""
LangGraph integration helpers.

This module centralizes how we import LangGraph so we can:
1) Prefer the locally cloned source at `/Users/reyhan/shail_master/langgraph`.
2) Fall back to the pip-installed LangGraph package.
3) Expose typed aliases for common LangGraph classes used across Shail.
"""

import importlib
import os
import sys
from types import ModuleType
from typing import Any, Optional, Type

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# LangGraph source is in langgraph/libs/langgraph/
_LOCAL_LANGGRAPH = os.path.join(_PROJECT_ROOT, "langgraph", "libs", "langgraph")
# Also try the root langgraph directory
_LOCAL_LANGGRAPH_ROOT = os.path.join(_PROJECT_ROOT, "langgraph")


def _ensure_local_langgraph_on_path() -> None:
    """Prepend local LangGraph source to sys.path if present.
    
    Only adds local source if pip-installed version is not available.
    This prevents conflicts between local source and pip installation.
    """
    # First check if pip-installed version is available
    try:
        import langgraph.graph
        # Pip version available, don't add local source
        return
    except ImportError:
        # Pip version not available, try local source
        pass
    
    # Try libs/langgraph first (monorepo structure)
    if os.path.isdir(_LOCAL_LANGGRAPH) and _LOCAL_LANGGRAPH not in sys.path:
        sys.path.insert(0, _LOCAL_LANGGRAPH)
    # Also try root langgraph directory
    elif os.path.isdir(_LOCAL_LANGGRAPH_ROOT) and _LOCAL_LANGGRAPH_ROOT not in sys.path:
        sys.path.insert(0, _LOCAL_LANGGRAPH_ROOT)


def _import_module(name: str) -> Optional[ModuleType]:
    """Try importing a module safely."""
    import warnings
    # Suppress warnings that might interfere
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        try:
            return importlib.import_module(name)
        except Exception:
            return None


def load_langgraph_modules() -> dict:
    """
    Attempt to import LangGraph from local source first, then pip installation.

    Returns:
        dict with loaded modules (graph, prebuilt, checkpoint).
    """
    _ensure_local_langgraph_on_path()

    graph = _import_module("langgraph.graph")
    prebuilt = _import_module("langgraph.prebuilt")
    checkpoint = _import_module("langgraph.checkpoint")

    if not graph:
        raise ImportError("langgraph.graph not available (local or pip).")

    return {"graph": graph, "prebuilt": prebuilt, "checkpoint": checkpoint}


def require_class(module: ModuleType, attr: str, typename: str) -> Type[Any]:
    """Fetch attribute or raise a clear error."""
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise ImportError(f"Required {typename} '{attr}' missing from {module.__name__}") from exc


# Convenience accessors
def get_state_graph():
    mods = load_langgraph_modules()
    graph = mods["graph"]
    return require_class(graph, "StateGraph", "class")


def get_messages_state():
    mods = load_langgraph_modules()
    graph = mods["graph"]
    # MessagesState is optional in some versions; guard with ImportError
    return require_class(graph, "MessagesState", "class")


def get_end():
    mods = load_langgraph_modules()
    graph = mods["graph"]
    return require_class(graph, "END", "constant")


def get_tool_node():
    mods = load_langgraph_modules()
    prebuilt = mods["prebuilt"]
    if not prebuilt:
        raise ImportError("langgraph.prebuilt not available; ToolNode is required.")
    return require_class(prebuilt, "ToolNode", "class")


def get_tools_condition():
    mods = load_langgraph_modules()
    prebuilt = mods["prebuilt"]
    if not prebuilt:
        raise ImportError("langgraph.prebuilt not available; tools_condition is required.")
    return require_class(prebuilt, "tools_condition", "function")


def get_memory_saver():
    """Get MemorySaver from langgraph.checkpoint.memory"""
    try:
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver
    except ImportError:
        # Fallback to direct checkpoint module
        mods = load_langgraph_modules()
        checkpoint = mods["checkpoint"]
        if not checkpoint:
            raise ImportError("langgraph.checkpoint not available; MemorySaver is required.")
        return require_class(checkpoint, "MemorySaver", "class")


def get_sqlite_saver():
    mods = load_langgraph_modules()
    checkpoint = mods["checkpoint"]
    if not checkpoint:
        raise ImportError("langgraph.checkpoint not available; SqliteSaver is required.")
    return require_class(checkpoint, "SqliteSaver", "class")
