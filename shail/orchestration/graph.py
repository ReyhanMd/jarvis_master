from typing import Dict, Any, Optional
from shail.core.types import TaskRequest, TaskResult, TaskStatus
from shail.safety.exceptions import PermissionRequired

logger = None
try:
    import logging
    logger = logging.getLogger(__name__)
except:
    pass


class LangGraphExecutor:
    """
    LangGraph-based executor for stateful workflows and multi-agent orchestration.
    
    This replaces SimpleGraphExecutor with LangGraph for:
    - Stateful workflows
    - Multi-agent orchestration
    - LLM-to-LLM communication
    """
    
    def __init__(self, agent, task_id: str = None):
        """
        Initialize LangGraph executor.
        
        Args:
            agent: Agent to execute
            task_id: Optional task ID
        """
        self.agent = agent
        self.task_id = task_id
        self.use_langgraph = False
        
        # Try to import LangGraph
        try:
            from langgraph.graph import StateGraph, END
            self.use_langgraph = True
            self.StateGraph = StateGraph
            self.END = END
            if logger:
                logger.info("LangGraph available - using LangGraph executor")
        except ImportError:
            if logger:
                logger.warning("LangGraph not available - falling back to SimpleGraphExecutor")
    
    def build_graph(self) -> Optional[Any]:
        """
        Build LangGraph workflow graph.
        
        Returns:
            LangGraph StateGraph or None if LangGraph not available
        """
        if not self.use_langgraph:
            return None
        
        # Build stateful workflow graph
        # In full implementation, would create nodes for:
        # - Master LLM (Kimi-K2)
        # - Worker LLMs (Gemini, ChatGPT)
        # - Tool execution nodes
        # - Decision nodes
        
        workflow = self.StateGraph(Dict[str, Any])
        
        # Add nodes (stub implementation)
        # workflow.add_node("master_llm", self._master_llm_node)
        # workflow.add_node("worker_llm", self._worker_llm_node)
        # workflow.add_node("tool_execution", self._tool_execution_node)
        
        # Set entry point
        # workflow.set_entry_point("master_llm")
        
        # Add edges
        # workflow.add_edge("master_llm", "worker_llm")
        # workflow.add_edge("worker_llm", self.END)
        
        # Compile graph
        # app = workflow.compile()
        # return app
        
        # For now, return None to use SimpleGraphExecutor
        return None
    
    def run(self, req: TaskRequest) -> TaskResult:
        """
        Execute using LangGraph if available, otherwise fall back to SimpleGraphExecutor.
        
        Args:
            req: Task request
            
        Returns:
            Task result
        """
        graph = self.build_graph()
        
        if graph:
            # Use LangGraph execution
            # result = graph.invoke({"request": req.text, "task_id": self.task_id})
            # return self._convert_langgraph_result(result)
            pass
        
        # Fall back to SimpleGraphExecutor
        return SimpleGraphExecutor(self.agent, self.task_id).run(req)
    
    def _convert_langgraph_result(self, result: Dict[str, Any]) -> TaskResult:
        """Convert LangGraph result to TaskResult."""
        return TaskResult(
            status=TaskStatus.COMPLETED,
            summary=result.get("summary", ""),
            agent=self.agent.name,
            artifacts=result.get("artifacts", []),
            task_id=self.task_id,
        )


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
        # Set task_id in thread-local context so tools can access it
        from shail.safety.context import set_current_task_id, clear_current_task_id
        
        try:
            if self.task_id:
                set_current_task_id(self.task_id)
            
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
        finally:
            # Always clear context when done
            clear_current_task_id()


