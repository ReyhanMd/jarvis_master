from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import sys
import importlib.util
import logging

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
from shail.core.types import TaskRequest, TaskResult, TaskStatus, ChatRequest, ChatResponse
from shail.safety.permission_manager import PermissionManager
from shail.safety.exceptions import PermissionDenied
from shail.utils.queue import TaskQueue
from shail.memory.store import (
    create_task,
    get_task,
    update_task_status,
    get_all_tasks,
    append_message,
    get_chat_history,
)
from apps.shail.settings import get_settings
from shail.integrations.register_all import register_all_tools
from shail.integrations.mcp.provider import get_provider
from apps.shail.websocket_server import websocket_endpoint, websocket_manager
from apps.shail.native_health import register_native_health
import uuid


def ensure_log_dir():
    """Ensure .cursor directory exists for debug logs"""
    log_dir = os.path.join(os.path.expanduser("~"), "jarvis_master", ".cursor")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "debug.log")


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

register_native_health(app)

router = ShailCoreRouter()
logger = logging.getLogger(__name__)


@app.on_event("startup")
def bootstrap_mcp():
    """Register all tools with MCP on service startup."""
    try:
        register_all_tools(get_provider())
        logger.info("MCP registration completed on startup")
    except Exception as exc:
        logger.warning("MCP registration failed: %s", exc)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.websocket("/ws/brain")
async def websocket_brain(websocket: WebSocket):
    """
    WebSocket endpoint for real-time LangGraph state synchronization.
    
    Clients connect to receive state updates as the planner executes tasks.
    """
    try:
        # #region agent log
        import json
        import time
        try:
            log_path = ensure_log_dir()
            with open(log_path, 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"A","location":"main.py:websocket_brain","message":"WebSocket route called","data":{},"timestamp":time.time()})+'\n')
        except Exception:
            pass  # Don't fail WebSocket if logging fails
        # #endregion
        logger.info("WebSocket /ws/brain endpoint called")
        await websocket_endpoint(websocket)
    except Exception as e:
        # #region agent log
        import json
        import time
        try:
            log_path = ensure_log_dir()
            with open(log_path, 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"A","location":"main.py:websocket_brain","message":"WebSocket route error","data":{"error":str(e)},"timestamp":time.time()})+'\n')
        except Exception:
            pass  # Don't fail WebSocket if logging fails
        # #endregion
        logger.error(f"WebSocket route error: {e}", exc_info=True)
        raise


@app.post("/tasks", response_model=TaskQueuedResponse, status_code=202)
def submit_task(req: TaskRequest) -> TaskQueuedResponse:
    """
    Submit a new task for asynchronous execution.
    
    Tasks are queued and processed by a background worker.
    Returns immediately with task_id for status tracking.
    
    Use GET /tasks/{task_id} to check status.
    """
    # #region agent log
    import json
    import time
    import sys
    log_entry = {"sessionId":"debug-session","runId":"test-desktop-id","hypothesisId":"G","location":"main.py:submit_task","message":"Task submission received","data":{"text":req.text[:50],"desktop_id":req.desktop_id},"timestamp":time.time()}
    print(f"🔍 [DEBUG] Task submission received: desktop_id={req.desktop_id}", file=sys.stderr)
    try:
        log_path = ensure_log_dir()
        with open(log_path, 'a') as f:
            f.write(json.dumps(log_entry)+'\n')
            f.flush()
    except Exception as e:
        print(f"🔍 [DEBUG] Failed to write log: {e}", file=sys.stderr)
    # #endregion
    try:
        # Generate task ID
        task_id = str(uuid.uuid4())[:8]
        
        req_dict = req.dict()
        # #region agent log
        try:
            log_path = ensure_log_dir()
            with open(log_path, 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"test-desktop-id","hypothesisId":"G","location":"main.py:submit_task","message":"Request dict created","data":{"desktop_id_in_dict":req_dict.get("desktop_id")},"timestamp":time.time()})+'\n')
        except Exception:
            pass  # Don't fail task submission if logging fails
        # #endregion
        
        # Store task in database
        try:
            create_task(task_id, req_dict)
        except Exception as e:
            logger.error(f"Failed to create task in database: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to store task: {str(e)}"
            )
        
        # Queue task for worker processing
        try:
            queue = TaskQueue()
            queue.enqueue(task_id, req_dict)
        except (ConnectionError, ImportError, RuntimeError, Exception) as e:
            # Redis not available - log warning but don't fail
            # Task is still stored in database, worker can poll database instead
            error_msg = str(e)
            error_msg = str(e)
            logger.warning(f"Redis queue unavailable: {e}. Task {task_id} stored in database only.")
            # #region agent log
            try:
                import json
                import time
                log_path = ensure_log_dir()
                with open(log_path, 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"test-desktop-id","hypothesisId":"G","location":"main.py:submit_task","message":"Redis unavailable, task stored in DB only","data":{"task_id":task_id,"error":error_msg},"timestamp":time.time()})+'\n')
            except Exception:
                pass  # Don't fail if logging fails
            # #endregion
            # Still return success - task is in database, worker can poll
            # Don't fail the request if Redis is down
        
        return TaskQueuedResponse(
            task_id=task_id,
            status="queued",
            message=f"Task {task_id} queued for processing"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Task submission error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Task submission failed: {str(e)}"
        )


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


@app.get("/tasks/awaiting-approval")
def get_tasks_awaiting_approval() -> List[Dict[str, Any]]:
    """
    Return tasks that are awaiting approval.
    """
    try:
        tasks = get_all_tasks(limit=200, offset=0)
        awaiting = []
        for task in tasks:
            if task.get("status") == "awaiting_approval":
                awaiting.append(task)
        return awaiting
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


@app.get("/tasks/{task_id}/results")
def get_task_results(task_id: str) -> Dict[str, Any]:
    """
    Return detailed task results (raw stored payload).
    """
    try:
        task_data = get_task(task_id)
        if not task_data:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        result = task_data.get("result")
        if result is None and task_data.get("result_json"):
            result = task_data.get("result_json")
        return {
            "task_id": task_id,
            "status": task_data.get("status"),
            "result": result,
        }
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


@app.post("/permissions/bulk-approve")
async def bulk_approve_permissions(categories: List[str]):
    """
    Approve multiple permission categories at once.
    
    This allows users to approve common operations (desktop_control, window_management, etc.)
    at startup, reducing the need for individual permission requests during task execution.
    """
    try:
        from shail.safety.bulk_permissions import approve_category
        
        approved = []
        failed = []
        
        for category in categories:
            if approve_category(category):
                approved.append(category)
            else:
                failed.append(category)
        
        return {
            "approved": approved,
            "failed": failed,
            "message": f"Approved {len(approved)} categories"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/permissions/categories")
async def get_permission_categories():
    """
    Get list of permission categories available for bulk approval.
    
    Returns a dictionary mapping category names to their descriptions.
    """
    try:
        from shail.safety.bulk_permissions import get_permission_summary
        return get_permission_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/chat/history", response_model=List[Dict[str, Any]])
async def chat_history(limit: int = 200):
    """
    Return chat history from the local store.
    """
    try:
        return get_chat_history(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"History error: {str(e)}")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Direct chat endpoint - immediate LLM response without task queue.
    
    This endpoint provides synchronous, real-time conversation with the LLM.
    Perfect for quick questions and interactive chat.
    
    Supports:
    - Text-only messages
    - Image attachments (multimodal input)
    
    Returns response immediately (no async task queue).
    """
    try:
        settings = get_settings()
        
        if not settings.gemini_api_key:
            raise HTTPException(
                status_code=500, 
                detail="GEMINI_API_KEY not configured. Please set it in .env file or environment variables."
            )
        
        # Import LangChain Gemini client
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            from langchain_core.messages import HumanMessage
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="langchain_google_genai not installed. Install with: pip install langchain-google-genai"
            )
        
        # Initialize LLM client
        llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=0.7
        )
        
        # Build message content
        content = [{"type": "text", "text": request.text}]
        
        # Add images if provided (multimodal support)
        if request.attachments:
            for att in request.attachments:
                if att.mime_type and att.mime_type.startswith("image/"):
                    if att.content_b64:
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{att.mime_type};base64,{att.content_b64}"
                            }
                        })
        
        # Create message and invoke LLM with timeout
        import asyncio
        message = HumanMessage(content=content)
        try:
            response = await asyncio.wait_for(
                llm.ainvoke([message]),
                timeout=60.0  # 60 seconds for LLM response
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail="LLM response timeout. Please try again with a simpler query."
            )

        # Persist conversation
        try:
            append_message("user", request.text)
            append_message("assistant", response.content)
        except Exception:
            logger.warning("Failed to append chat history")
        
        return ChatResponse(
            text=response.content,
            model=settings.gemini_model
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))


