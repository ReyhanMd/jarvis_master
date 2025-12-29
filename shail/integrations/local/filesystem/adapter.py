"""File system adapter for SHAIL MCP integration."""

import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class FileSystemAdapter:
    """
    Adapter for macOS file system integration via MCP.
    
    This adapter allows SHAIL to:
    - Watch files
    - Perform directory operations
    - Manage files
    """
    
    def __init__(self):
        """Initialize the FileSystem adapter."""
        self.name = "filesystem"
        self.category = "local"
        logger.info("Initialized FileSystem adapter")
    
    def list_directory(self, directory: str) -> List[Dict[str, Any]]:
        """
        List files and directories.
        
        Args:
            directory: Directory path
            
        Returns:
            List of file/directory information
        """
        path = Path(directory)
        if not path.exists():
            return [{"error": f"Directory not found: {directory}"}]
        
        items = []
        for item in path.iterdir():
            items.append({
                "name": item.name,
                "path": str(item),
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        
        return items
    
    def watch_file(self, file_path: str) -> Dict[str, Any]:
        """
        Watch a file for changes (stub).
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with watch result
        """
        # Stub implementation - would use watchdog or similar
        return {
            "success": False,
            "error": "File watching not yet implemented - requires watchdog library",
            "file_path": file_path,
        }
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get adapter capabilities.
        
        Returns:
            Dictionary describing what this adapter can do
        """
        return {
            "name": self.name,
            "category": self.category,
            "capabilities": [
                "list_directory",
                "watch_file",
            ],
            "status": "basic",
        }


# MCP tool registration functions
def register_filesystem_tools(provider):
    """
    Register FileSystem tools with MCP provider.
    
    Args:
        provider: MCPProvider instance
    """
    adapter = FileSystemAdapter()
    
    @provider.register_tool
    def list_directory(directory: str) -> List[Dict[str, Any]]:
        """List files and directories."""
        return adapter.list_directory(directory)
    
    # Register the adapter as a provider
    provider.register_provider("filesystem", adapter, category="local")
    
    logger.info("Registered FileSystem tools with MCP provider")
