"""Generic GraphQL API adapter framework for SHAIL MCP integration."""

import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class GraphQLAdapter:
    """
    Generic GraphQL API adapter framework.
    
    This adapter provides a framework for integrating with any GraphQL API
    via MCP.
    """
    
    def __init__(self, endpoint: str, name: str = "graphql_api"):
        """
        Initialize the GraphQL adapter.
        
        Args:
            endpoint: GraphQL API endpoint URL
            name: Name for this adapter instance
        """
        self.name = name
        self.endpoint = endpoint
        self.category = "api"
        logger.info(f"Initialized GraphQL adapter: {name} ({endpoint})")
    
    def query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a GraphQL query.
        
        Args:
            query: GraphQL query string
            variables: Optional query variables
            
        Returns:
            Dictionary with response data
        """
        payload = {
            "query": query,
        }
        
        if variables:
            payload["variables"] = variables
        
        try:
            response = httpx.post(
                self.endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            
            result = response.json()
            
            return {
                "success": "errors" not in result,
                "data": result.get("data"),
                "errors": result.get("errors"),
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def mutate(self, mutation: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a GraphQL mutation.
        
        Args:
            mutation: GraphQL mutation string
            variables: Optional mutation variables
            
        Returns:
            Dictionary with response data
        """
        return self.query(mutation, variables)
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get adapter capabilities.
        
        Returns:
            Dictionary describing what this adapter can do
        """
        return {
            "name": self.name,
            "category": self.category,
            "endpoint": self.endpoint,
            "capabilities": [
                "query",
                "mutate",
            ],
        }


# MCP tool registration functions
def register_graphql_adapter(provider, endpoint: str, name: str = "graphql_api"):
    """
    Register a GraphQL API adapter with MCP provider.
    
    Args:
        provider: MCPProvider instance
        endpoint: GraphQL API endpoint URL
        name: Name for this adapter
    """
    adapter = GraphQLAdapter(endpoint, name)
    
    @provider.register_tool
    def graphql_query(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a GraphQL query."""
        return adapter.query(query, variables)
    
    @provider.register_tool
    def graphql_mutate(mutation: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a GraphQL mutation."""
        return adapter.mutate(mutation, variables)
    
    # Register the adapter as a provider
    provider.register_provider(name, adapter, category="api")
    
    logger.info(f"Registered GraphQL adapter '{name}' with MCP provider")
