from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import sys
import importlib.util

# Ensure project root is on sys.path for `shail` package imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Manually load shail module (works around macOS case-insensitivity issues)
# This is needed because Python's import system has issues with case-insensitive filesystems
shail_path = os.path.join(PROJECT_ROOT, "shail", "__init__.py")
if os.path.exists(shail_path):
    try:
        spec = importlib.util.spec_from_file_location("shail", shail_path)
        if spec and spec.loader:
            shail_module = importlib.util.module_from_spec(spec)
            sys.modules["shail"] = shail_module
            spec.loader.exec_module(shail_module)
    except Exception:
        # If manual loading fails, fall back to normal import
        pass

from shail.core.router import ShailCoreRouter
from shail.core.types import TaskRequest, TaskResult, TaskStatus
from shail.safety.permission_manager import PermissionManager
from shail.safety.exceptions import PermissionDenied
from shail.utils.queue import TaskQueue
from shail.memory.store import create_task, get_task, update_task_status, get_all_tasks
import uuid


class HealthResponse(BaseModel):
    status: str = Field(default="ok")
    service: str = Field(default="shail")


class ApprovalResponse(BaseModel):
    status: str
    message: str
    task_id: str


class TaskQueuedResponse(BaseModel):
    task_id: str
    status: str
    message: str


app = FastAPI(title="Shail Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = ShailCoreRouter()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/tasks", response_model=TaskQueuedResponse, status_code=202)
def submit_task(req: TaskRequest) -> TaskQueuedResponse:
    """
    Submit a new task for asynchronous execution.
    
    Tasks are queued and processed by a background worker.
    Returns immediately with task_id for status tracking.
    
    Use GET /tasks/{task_id} to check status.
    """
    try:
        # Generate task ID
        task_id = str(uuid.uuid4())[:8]
        
        # Store task in database
        create_task(task_id, req.dict())
        
        # Queue task for worker processing
        queue = TaskQueue()
        queue.enqueue(task_id, req.dict())
        
        return TaskQueuedResponse(
            task_id=task_id,
            status="queued",
            message=f"Task {task_id} queued for processing"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks/{task_id}", response_model=TaskResult)
def get_task_status(task_id: str) -> TaskResult:
    """
    Get the current status of a task from the task store.
    
    Returns full task status including results if completed.
    """
    try:
        # Get task from database
        task_data = get_task(task_id)
        if not task_data:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        # Convert database status to TaskStatus enum
        db_status = task_data["status"]
        if db_status == "pending":
            status = TaskStatus.PENDING
        elif db_status == "running":
            status = TaskStatus.RUNNING
        elif db_status == "awaiting_approval":
            status = TaskStatus.AWAITING_APPROVAL
        elif db_status == "completed":
            status = TaskStatus.COMPLETED
        elif db_status == "failed":
            status = TaskStatus.FAILED
        elif db_status == "denied":
            status = TaskStatus.DENIED
        else:
            status = TaskStatus.PENDING
        
        # If awaiting approval, include permission request
        permission_req = None
        if status == TaskStatus.AWAITING_APPROVAL:
            permission_req = PermissionManager.get_pending(task_id)
        
        # Build TaskResult from stored data
        result_data = task_data.get("result")
        if result_data:
            # Result was stored by worker - use it
            return TaskResult(
                status=status,
                summary=result_data.get("summary", f"Task {task_id} status: {db_status}"),
                agent=result_data.get("agent"),
                artifacts=result_data.get("artifacts"),
                audit_ref=result_data.get("audit_ref"),
                permission_request=permission_req,
                task_id=task_id
            )
        else:
            # No result yet - return current status
            summary = f"Task {task_id} is {db_status}"
            if status == TaskStatus.AWAITING_APPROVAL and permission_req:
                summary = f"Task {task_id} is awaiting approval for {permission_req.tool_name}"
            
            return TaskResult(
                status=status,
                summary=summary,
                permission_request=permission_req,
                task_id=task_id
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tasks/{task_id}/approve", response_model=ApprovalResponse)
def approve_task(task_id: str) -> ApprovalResponse:
    """
    Approve a pending permission request for a task.
    
    After approval, the task is automatically re-queued for worker processing.
    The worker will pick it up and execute it since permission is now approved.
    """
    try:
        success = PermissionManager.approve(task_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found or already resolved")
        
        # Re-queue the task for worker processing
        router.resume_task(task_id)
        
        return ApprovalResponse(
            status="approved",
            message=f"Task {task_id} approved and queued for execution.",
            task_id=task_id
        )
    except PermissionDenied as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tasks/{task_id}/deny", response_model=ApprovalResponse)
def deny_task(task_id: str) -> ApprovalResponse:
    """
    Deny a pending permission request for a task.
    """
    try:
        success = PermissionManager.deny(task_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        return ApprovalResponse(
            status="denied",
            message=f"Task {task_id} denied by user",
            task_id=task_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks/all")
def get_all_tasks_endpoint(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Get all tasks from the database.
    
    Args:
        limit: Maximum number of tasks to return (default: 100)
        offset: Number of tasks to skip for pagination (default: 0)
        
    Returns:
        List of task dictionaries with their current status
    """
    try:
        tasks = get_all_tasks(limit=limit, offset=offset)
        
        # Enrich tasks with permission requests if awaiting approval
        enriched_tasks = []
        for task in tasks:
            task_id = task["task_id"]
            if task["status"] == "awaiting_approval":
                permission_req = PermissionManager.get_pending(task_id)
                task["permission_request"] = permission_req.dict() if permission_req else None
            
            # Extract text from request for display
            request_text = task.get("request", {}).get("text", "")
            task["request_text"] = request_text
            
            enriched_tasks.append(task)
        
        return enriched_tasks
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))


