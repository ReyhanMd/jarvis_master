from typing import Dict, Any, Optional
import asyncio
import time
from shail.core.types import TaskRequest, TaskResult, TaskStatus
from shail.safety.exceptions import PermissionRequired
from shail.safety.context import set_current_task_id, clear_current_task_id
from shail.safety.permission_manager import PermissionManager
from shail.orchestration.langgraph_integration import (
    get_state_graph,
    get_end,
)
from shail.orchestration.checkpointing import create_checkpointer
from shail.orchestration.nodes.master_node import MasterNode
from shail.orchestration.nodes.worker_nodes import WorkerNodes
from shail.orchestration.nodes.permission_node import PermissionNode
from shail.orchestration.nodes.recovery_node import RecoveryNode
from apps.shail.websocket_server import websocket_manager as brain_ws_manager
from apps.shail.settings import get_settings

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
    
    def __init__(self, agent, task_id: str = None, persistent: bool = True):
        """
        Initialize LangGraph executor.
        
        Args:
            agent: Agent to execute
            task_id: Optional task ID
            persistent: Whether to use persistent checkpoints
        """
        self.agent = agent
        self.task_id = task_id
        self.use_langgraph = True
        self.persistent = persistent
        self.StateGraph = get_state_graph()
        self.END = get_end()
        self.checkpointer = create_checkpointer(persistent=persistent)
        self.master_node = MasterNode()
        self.worker_nodes = WorkerNodes()
        self.permission_node = PermissionNode()
        self.recovery_node = RecoveryNode()
        if logger:
            logger.info("LangGraph available - using LangGraph executor")
    
    def build_graph(self) -> Optional[Any]:
        """
        Build LangGraph workflow graph.
        
        Returns:
            LangGraph compiled app or None if LangGraph not available
        """
        if not self.use_langgraph:
            return None

        workflow = self.StateGraph(Dict[str, Any])

        async def master_step(state: Dict[str, Any]):
            return self.master_node(state)

        async def worker_step(state: Dict[str, Any]):
            return self.worker_nodes(state)

        async def act_step(state: Dict[str, Any]):
            try:
                if self.task_id:
                    set_current_task_id(self.task_id)
                # Agent act handles tools and permissions internally
                summary, artifacts = self.agent.act(state.get("task_description", ""))
                tool_history = state.get("tool_history", [])
                tool_history.append({"agent": getattr(self.agent, "name", "agent"), "summary": summary})
                state.update(
                    {
                        "summary": summary,
                        "artifacts": artifacts or [],
                        "tool_history": tool_history,
                        "status": "verifying",
                    }
                )
                return state
            except PermissionRequired as e:
                state["pending_permission"] = {
                    "tool_name": e.tool_name,
                    "tool_args": e.args,
                    "rationale": e.rationale,
                }
                state["status"] = "awaiting_approval"
                return state
            except Exception as exc:
                state["error"] = str(exc)
                state["status"] = "error"
                return state
            finally:
                clear_current_task_id()

        async def permission_step(state: Dict[str, Any]):
            return self.permission_node(state)

        async def recovery_step(state: Dict[str, Any]):
            return self.recovery_node(state)

        async def finalize_step(state: Dict[str, Any]):
            state["status"] = "completed"
            return state

        workflow.add_node("master", master_step)
        workflow.add_node("worker", worker_step)
        workflow.add_node("act", act_step)
        workflow.add_node("permission", permission_step)
        workflow.add_node("recovery", recovery_step)
        workflow.add_node("finalize", finalize_step)

        workflow.set_entry_point("master")
        workflow.add_edge("master", "worker")
        workflow.add_edge("worker", "act")

        def route_after_act(state: Dict[str, Any]):
            if state.get("status") == "awaiting_approval" or state.get("pending_permission"):
                return "permission"
            if state.get("error"):
                return "recovery"
            return "finalize"

        workflow.add_conditional_edges(
            "act",
            route_after_act,
            {
                "permission": "permission",
                "recovery": "recovery",
                "finalize": "finalize",
            },
        )
        workflow.add_edge("permission", "finalize")
        workflow.add_edge("recovery", "act")
        workflow.add_edge("finalize", self.END)

        return workflow.compile(checkpointer=self.checkpointer)
    
    def run(self, req: TaskRequest) -> TaskResult:
        """
        Execute using LangGraph if available, otherwise fall back to SimpleGraphExecutor.
        
        Uses streaming for real-time incremental updates via WebSocket.
        
        Args:
            req: Task request
            
        Returns:
            Task result
        """
        graph = self.build_graph()
        
        if graph:
            start_time = time.time()
            settings = get_settings()
            desktop_id = getattr(req, "desktop_id", None)
            # #region agent log
            import json
            with open('/Users/reyhan/shail_master/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"test-desktop-id","hypothesisId":"H","location":"graph.py:run","message":"Creating initial state","data":{"desktop_id":desktop_id,"task_id":self.task_id},"timestamp":time.time()})+'\n')
            # #endregion
            initial_state = {
                "task_description": req.text,
                "request": req.text,
                "task_id": self.task_id,
                "desktop_id": desktop_id,  # Include desktop context
                "services": {
                    "ui_twin": settings.ui_twin_url,
                    "action_executor": settings.action_executor_url,
                    "vision": settings.vision_url,
                    "rag": settings.rag_url,
                },
                "context": [],
                "plan_steps": [],
                "execution_results": [],
                "current_step": 0,
                "status": "planning",
                "agent_history": [],
                "tool_history": [],
                "recovery_attempts": 0,
                "permission_requests": [],
            }
            # #region agent log
            with open('/Users/reyhan/shail_master/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"test-desktop-id","hypothesisId":"H","location":"graph.py:run","message":"Initial state created","data":{"desktop_id_in_state":initial_state.get("desktop_id")},"timestamp":time.time()})+'\n')
            # #endregion

            config = {"configurable": {"thread_id": self.task_id}}
            result_state = None
            
            # Use streaming for incremental updates
            try:
                # Check if we're in an async context
                try:
                    loop = asyncio.get_running_loop()
                    # We're in async context - schedule streaming task
                    # Note: This method is called from sync context, so we use sync streaming
                    # For true async, the caller should use run_async() method
                    result_state = self._run_streaming_sync(graph, initial_state, config)
                except RuntimeError:
                    # No event loop running - use sync streaming
                    result_state = self._run_streaming_sync(graph, initial_state, config)
            except Exception as e:
                if logger:
                    logger.error(f"Streaming failed, falling back to invoke: {e}")
                # Fallback to non-streaming
                result_state = graph.invoke(initial_state, config=config)
                if brain_ws_manager:
                    try:
                        asyncio.run(brain_ws_manager.broadcast_state(result_state))
                    except RuntimeError:
                        loop = asyncio.get_event_loop()
                        loop.create_task(brain_ws_manager.broadcast_state(result_state))
            
            if result_state:
                result_state["metrics"] = {
                    "duration_ms": (time.time() - start_time) * 1000,
                    "recovery_attempts": result_state.get("recovery_attempts", 0),
                    "tool_calls": len(result_state.get("tool_history", [])),
                }
                # Final state broadcast
                if brain_ws_manager:
                    try:
                        asyncio.run(brain_ws_manager.broadcast_state(result_state))
                    except RuntimeError:
                        loop = asyncio.get_event_loop()
                        loop.create_task(brain_ws_manager.broadcast_state(result_state))
                return self._convert_langgraph_result(result_state)
        
        # Fall back to SimpleGraphExecutor
        return SimpleGraphExecutor(self.agent, self.task_id).run(req)
    
    def _run_streaming_sync(self, graph, initial_state, config):
        """Run graph with streaming in sync context."""
        result_state = None
        
        # Use astream for incremental updates
        async def stream_and_collect():
            nonlocal result_state
            async for event in graph.astream(initial_state, config=config, stream_mode="updates"):
                # event is a dict with node names as keys and state updates as values
                for node_name, state_update in event.items():
                    # Broadcast incremental state update
                    if brain_ws_manager:
                        try:
                            await brain_ws_manager.broadcast_event("node_update", {
                                "node": node_name,
                                "state": state_update,
                            })
                        except Exception as e:
                            if logger:
                                logger.warning(f"Failed to broadcast node update: {e}")
                    
                    # Track latest state
                    if result_state is None:
                        result_state = state_update.copy()
                    else:
                        result_state.update(state_update)
            
            # Get final state
            if result_state is None:
                result_state = await graph.ainvoke(initial_state, config=config)
            return result_state
        
        # Run async function in sync context
        result_state = asyncio.run(stream_and_collect())
        return result_state
    
    async def _run_streaming_async(self, graph, initial_state, config, loop):
        """Run graph with streaming in async context."""
        result_state = None
        
        async for event in graph.astream(initial_state, config=config, stream_mode="updates"):
            # event is a dict with node names as keys and state updates as values
            for node_name, state_update in event.items():
                # Broadcast incremental state update
                if brain_ws_manager:
                    try:
                        await brain_ws_manager.broadcast_event("node_update", {
                            "node": node_name,
                            "state": state_update,
                        })
                    except Exception as e:
                        if logger:
                            logger.warning(f"Failed to broadcast node update: {e}")
                
                # Track latest state
                if result_state is None:
                    result_state = state_update.copy()
                else:
                    result_state.update(state_update)
        
        # Get final state if not collected
        if result_state is None:
            result_state = await graph.ainvoke(initial_state, config=config)
        
        return result_state
    
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


