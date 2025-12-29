"""PyBullet adapter for SHAIL MCP integration."""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class PyBulletAdapter:
    """
    Adapter for PyBullet integration via MCP.
    
    This adapter allows SHAIL to:
    - Set up physics simulations
    - Query physics state
    - Run simulations
    """
    
    def __init__(self):
        """Initialize the PyBullet adapter."""
        self.name = "pybullet"
        self.category = "engineering"
        self.simulator = None
        logger.info("Initialized PyBullet adapter")
    
    def setup_simulation(self, gravity: float = -9.81) -> Dict[str, Any]:
        """
        Set up a new physics simulation.
        
        Args:
            gravity: Gravity value
            
        Returns:
            Dictionary with setup information
        """
        from shail.integrations.tools.pybullet.simulator import PyBulletSimulator
        
        if self.simulator is None:
            self.simulator = PyBulletSimulator()
        
        return self.simulator.setup_simulation(gravity)
    
    def query_physics(self, query: str) -> Dict[str, Any]:
        """
        Query physics state.
        
        Args:
            query: Query string
            
        Returns:
            Dictionary with query results
        """
        if self.simulator is None:
            return {"error": "Simulation not initialized. Call setup_simulation first."}
        
        return self.simulator.query_physics(query)
    
    def add_body(self, body_type: str, position: List[float], **kwargs) -> int:
        """
        Add a body to the simulation.
        
        Args:
            body_type: Type of body
            position: [x, y, z] position
            **kwargs: Additional parameters
            
        Returns:
            Body ID
        """
        if self.simulator is None:
            raise RuntimeError("Simulation not initialized. Call setup_simulation first.")
        
        return self.simulator.add_body(body_type, position, **kwargs)
    
    def step_simulation(self, steps: int = 1) -> Dict[str, Any]:
        """
        Step the simulation forward.
        
        Args:
            steps: Number of steps
            
        Returns:
            Dictionary with step results
        """
        if self.simulator is None:
            return {"error": "Simulation not initialized. Call setup_simulation first."}
        
        return self.simulator.step_simulation(steps)
    
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
                "setup_simulation",
                "query_physics",
                "add_body",
                "step_simulation",
            ],
            "requires_pybullet": True,
            "note": "Full functionality requires PyBullet installation",
        }


# MCP tool registration functions
def register_pybullet_tools(provider):
    """
    Register PyBullet tools with MCP provider.
    
    Args:
        provider: MCPProvider instance
    """
    adapter = PyBulletAdapter()
    
    @provider.register_tool
    def setup_pybullet_simulation(gravity: float = -9.81) -> Dict[str, Any]:
        """Set up a new PyBullet physics simulation."""
        return adapter.setup_simulation(gravity)
    
    @provider.register_tool
    def query_pybullet_physics(query: str) -> Dict[str, Any]:
        """Query physics state from PyBullet simulation."""
        return adapter.query_physics(query)
    
    @provider.register_tool
    def step_pybullet_simulation(steps: int = 1) -> Dict[str, Any]:
        """Step the PyBullet simulation forward."""
        return adapter.step_simulation(steps)
    
    # Register the adapter as a provider
    provider.register_provider("pybullet", adapter, category="engineering")
    
    logger.info("Registered PyBullet tools with MCP provider")
