from typing import Dict, Any
from shail.core.types import TaskRequest, TaskResult, TaskStatus
from shail.safety.exceptions import PermissionRequired


class SimpleGraphExecutor:
    """
    Executor that runs an agent with the request and returns a TaskResult.
    This is a simplified version - in Phase 2 we'll replace with full LangGraph.
    """

    def __init__(self, agent, task_id: str = None):
        self.agent = agent
        self.task_id = task_id
        
        # Add to approved context if permission is already approved
        if task_id:
            from shail.safety.permission_manager import PermissionManager
            if PermissionManager.is_approved(task_id):
                PermissionManager.add_approved_context(task_id)

    def run(self, req: TaskRequest) -> TaskResult:
        """
        Execute the agent's plan -> act workflow.
        
        Handles PermissionRequired exceptions by returning AWAITING_APPROVAL status.
        """
        try:
            # Plan step (can be used for logging/analysis)
            plan = self.agent.plan(req.text)
            
            # Act step (executes with tools)
            summary, artifacts = self.agent.act(req.text)
            
            return TaskResult(
                status=TaskStatus.COMPLETED,
                summary=summary,
                agent=self.agent.name,
                artifacts=artifacts or [],
                task_id=self.task_id
            )
        except PermissionRequired as e:
            # Tool requires permission - check if already approved
            from shail.safety.permission_manager import PermissionManager
            
            if self.task_id:
                # Check if permission was already approved (task was resumed)
                if PermissionManager.is_approved(self.task_id):
                    # Permission already approved - execute the tool directly
                    # Import the tool and execute it manually
                    try:
                        # Desktop control tools
                        if e.tool_name == "click_mouse":
                            from shail.tools.desktop import _execute_click_mouse_approved
                            result = _execute_click_mouse_approved(**e.args)
                        elif e.tool_name == "move_mouse":
                            from shail.tools.desktop import _execute_move_mouse_approved
                            result = _execute_move_mouse_approved(**e.args)
                        elif e.tool_name == "scroll_mouse":
                            from shail.tools.desktop import _execute_scroll_mouse_approved
                            result = _execute_scroll_mouse_approved(**e.args)
                        elif e.tool_name == "type_text":
                            from shail.tools.desktop import _execute_type_text_approved
                            result = _execute_type_text_approved(**e.args)
                        elif e.tool_name == "press_key":
                            from shail.tools.desktop import _execute_press_key_approved
                            result = _execute_press_key_approved(**e.args)
                        elif e.tool_name == "press_hotkey":
                            from shail.tools.desktop import _execute_press_hotkey_approved
                            result = _execute_press_hotkey_approved(**e.args)
                        elif e.tool_name == "focus_window":
                            from shail.tools.desktop import _execute_focus_window_approved
                            result = _execute_focus_window_approved(**e.args)
                        # OS tools
                        elif e.tool_name == "run_command":
                            from shail.tools.os import _execute_run_command_approved
                            result = _execute_run_command_approved(**e.args)
                        elif e.tool_name == "open_app":
                            from shail.tools.os import _execute_open_app_approved
                            result = _execute_open_app_approved(**e.args)
                        elif e.tool_name == "close_app":
                            from shail.tools.os import _execute_close_app_approved
                            result = _execute_close_app_approved(**e.args)
                        else:
                            # Unknown tool - re-run agent to continue
                            summary, artifacts = self.agent.act(req.text)
                            return TaskResult(
                                status=TaskStatus.COMPLETED,
                                summary=f"{summary} (approved tool executed: {e.tool_name})",
                                agent=self.agent.name,
                                artifacts=artifacts or [],
                                task_id=self.task_id
                            )
                        
                        # Tool executed successfully - re-run agent to continue workflow
                        summary, artifacts = self.agent.act(req.text)
                        return TaskResult(
                            status=TaskStatus.COMPLETED,
                            summary=f"{summary} (approved tool executed: {e.tool_name})",
                            agent=self.agent.name,
                            artifacts=artifacts or [],
                            task_id=self.task_id
                        )
                    except Exception as exec_error:
                        # Tool execution failed even with approval
                        return TaskResult(
                            status=TaskStatus.FAILED,
                            summary=f"Approved tool {e.tool_name} execution failed: {str(exec_error)}",
                            agent=self.agent.name,
                            artifacts=[],
                            task_id=self.task_id
                        )
                    except PermissionRequired:
                        # Tool still raised permission (shouldn't happen if approved, but handle it)
                        pass
                
                # Request permission
                permission_req = PermissionManager.request_permission(
                    task_id=self.task_id,
                    tool_name=e.tool_name,
                    tool_args=e.args,
                    rationale=e.rationale
                )
                
                return TaskResult(
                    status=TaskStatus.AWAITING_APPROVAL,
                    summary=f"Awaiting approval to {e.tool_name}: {e.rationale}",
                    agent=self.agent.name,
                    artifacts=[],
                    permission_request=permission_req,
                    task_id=self.task_id
                )
            else:
                # No task_id yet - this shouldn't happen, but handle gracefully
                return TaskResult(
                    status=TaskStatus.FAILED,
                    summary=f"Permission required but no task_id available: {e.rationale}",
                    agent=self.agent.name,
                    artifacts=[]
                )
        except Exception as e:
            return TaskResult(
                status=TaskStatus.FAILED,
                summary=f"Execution failed: {str(e)}",
                agent=self.agent.name,
                artifacts=[],
                task_id=self.task_id
            )


