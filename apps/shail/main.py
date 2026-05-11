from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, AsyncIterator
import asyncio
import httpx
import json
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
from apps.shail.browser_api import browser_router
from apps.shail.ascents_api import ascents_router
from apps.shail.chat_api import chat_router
from apps.shail.mcp_api import mcp_router
from apps.shail.auth_api import auth_router, get_user_or_local
from apps.shail.auth_store import init_auth_db
from apps.shail.memory_dashboard_api import dashboard_router
from apps.shail.macos_memory_api import memory_router, path_idx_router
from apps.shail.llm import call_llm
from shail.core.task_classifier import classify
import uuid


def ensure_log_dir():
    """Ensure .cursor directory exists for debug logs"""
    log_dir = os.path.join(os.path.expanduser("~"), "jarvis_master", ".cursor")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "debug.log")


class HealthResponse(BaseModel):
    status: str = Field(default="ok")
    service: str = Field(default="shail")
    version: str = Field(default="0.1.0")
    chroma_ready: bool = Field(default=False)
    embedder_ready: bool = Field(default=False)
    ollama_reachable: bool = Field(default=False)
    google_oauth_configured: bool = Field(default=False)
    apple_signin_configured: bool = Field(default=False)
    errors: List[str] = Field(default_factory=list)


class ApprovalResponse(BaseModel):
    status: str
    message: str
    task_id: str


class TaskQueuedResponse(BaseModel):
    task_id: str
    status: str
    message: str


app = FastAPI(title="Shail Service", version="0.1.0")

# CORS: pinned to known origins. allow_origins=["*"] paired with
# allow_credentials=True is a CORS spec violation that some browsers reject.
# Extension origins use chrome-extension:// scheme; allow_origin_regex covers
# every install ID without enumerating them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    # Chrome extension IDs are 32 lowercase a-p chars (base-26); also allow
    # any alphanumeric variant to future-proof Safari/Firefox extensions.
    allow_origin_regex=r"^chrome-extension://[a-z0-9]+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_native_health(app)
app.include_router(auth_router, prefix="/auth", tags=["auth"])

# Google OAuth2 — mount BEFORE the generic /auth router to avoid prefix conflicts
from apps.shail.google_auth_api import google_auth_router  # noqa: E402
app.include_router(google_auth_router, prefix="/auth/google", tags=["google-auth"])

app.include_router(browser_router, prefix="/browser", tags=["browser"])
app.include_router(ascents_router, prefix="/browser/ascents", tags=["ascents"])
app.include_router(chat_router, prefix="/browser/chat", tags=["chat"])
app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])
app.include_router(dashboard_router, prefix="/api/v2", tags=["dashboard"])
app.include_router(memory_router, prefix="/memory", tags=["memory"])
app.include_router(path_idx_router, prefix="/path-index", tags=["path-index"])

from apps.shail.system_api import system_router  # noqa: E402
app.include_router(system_router, prefix="/system", tags=["system"])

# ── Serve shail-ui SPA at /dashboard (web fallback when ShailUI.app not running)
_UI_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../apps/shail-ui/dist"))
if os.path.isdir(_UI_DIST):
    from pathlib import Path as _Path
    _UI_ASSETS = os.path.join(_UI_DIST, "assets")
    if os.path.isdir(_UI_ASSETS):
        app.mount("/dashboard/assets", StaticFiles(directory=_UI_ASSETS), name="shail-ui-assets")

    @app.get("/dashboard", include_in_schema=False)
    @app.get("/dashboard/{full_path:path}", include_in_schema=False)
    async def serve_dashboard_spa(full_path: str = ""):
        candidate = _Path(_UI_DIST) / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_Path(_UI_DIST) / "index.html")

router = ShailCoreRouter()
logger = logging.getLogger(__name__)


@app.on_event("startup")
def bootstrap_mcp():
    """Register all tools with MCP on service startup."""
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.sqlite_path), exist_ok=True)
    try:
        init_auth_db()
        logger.info("Auth DB initialized")
    except Exception as exc:
        logger.warning("Auth DB init failed: %s", exc)
    try:
        from apps.shail.blueprints import init_blueprint_db
        init_blueprint_db()
        logger.info("Blueprint DB initialized")
    except Exception as exc:
        logger.warning("Blueprint DB init failed: %s", exc)
    try:
        from apps.shail.capture_store import init_capture_store
        init_capture_store()
        logger.info("Capture store initialized")
    except Exception as exc:
        logger.warning("Capture store init failed: %s", exc)
    try:
        register_all_tools(get_provider())
        logger.info("MCP registration completed on startup")
    except Exception as exc:
        logger.warning("MCP registration failed: %s", exc)
    # Phase 6: init metrics
    try:
        from shail.observability.metrics import init_metrics
        init_metrics()
    except Exception as exc:
        logger.warning("Metrics init failed: %s", exc)
    # Phase 3: start ingest queue drain worker
    try:
        from shail.memory.ingest_queue import get_ingest_queue
        get_ingest_queue().start()
    except Exception as exc:
        logger.warning("IngestQueue start failed: %s", exc)


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    """Prometheus metrics endpoint (Phase 6)."""
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        from fastapi.responses import Response
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("# prometheus_client not installed\n", status_code=200)
    except Exception as exc:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(f"# metrics error: {exc}\n", status_code=500)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    errors: List[str] = []
    chroma_ready = False
    embedder_ready = False
    ollama_reachable = False

    try:
        from shail.memory.rag import _get_store
        store = _get_store()
        if hasattr(store, "collection"):
            _ = store.collection.count()
        chroma_ready = True
    except Exception as exc:
        errors.append(f"chroma: {exc}")

    try:
        from shail.memory.embeddings import embed_query
        vec = embed_query("ping")
        embedder_ready = bool(vec)
    except Exception as exc:
        errors.append(f"embedder: {exc}")

    try:
        import httpx
        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{host}/api/tags")
            ollama_reachable = r.status_code == 200
    except Exception as exc:
        errors.append(f"ollama: {exc}")

    google_oauth_configured = bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))
    apple_signin_configured = bool(os.getenv("APPLE_AUDIENCE"))

    overall_ok = chroma_ready and embedder_ready
    return HealthResponse(
        status="ok" if overall_ok else "degraded",
        chroma_ready=chroma_ready,
        embedder_ready=embedder_ready,
        ollama_reachable=ollama_reachable,
        google_oauth_configured=google_oauth_configured,
        apple_signin_configured=apple_signin_configured,
        errors=errors,
    )


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



async def rag_retrieve(query: str, user_id: str = "local") -> str:
    """Retrieve context from all memory tiers for a query, scoped to a user.

    Sprint 1 fix: previously queried `shail_important` and `shail_ephemeral`
    as separate Chroma collections — but every writer (browser_api,
    macos_memory_api, _ingest_unified) writes to the single base collection
    via _get_store() with `tier` as a metadata field. The old code therefore
    queried empty collections and Gemma never saw any captured memory.
    """
    try:
        from shail.memory.rag import _get_store
        from shail.memory.path_index import search as path_search
        from shail.memory.embeddings import embed_query as emb_q
        s = get_settings()

        q_embed = emb_q(query)
        results: list = []

        store = _get_store()
        namespace = f"user_{user_id}" if user_id and user_id != "local" else "local"

        for tier in ("important", "ephemeral"):
            try:
                hits = store.query(
                    query_embedding=q_embed,
                    namespace=namespace,
                    filters={"tier": tier},
                    k=4,
                )
                results.extend(hits)
            except Exception as exc:
                logger.warning("rag_retrieve tier=%s failed: %s", tier, exc)

        path_hits = path_search(s.path_index_db, query, limit=3)
        for h in path_hits:
            snippet = f"{h.get('title', '')} — {h['path']}"
            results.append({"content": snippet, "score": 0.6})

        # Sort by score ascending (lower = more similar in cosine distance)
        results.sort(key=lambda x: x.get("score", 1.0))
        return "\n\n---\n".join(r["content"][:400] for r in results[:6])
    except Exception as e:
        logger.warning("rag_retrieve failed: %s", e)
        return ""


# ── /query endpoint (replaces /chat) ─────────────────────────────────────────

class QueryRequest(BaseModel):
    text: str
    history: List[Dict[str, str]] = Field(default_factory=list)


class WebSource(BaseModel):
    title: str
    url: str
    snippet: str = ""


class QueryResponse(BaseModel):
    answer: str
    text: str = ""       # backward-compat: old ChatService decodes .text
    tier_used: str
    model: str = "gemma3:4b-it-q4_K_M"
    sources: List[WebSource] = Field(default_factory=list)
    used_web: bool = False


@app.post("/query", response_model=QueryResponse)
async def unified_query(
    req: QueryRequest,
    user_id: str = Depends(get_user_or_local),
) -> QueryResponse:
    """
    Unified query: classify intent, run RAG + (optionally) web search in parallel,
    inject combined context into Gemma. Web search hard-capped at 3 s.
    """
    from apps.shail.web_search import needs_web_search, search as web_search, format_for_prompt

    slot = classify(req.text)

    # Run RAG and web search concurrently — overlap latency
    needs_rag = slot in ("memory.search", "nav.assist", "gemma.chat")
    needs_web = needs_web_search(req.text)

    rag_task = rag_retrieve(req.text, user_id=user_id) if needs_rag else None
    web_task = web_search(req.text, max_results=3, timeout=3.0) if needs_web else None

    rag_context = ""
    web_results: list = []

    if rag_task and web_task:
        rag_context, web_results = await asyncio.gather(rag_task, web_task)
    elif rag_task:
        rag_context = await rag_task
    elif web_task:
        web_results = await web_task

    # Build combined context
    parts = []
    if rag_context:
        parts.append(rag_context)
    if web_results:
        parts.append(format_for_prompt(web_results))
    context = "\n\n---\n\n".join(parts)

    messages = req.history + [{"role": "user", "content": req.text}]
    answer, meta = await call_llm(
        messages=messages,
        user_id=user_id,
        context=context,
        system_prompt="You are SHAIL, a personal AI assistant running locally.",
    )

    try:
        append_message("user", req.text)
        append_message("assistant", answer)
    except Exception:
        pass

    sources = [WebSource(**r) for r in web_results] if web_results else []

    return QueryResponse(
        answer=answer,
        text=answer,
        tier_used=slot,
        model=meta.get("model", get_settings().ollama_chat_model),
        sources=sources,
        used_web=bool(web_results),
    )


@app.post("/chat", response_model=QueryResponse)
async def chat_compat(
    req: QueryRequest,
    user_id: str = Depends(get_user_or_local),
) -> QueryResponse:
    """/chat kept for backward-compat — delegates to /query."""
    return await unified_query(req, user_id=user_id)


@app.post("/query/stream")
async def stream_query(req: QueryRequest) -> StreamingResponse:
    """
    Streaming SSE version of /query — token streaming + parallel web search.

    Events:
      data: {"token": "..."}                              — partial token
      data: {"sources": [...]}                            — emitted ASAP after web fetch
      data: {"done": true, "answer": "...", "sources":[]} — final
      data: {"error": "..."}                              — backend error
    """
    from apps.shail.web_search import needs_web_search, search as web_search, format_for_prompt

    s = get_settings()
    slot = classify(req.text)
    needs_rag = slot in ("memory.search", "nav.assist", "gemma.chat")
    needs_web = needs_web_search(req.text)

    # Run RAG + web search concurrently BEFORE streaming starts
    rag_task = rag_retrieve(req.text) if needs_rag else None
    web_task = web_search(req.text, max_results=3, timeout=3.0) if needs_web else None

    rag_context = ""
    web_results: list = []
    if rag_task and web_task:
        rag_context, web_results = await asyncio.gather(rag_task, web_task)
    elif rag_task:
        rag_context = await rag_task
    elif web_task:
        web_results = await web_task

    parts = []
    if rag_context:
        parts.append(rag_context)
    if web_results:
        parts.append(format_for_prompt(web_results))
    context = "\n\n---\n\n".join(parts)

    system_content = "You are SHAIL, a personal AI assistant running locally."
    if context:
        system_content += f"\n\nRelevant context:\n{context}"

    messages = req.history + [{"role": "user", "content": req.text}]
    payload = {
        "model": s.ollama_chat_model,
        "messages": [{"role": "system", "content": system_content}] + messages,
        "stream": True,
    }

    async def event_stream() -> AsyncIterator[str]:
        full_answer = ""
        # Emit sources upfront so UI can render link icons early
        if web_results:
            yield f"data: {json.dumps({'sources': web_results})}\n\n"
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                async with client.stream(
                    "POST", f"{s.ollama_base_url}/api/chat", json=payload
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            full_answer += token
                            yield f"data: {json.dumps({'token': token})}\n\n"
                        if chunk.get("done"):
                            yield f"data: {json.dumps({'done': True, 'answer': full_answer, 'sources': web_results})}\n\n"
                            break
        except httpx.ConnectError:
            yield f"data: {json.dumps({'error': 'ollama_offline', 'message': 'Ollama is not running'})}\n\n"
        except Exception as exc:
            logger.error("stream_query error: %s", exc)
            yield f"data: {json.dumps({'error': 'backend_error', 'message': str(exc)})}\n\n"

        try:
            append_message("user", req.text)
            append_message("assistant", full_answer)
        except Exception:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Startup indexing ──────────────────────────────────────────────────────────

@app.on_event("startup")
async def _startup_index():
    async def _run():
        await asyncio.sleep(6)
        try:
            from shail.memory.path_index import scan
            count = scan(get_settings().path_index_db)
            logger.info("Startup path index complete: %d files", count)
        except Exception as e:
            logger.warning("Startup index failed: %s", e)
    asyncio.create_task(_run())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

