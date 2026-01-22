"""
Recovery node for LangGraph.
"""

from typing import Dict, Any


class RecoveryNode:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        attempts = state.get("recovery_attempts", 0) + 1
        state["recovery_attempts"] = attempts
        if attempts > self.max_retries:
            state["status"] = "failed"
            state["error"] = state.get("error") or "Max recovery attempts exceeded"
            state["circuit_open"] = True
        else:
            state["status"] = "retrying"
        return state
