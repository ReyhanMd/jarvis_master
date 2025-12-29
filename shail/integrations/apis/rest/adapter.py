"""Generic REST API adapter framework for SHAIL MCP integration."""

import logging
import httpx
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class RESTAdapter:
    """
    Generic REST API adapter framework.
    
    This adapter provides a framework for integrating with any REST API
    via MCP. It can be configured for specific APIs.
    """
    
    def __init__(self, base_url: str, name: str = "rest_api"):
        """
        Initialize the REST adapter.
        
        Args:
            base_url: Base URL for the REST API
            name: Name for this adapter instance
        """
        self.name = name
        self.base_url = base_url.rstrip('/')
        self.category = "api"
        self.client = None
        logger.info(f"Initialized REST adapter: {name} ({base_url})")
    
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Perform a GET request.
        
        Args:
            endpoint: API endpoint (relative to base_url)
            params: Optional query parameters
            
        Returns:
            Dictionary with response data
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            response = httpx.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            return {
                "success": True,
                "data": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
                "status_code": response.status_code,
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Perform a POST request.
        
        Args:
            endpoint: API endpoint
            data: Optional request body
            
        Returns:
            Dictionary with response data
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            response = httpx.post(url, json=data, timeout=30)
            response.raise_for_status()
            
            return {
                "success": True,
                "data": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
                "status_code": response.status_code,
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
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
            "base_url": self.base_url,
            "capabilities": [
                "get",
                "post",
                "put",
                "delete",
            ],
        }


# MCP tool registration functions
def register_rest_adapter(provider, base_url: str, name: str = "rest_api"):
    """
    Register a REST API adapter with MCP provider.
    
    Args:
        provider: MCPProvider instance
        base_url: Base URL for the REST API
        name: Name for this adapter
    """
    adapter = RESTAdapter(base_url, name)
    
    @provider.register_tool
    def rest_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform a GET request to the REST API."""
        return adapter.get(endpoint, params)
    
    @provider.register_tool
    def rest_post(endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform a POST request to the REST API."""
        return adapter.post(endpoint, data)
    
    # Register the adapter as a provider
    provider.register_provider(name, adapter, category="api")
    
    logger.info(f"Registered REST adapter '{name}' with MCP provider")
