import os
from typing import Optional, List
from langchain_core.tools import tool

BASE_DIR = os.path.abspath(os.path.join(os.getcwd(), "workspace"))
os.makedirs(BASE_DIR, exist_ok=True)


def _resolve_path(rel_path: str) -> str:
    """Resolve relative path within workspace, ensuring no directory traversal."""
    abspath = os.path.abspath(os.path.join(BASE_DIR, rel_path))
    if not abspath.startswith(BASE_DIR):
        raise ValueError("Access outside workspace is not allowed")
    parent_dir = os.path.dirname(abspath)
    os.makedirs(parent_dir, exist_ok=True)
    return abspath


@tool
def write_text_file(rel_path: str, content: str) -> str:
    """Write text content to a file in the workspace. Creates directories as needed.
    
    Args:
        rel_path: Relative path from workspace root (e.g., 'project/main.py')
        content: Text content to write
        
    Returns:
        Absolute path of created file
    """
    path = _resolve_path(rel_path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote {rel_path} ({len(content)} chars)"


@tool
def read_text_file(rel_path: str) -> str:
    """Read text content from a file in the workspace.
    
    Args:
        rel_path: Relative path from workspace root
        
    Returns:
        File contents as string
    """
    path = _resolve_path(rel_path)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@tool
def list_files(rel_dir: str = ".") -> List[str]:
    """List files and directories in a workspace directory.
    
    Args:
        rel_dir: Relative directory path (default: workspace root)
        
    Returns:
        List of file/directory names
    """
    path = _resolve_path(rel_dir)
    if not os.path.isdir(path):
        raise ValueError(f"Not a directory: {rel_dir}")
    return sorted(os.listdir(path))


@tool
def delete_file(rel_path: str) -> str:
    """Delete a file in the workspace.
    
    Args:
        rel_path: Relative path from workspace root
        
    Returns:
        Confirmation message
    """
    path = _resolve_path(rel_path)
    if not os.path.exists(path):
        return f"File not found: {rel_path}"
    os.remove(path)
    return f"Deleted {rel_path}"


@tool
def create_directory(rel_path: str) -> str:
    """Create a directory in the workspace (and parent directories as needed).
    
    Args:
        rel_path: Relative path from workspace root
        
    Returns:
        Confirmation message
    """
    path = _resolve_path(rel_path)
    os.makedirs(path, exist_ok=True)
    return f"Created directory {rel_path}"


