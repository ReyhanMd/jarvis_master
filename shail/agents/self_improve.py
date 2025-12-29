"""Self-Improvement Agent for SHAIL.

This agent allows SHAIL to propose and implement improvements to itself
using tool awareness (MCP), memory (RAG), and self-modification capabilities.
"""

import logging
from typing import Dict, Any, List, Optional
from shail.agents.base import AbstractAgent

logger = logging.getLogger(__name__)


class SelfImproveAgent(AbstractAgent):
    """
    Agent that proposes and implements improvements to SHAIL's codebase.
    
    Uses:
    - MCP to discover available tools
    - RAG to access memory and context
    - Self-modification tools to implement changes
    - Code introspection to understand structure
    """
    
    def __init__(self):
        """Initialize the self-improvement agent."""
        self.name = "self_improve"
        self.capabilities = ["propose_improvements", "create_patches", "implement_changes"]
        logger.info("Initialized SelfImproveAgent")
    
    def plan(self, text: str) -> str:
        """Plan phase for self-improvement agent."""
        return f"Planning improvement: {text}"
    
    def act(self, text: str):
        """Act phase for self-improvement agent."""
        from shail.core.types import Artifact
        return f"Acting on improvement: {text}", []
    
    def propose_improvement(
        self,
        target: str,
        rationale: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Propose an improvement to SHAIL's codebase.
        
        Args:
            target: What to improve (e.g., "freecad adapter", "rag memory")
            rationale: Why this improvement is needed
            context: Optional context from RAG
            
        Returns:
            Dictionary with improvement proposal
        """
        # Use MCP to discover available tools
        from shail.integrations.mcp.provider import get_provider
        mcp_provider = get_provider()
        available_tools = mcp_provider.discover_tools()
        
        # Use code introspection to understand current structure
        from shail.tools.code_introspection import analyze_architecture
        architecture = analyze_architecture()
        
        proposal = {
            "target": target,
            "rationale": rationale,
            "available_tools": list(available_tools.keys()),
            "architecture_context": architecture,
            "context": context,
            "status": "proposed",
        }
        
        logger.info(f"Proposed improvement: {target}")
        return proposal
    
    def create_patch(
        self,
        file_path: str,
        changes: Dict[str, Any],
        proposal: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a patch for a file modification.
        
        Args:
            file_path: Path to the file to modify
            changes: Dictionary with changes (old_content, new_content, etc.)
            proposal: Optional improvement proposal
            
        Returns:
            Dictionary with patch information
        """
        from shail.tools.self_mod import read_shail_code, get_code_diff, backup_file
        
        # Read current code
        current = read_shail_code(file_path)
        if "error" in current:
            return {"error": current["error"]}
        
        old_content = current["content"]
        new_content = changes.get("new_content", old_content)
        
        # Generate diff
        diff = get_code_diff(old_content, new_content)
        
        # Create backup
        backup_path = backup_file(file_path)
        
        patch = {
            "file_path": file_path,
            "backup_path": backup_path,
            "diff": diff,
            "proposal": proposal,
            "status": "pending_approval",
        }
        
        logger.info(f"Created patch for {file_path}")
        return patch
    
    def implement_improvement(
        self,
        proposal: Dict[str, Any],
        patch: Dict[str, Any],
        approved: bool = False,
    ) -> Dict[str, Any]:
        """
        Implement an improvement (requires approval).
        
        Args:
            proposal: Improvement proposal
            patch: Patch to apply
            approved: Whether the change is approved
            
        Returns:
            Dictionary with implementation result
        """
        if not approved:
            return {
                "error": "Improvement requires approval",
                "proposal": proposal,
                "patch": patch,
            }
        
        from shail.tools.self_mod import write_shail_code
        from shail.tools.code_validation import validate_python_syntax
        
        # Validate syntax
        new_content = patch.get("diff", {}).get("new_content")
        if new_content:
            validation = validate_python_syntax(new_content)
            if not validation["valid"]:
                return {
                    "error": "Syntax validation failed",
                    "validation": validation,
                }
        
        # Write the code (with approval flag set)
        result = write_shail_code(
            patch["file_path"],
            new_content or "",
            create_backup=False,  # Already backed up
            require_approval=False,  # Already approved
        )
        
        # Log to RAG
        from shail.memory.rag import store_architecture_note_for_rag
        store_architecture_note_for_rag(
            "integration",
            f"Self-improvement: {proposal.get('target', 'unknown')}",
            f"Implemented improvement: {proposal.get('rationale', '')}",
        )
        
        logger.info(f"Implemented improvement: {proposal.get('target')}")
        return result
    
    def analyze_codebase(self) -> Dict[str, Any]:
        """
        Analyze the codebase to find improvement opportunities.
        
        Returns:
            Dictionary with analysis and suggestions
        """
        from shail.tools.code_introspection import (
            analyze_architecture,
            list_shail_modules,
        )
        
        architecture = analyze_architecture()
        modules = list_shail_modules()
        
        # Simple analysis - in full implementation would use LLM
        suggestions = []
        
        # Check for missing integrations
        expected_integrations = ["mcp", "tools", "apis", "local"]
        for expected in expected_integrations:
            if expected not in architecture.get("integrations", []):
                suggestions.append({
                    "type": "missing_integration",
                    "target": expected,
                    "priority": "medium",
                })
        
        return {
            "architecture": architecture,
            "modules_count": len(modules),
            "suggestions": suggestions,
        }
