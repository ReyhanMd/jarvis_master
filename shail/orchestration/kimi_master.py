"""Kimi-K2 Master Planner for SHAIL."""

import logging
from typing import Dict, Any, Optional
from shail.llm.kimi_k2 import KimiK2Client

logger = logging.getLogger(__name__)


class KimiMasterPlanner:
    """
    Master planner using Kimi-K2 as the orchestrating LLM.
    
    This replaces or enhances the existing master planner to use
    Kimi-K2 for task routing and orchestration.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Kimi-K2 master planner.
        
        Args:
            api_key: Kimi-K2 API key
        """
        self.client = KimiK2Client(api_key)
        logger.info("Initialized KimiMasterPlanner")
    
    def plan_task(self, request: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Plan a task using Kimi-K2.
        
        Args:
            request: User request text
            context: Optional context from RAG
            
        Returns:
            Dictionary with plan
        """
        # Build messages for Kimi-K2
        messages = [
            {
                "role": "system",
                "content": "You are SHAIL's master planner. Route tasks to appropriate agents and tools.",
            },
            {
                "role": "user",
                "content": f"Request: {request}\n\nContext: {context or 'No additional context'}",
            },
        ]
        
        # Get plan from Kimi-K2
        response = self.client.chat(messages, temperature=0.3)
        
        if not response.get("success"):
            return {
                "error": response.get("error", "Unknown error"),
            }
        
        # Parse response (in full implementation would parse structured plan)
        return {
            "plan": response.get("content", ""),
            "llm": "kimi_k2",
            "context": context,
        }
    
    def route_task(self, request: str) -> Dict[str, Any]:
        """
        Route a task to the appropriate agent/tool.
        
        Args:
            request: User request
            
        Returns:
            Dictionary with routing decision
        """
        plan = self.plan_task(request)
        
        # In full implementation, would parse plan and determine routing
        # For now, return the plan
        return {
            "routing": plan,
            "agent": "auto",  # Would be determined by Kimi-K2
        }
