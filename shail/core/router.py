import uuid
from shail.core.types import TaskRequest, TaskResult, TaskStatus
from shail.orchestration.master_planner import MasterPlanner
from shail.orchestration.graph import SimpleGraphExecutor
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
        if task_id is None:
            task_id = str(uuid.uuid4())[:8]
        
        # Step 1: Routing decision using Master Planner LLM
        decision = self.master_planner.route_request(req)
        
        # Step 2: Store user message
        append_message("user", req.text)
        
        # Step 3: Execute agent (with task_id for permission tracking)
        agent = AGENTS.get(decision.agent, AGENTS["code"])
        executor = SimpleGraphExecutor(agent, task_id=task_id)
        result = executor.run(req)
        
        # Step 4: Audit log
        settings = get_settings()
        audit_ref = write_audit({
            "task_id": task_id,
            "request": req.text[:200],
            "agent": decision.agent,
            "confidence": decision.confidence,
            "status": result.status.value if isinstance(result.status, TaskStatus) else result.status,
            "artifacts_count": len(result.artifacts) if result.artifacts else 0
        }, audit_log_path=settings.audit_log_path)
        
        # Step 5: Store agent response (only if completed, not if awaiting approval)
        if result.status != TaskStatus.AWAITING_APPROVAL:
            append_message("assistant", result.summary)
        
        # Enhance result with routing metadata
        result.audit_ref = audit_ref
        result.agent = decision.agent
        result.task_id = task_id
        
        # Add routing metadata to summary (if not awaiting approval)
        if result.status != TaskStatus.AWAITING_APPROVAL:
            result.summary = f"{result.summary}\n\n[Routing: {decision.agent}, confidence={decision.confidence:.2f}]"
        
        return result
    
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


