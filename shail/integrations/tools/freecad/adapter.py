"""FreeCAD adapter for SHAIL MCP integration."""

import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class FreeCADAdapter:
    """
    Adapter for FreeCAD integration via MCP.
    
    This adapter allows SHAIL to:
    - Read FreeCAD FCStd files
    - Query geometry information
    - Interact with FreeCAD models
    """
    
    def __init__(self):
        """Initialize the FreeCAD adapter."""
        self.name = "freecad"
        self.category = "engineering"
        logger.info("Initialized FreeCAD adapter")
    
    def read_file(self, file_path: str) -> Dict[str, Any]:
        """
        Read a FreeCAD FCStd file.
        
        Args:
            file_path: Path to the FCStd file
            
        Returns:
            Dictionary with file information
        """
        from shail.integrations.tools.freecad.file_reader import read_fcstd_file
        return read_fcstd_file(file_path)
    
    def query_geometry(self, file_path: str, query: Optional[str] = None) -> Dict[str, Any]:
        """
        Query geometry information from a FreeCAD file.
        
        Args:
            file_path: Path to the FCStd file
            query: Optional query string (e.g., "volume", "surface_area")
            
        Returns:
            Dictionary with geometry information
        """
        from shail.integrations.tools.freecad.file_reader import extract_geometry_info
        
        geometry = extract_geometry_info(file_path)
        
        if query:
            # In full implementation, would filter based on query
            geometry["query"] = query
            geometry["note"] = f"Query '{query}' requires full FreeCAD API"
        
        return geometry
    
    def list_objects(self, file_path: str) -> List[Dict[str, Any]]:
        """
        List objects in a FreeCAD file.
        
        Args:
            file_path: Path to the FCStd file
            
        Returns:
            List of object information dictionaries
        """
        geometry = self.query_geometry(file_path)
        return geometry.get("objects", [])
    
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
                "read_fcstd_files",
                "query_geometry",
                "list_objects",
            ],
            "file_formats": [".fcstd"],
            "requires_freecad": True,
            "note": "Full functionality requires FreeCAD Python API installation",
        }


# MCP tool registration functions
def register_freecad_tools(provider):
    """
    Register FreeCAD tools with MCP provider.
    
    Args:
        provider: MCPProvider instance
    """
    adapter = FreeCADAdapter()
    
    @provider.register_tool
    def read_freecad_file(file_path: str) -> Dict[str, Any]:
        """Read a FreeCAD FCStd file and return basic information."""
        return adapter.read_file(file_path)
    
    @provider.register_tool
    def query_freecad_geometry(file_path: str, query: Optional[str] = None) -> Dict[str, Any]:
        """Query geometry information from a FreeCAD file."""
        return adapter.query_geometry(file_path, query)
    
    @provider.register_tool
    def list_freecad_objects(file_path: str) -> List[Dict[str, Any]]:
        """List objects in a FreeCAD file."""
        return adapter.list_objects(file_path)
    
    # Register the adapter as a provider
    provider.register_provider("freecad", adapter, category="engineering")
    
    logger.info("Registered FreeCAD tools with MCP provider")
