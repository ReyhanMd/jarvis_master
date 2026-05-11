import uuid
import time
from typing import Any
from shail.core.types import TaskRequest, TaskResult, TaskStatus
from shail.orchestration.master_planner import MasterPlanner
from shail.orchestration.graph import SimpleGraphExecutor, LangGraphExecutor
from shail.agents.code import CodeAgent
from shail.agents.bio import BioAgent
from shail.agents.robo import RoboAgent
from shail.agents.plasma import PlasmaAgent
from shail.agents.research import ResearchAgent
from shail.agents.friend import FriendAgent
from shail.memory.store import append_message
from shail.logging.audit import write_audit
from shail.safety.permission_manager import PermissionManager
from shail.safety.exceptions import PermissionDenied
from apps.shail.settings import get_settings
from shail.memory import rag
from shail.integrations.mcp.provider import get_provider
from shail.integrations.mcp.client import MCPClient


def _maybe_enqueue_ingest(result, req) -> None:
    """Phase 3: fire-and-forget auto-ingest. Never raises.

    Thread-safe across all caller contexts:
      • Running loop in this thread → schedule task on it
      • FastAPI threadpool (sync route) → run_coroutine_threadsafe on main loop
      • Pure sync (tests, CLI) → no loop available → drop silently

    Never uses asyncio.ensure_future() from cross-thread (NOT thread-safe).
    Never uses asyncio.run() (would crash under FastAPI).
    """
    try:
        from apps.shail.settings import get_settings
        if not get_settings().ingest_generated_outputs:
            return
        import asyncio
        from shail.memory.ingest_queue import get_ingest_queue
        q = get_ingest_queue()
        coro = q.enqueue(result, req)

        # Case 1: running loop in THIS thread
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
            return
        except RuntimeError:
            pass

        # Case 2: main loop on ANOTHER thread (FastAPI threadpool case)
        try:
            from shail.orchestration.graph import _get_main_loop
            main_loop = _get_main_loop()
            if main_loop is not None and main_loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, main_loop)
                return
        except Exception:
            pass

        # Case 3: no loop anywhere — drop. Test/CLI context.
        # We cannot await coro here without blocking the sync caller.
        # Close it cleanly to avoid "coroutine was never awaited" warnings.
        try:
            coro.close()
        except Exception:
            pass
    except Exception as exc:
        import logging
        logging.getLogger(__name__).debug("Phase3 ingest enqueue failed: %s", exc)


# Initialize agents once (singleton pattern)
AGENTS = {
    "code": CodeAgent(),
    "bio": BioAgent(),
    "robo": RoboAgent(),
    "plasma": PlasmaAgent(),
    "research": ResearchAgent(),
    "friend": FriendAgent(),
}


class ShailCoreRouter:
    """ShailCore - Master router that coordinates sub-agents and tracks execution."""
    
    def __init__(self):
        """Initialize the router with the Master Planner."""
        self.master_planner = MasterPlanner()
        self.mcp_provider = get_provider()
        self.mcp_client = MCPClient(provider=self.mcp_provider)
        self.rag_search = rag.search
        self._min_interval_sec = 0.05  # simple throttle (20 rps)
        self._last_task_time = 0.0
    
    def route(self, req: TaskRequest, task_id: str = None) -> TaskResult:
        """
        Main routing logic:
        1. Make routing decision
        2. Store user message in memory
        3. Execute agent workflow (handles permission requests)
        4. Log audit trail
        5. Store agent response
        
        Args:
            req: Task request
            task_id: Optional task ID (generates new one if not provided)
            
        Returns:
            TaskResult with status, summary, and optional permission_request
        """
        start_time = time.time()
        # Basic throttle to avoid overload
        if self._last_task_time:
            elapsed = start_time - self._last_task_time
            if elapsed < self._min_interval_sec:
                time.sleep(self._min_interval_sec - elapsed)
        self._last_task_time = time.time()
        
        if task_id is None:
            # Full UUID4 (36 chars) — 8-char truncation caused birthday collisions
            # at ~65K tasks, which polluted shared-context namespaces.
            task_id = str(uuid.uuid4())
        
        try:
            # Step 1: Routing decision — classifier first, master planner as fallback
            routing_start = time.time()
            from shail.core.task_classifier import classify
            from shail.core.types import RoutingDecision
            slot = classify(req.text or "")
            if slot == "code.agent":
                decision = RoutingDecision(agent="code", confidence=1.0, rationale="task_classifier")
            else:
                decision = self.master_planner.route_request(req)
            routing_time = time.time() - routing_start

            if routing_time < 0.01:  # Fast keyword routing
                print(f"[Router] Task {task_id}: Fast routing → {decision.agent} ({routing_time*1000:.1f}ms)")
            else:  # LLM routing
                print(f"[Router] Task {task_id}: LLM routing → {decision.agent} ({routing_time:.2f}s, confidence={decision.confidence:.2f})")
            
            # Step 2: Store user message
            try:
                append_message("user", req.text)
            except Exception as e:
                print(f"[Router] Warning: Failed to store user message: {e}")
            
            # Step 3: Execute agent (with task_id for permission tracking)
            execution_start = time.time()
            agent = AGENTS.get(decision.agent, AGENTS["code"])
            if agent is None:
                raise ValueError(f"Agent '{decision.agent}' not found in registry")
            # Expose MCP provider/client to agents that want tool discovery/calls
            setattr(agent, "mcp_provider", self.mcp_provider)
            setattr(agent, "mcp_client", self.mcp_client)
            
            # Auto-approve initial task execution (tools check this before requiring permission)
            # This allows simple tasks to execute immediately without permission modals
            PermissionManager.add_approved_context(task_id)
            
            try:
                executor = LangGraphExecutor(agent, task_id=task_id, persistent=True)
            except Exception:
                executor = SimpleGraphExecutor(agent, task_id=task_id)
            result = executor.run(req)
            execution_time = time.time() - execution_start
            
            # Clean up approved context after execution
            PermissionManager.remove_approved_context(task_id)
            
            print(f"[Router] Task {task_id}: Execution completed in {execution_time:.2f}s, status={result.status}")
            
            # Step 4: Audit log
            try:
                settings = get_settings()
                audit_ref = write_audit({
                    "task_id": task_id,
                    "request": req.text[:200],
                    "agent": decision.agent,
                    "confidence": decision.confidence,
                    "status": result.status.value if isinstance(result.status, TaskStatus) else result.status,
                    "artifacts_count": len(result.artifacts) if result.artifacts else 0,
                    "routing_time_ms": routing_time * 1000,
                    "execution_time_ms": execution_time * 1000
                }, audit_log_path=settings.audit_log_path)
            except Exception as e:
                print(f"[Router] Warning: Failed to write audit log: {e}")
                audit_ref = None
            
            # Step 5: Store agent response (only if completed, not if awaiting approval)
            if result.status != TaskStatus.AWAITING_APPROVAL:
                try:
                    append_message("assistant", result.summary)
                except Exception as e:
                    print(f"[Router] Warning: Failed to store assistant message: {e}")
            
            # Enhance result with routing metadata
            result.audit_ref = audit_ref
            result.agent = decision.agent
            result.task_id = task_id
            result.generated_by = decision.agent  # Phase 3: provenance

            # ── Phase 3: Fire-and-forget auto-ingest ──────────────────── #
            _maybe_enqueue_ingest(result, req)

            # Add routing metadata to summary (if not awaiting approval)
            if result.status != TaskStatus.AWAITING_APPROVAL:
                # Only add routing info if it's not already in the summary
                if "[Routing:" not in result.summary:
                    result.summary = f"{result.summary}\n\n[Routing: {decision.agent}, confidence={decision.confidence:.2f}]"
            
            total_time = time.time() - start_time
            if total_time > 5.0:
                print(f"[Router] Warning: Task {task_id} took {total_time:.2f}s total (slow)")
            
            return result
            
        except Exception as e:
            # Comprehensive error handling
            error_msg = str(e)[:200]  # Truncate long errors
            print(f"[Router] Error processing task {task_id}: {error_msg}")
            
            # Return failed result
            return TaskResult(
                status=TaskStatus.FAILED,
                summary=f"Routing error: {error_msg}",
                agent="unknown",
                artifacts=[],
                task_id=task_id
            )

    def list_mcp_tools(self) -> dict:
        """Expose MCP tool discovery to callers/agents."""
        try:
            return self.mcp_client.discover_available_tools()
        except Exception as exc:
            return {"error": str(exc)}

    def call_mcp_tool(self, tool_name: str, **kwargs) -> Any:
        """Call a locally registered MCP tool by name."""
        tool = self.mcp_provider.get_tool(tool_name)
        if not tool:
            raise ValueError(f"MCP tool '{tool_name}' not found")
        return tool(**kwargs)
    
    def resume_task(self, task_id: str) -> None:
        """
        Resume a task after permission has been approved.
        
        This method re-queues the task for worker processing.
        The worker will pick it up and execute it since permission is now approved.
        
        Args:
            task_id: Task ID to resume
            
        Raises:
            PermissionDenied: If permission was denied
            ValueError: If task not found or not awaiting approval
        """
        from shail.memory.store import get_task
        from shail.utils.queue import TaskQueue
        
        # Check permission status
        if PermissionManager.is_denied(task_id):
            raise PermissionDenied(task_id, "user denied")
        
        if not PermissionManager.is_approved(task_id):
            raise ValueError(f"Task {task_id} is not approved for execution")
        
        # Get the original task request from the database
        task_data = get_task(task_id)
        if not task_data:
            raise ValueError(f"Task {task_id} not found in database")
        
        # Re-queue the task for worker processing
        queue = TaskQueue()
        queue.enqueue(task_id, task_data["request"])


