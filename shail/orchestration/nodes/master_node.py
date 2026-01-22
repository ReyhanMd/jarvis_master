"""
Master node for LangGraph orchestration.

Uses the existing MasterPlanner to route or enrich context before handing off to workers.
"""

from typing import Dict, Any
from shail.orchestration.master_planner import MasterPlanner


class MasterNode:
    def __init__(self):
        self.planner = MasterPlanner()

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich state with routing decision and synthesized context.
        """
        req_text = state.get("task_description") or state.get("request") or ""
        decision = self.planner.route_request(type("TaskRequest", (), {"text": req_text, "mode": "auto"}))

        agent_history = state.get("agent_history", [])
        agent_history.append(
            {
                "agent": decision.agent,
                "confidence": decision.confidence,
                "rationale": decision.rationale,
            }
        )

        state.update(
            {
                "agent": decision.agent,
                "agent_history": agent_history,
                "status": "planning",
            }
        )
        return state
