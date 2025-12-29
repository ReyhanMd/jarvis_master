"""Universal file loader adapter for SHAIL MCP integration."""

import logging
from typing import Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class FileLoaderAdapter:
    """
    Universal file loader adapter for SHAIL.
    
    This adapter can load and parse various file types:
    - CAD files (FCStd, SLDPRT, etc.)
    - Images (JPG, PNG, etc.)
    - Documents (PDF, DOCX, etc.)
    - Code files (Python, JavaScript, etc.)
    """
    
    def __init__(self):
        """Initialize the file loader adapter."""
        self.name = "file_loader"
        self.category = "utility"
        logger.info("Initialized FileLoader adapter")
    
    def load_file(self, file_path: str) -> Dict[str, Any]:
        """
        Load and parse a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with file information and parsed content
        """
        from shail.integrations.tools.file_loader.parsers import parse_file
        
        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}"}
        
        parsed = parse_file(file_path)
        return parsed
    
    def load_files(self, file_paths: List[str]) -> List[Dict[str, Any]]:
        """
        Load multiple files.
        
        Args:
            file_paths: List of file paths
            
        Returns:
            List of parsed file dictionaries
        """
        results = []
        for file_path in file_paths:
            try:
                result = self.load_file(file_path)
                results.append(result)
            except Exception as e:
                results.append({"error": str(e), "file_path": file_path})
        
        return results
    
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
                "load_cad_files",
                "load_image_files",
                "load_document_files",
                "load_code_files",
            ],
            "supported_formats": {
                "cad": [".fcstd", ".sldprt", ".sldasm", ".step", ".stp"],
                "image": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg"],
                "document": [".pdf", ".docx", ".xlsx", ".pptx"],
                "code": [".py", ".js", ".ts", ".jsx", ".java", ".cpp"],
            },
        }


# MCP tool registration functions
def register_file_loader_tools(provider):
    """
    Register file loader tools with MCP provider.
    
    Args:
        provider: MCPProvider instance
    """
    adapter = FileLoaderAdapter()
    
    @provider.register_tool
    def load_file(file_path: str) -> Dict[str, Any]:
        """Load and parse a file."""
        return adapter.load_file(file_path)
    
    @provider.register_tool
    def load_files(file_paths: List[str]) -> List[Dict[str, Any]]:
        """Load multiple files."""
        return adapter.load_files(file_paths)
    
    # Register the adapter as a provider
    provider.register_provider("file_loader", adapter, category="utility")
    
    logger.info("Registered file loader tools with MCP provider")
