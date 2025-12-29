"""GNU Octave adapter for SHAIL MCP integration."""

import logging
import subprocess
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class OctaveAdapter:
    """
    Adapter for GNU Octave integration via MCP.
    
    This adapter allows SHAIL to:
    - Execute Octave scripts
    - Run Octave commands
    """
    
    def __init__(self):
        """Initialize the Octave adapter."""
        self.name = "octave"
        self.category = "engineering"
        logger.info("Initialized Octave adapter")
    
    def execute_script(self, script_path: str) -> Dict[str, Any]:
        """
        Execute an Octave script.
        
        Args:
            script_path: Path to the Octave script (.m file)
            
        Returns:
            Dictionary with execution result
        """
        path = Path(script_path)
        
        if not path.exists():
            return {"error": f"Script not found: {script_path}"}
        
        try:
            result = subprocess.run(
                ["octave", "--no-gui", script_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Octave not found - please install GNU Octave",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Script execution timed out",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def execute_command(self, command: str) -> Dict[str, Any]:
        """
        Execute an Octave command.
        
        Args:
            command: Octave command string
            
        Returns:
            Dictionary with execution result
        """
        try:
            result = subprocess.run(
                ["octave", "--no-gui", "--eval", command],
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Octave not found - please install GNU Octave",
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
            "capabilities": [
                "execute_script",
                "execute_command",
            ],
            "requires_octave": True,
            "note": "Requires GNU Octave to be installed and in PATH",
        }


# MCP tool registration functions
def register_octave_tools(provider):
    """
    Register Octave tools with MCP provider.
    
    Args:
        provider: MCPProvider instance
    """
    adapter = OctaveAdapter()
    
    @provider.register_tool
    def execute_octave_script(script_path: str) -> Dict[str, Any]:
        """Execute an Octave script."""
        return adapter.execute_script(script_path)
    
    @provider.register_tool
    def execute_octave_command(command: str) -> Dict[str, Any]:
        """Execute an Octave command."""
        return adapter.execute_command(command)
    
    # Register the adapter as a provider
    provider.register_provider("octave", adapter, category="engineering")
    
    logger.info("Registered Octave tools with MCP provider")
