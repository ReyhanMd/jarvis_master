"""
Permission handling node for LangGraph.
"""

from typing import Dict, Any
from shail.safety.permission_manager import PermissionManager


class PermissionNode:
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        task_id = state.get("task_id")
        permission_requests = state.get("permission_requests", [])

        pending = state.get("pending_permission")
        if pending:
            PermissionManager.request_permission(
                task_id=task_id,
                tool_name=pending.get("tool_name"),
                tool_args=pending.get("tool_args", {}),
                rationale=pending.get("rationale", ""),
            )
            permission_requests.append(pending)

        state.update(
            {
                "permission_requests": permission_requests,
                "status": "awaiting_approval",
            }
        )
        return state
