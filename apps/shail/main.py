from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
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
if os.path.exists(shail_path) and "shail" not in sys.modules:
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
from apps.shail.auth_api import auth_router, get_current_user, get_user_or_local
from apps.shail.auth_store import init_auth_db
from apps.shail.memory_dashboard_api import dashboard_router
from apps.shail.macos_memory_api import memory_router, path_idx_router
from apps.shail.llm import call_llm
from shail.core.task_classifier import classify
import uuid


def ensure_log_dir():
    log_dir = os.path.join(PROJECT_ROOT, ".cursor")
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.sqlite_path), exist_ok=True)
    try:
        init_auth_db()
        logger.info("Auth DB initialized")
        try:
            from apps.shail.crypto import run_migrations
            run_migrations()
            logger.info("Database GCM migrations complete")
        except Exception as migration_exc:
            logger.warning("Database GCM migrations failed: %s", migration_exc)
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
        from apps.shail.session_backfill import ensure_phase_c_schema
        ensure_phase_c_schema()
        logger.info("Phase C session schema applied")
    except Exception as exc:
        logger.warning("Phase C schema apply failed: %s", exc)
    try:
        from apps.shail.raw_transcripts import init_raw_transcripts_schema
        init_raw_transcripts_schema()
        logger.info("Raw transcripts schema applied (segments columns)")
    except Exception as exc:
        logger.warning("Raw transcripts schema apply failed: %s", exc)
    try:
        from apps.shail.pipeline_status import init_pipeline_status_schema
        init_pipeline_status_schema()
        logger.info("Pipeline status schema applied")
    except Exception as exc:
        logger.warning("Pipeline status schema apply failed: %s", exc)
    try:
        register_all_tools(get_provider())
        logger.info("MCP registration completed on startup")
    except Exception as exc:
        logger.warning("MCP registration failed: %s", exc)
    # Runtime stabilization: register main event loop for thread-safe scheduling
    try:
        from shail.orchestration.graph import register_main_loop
        register_main_loop(asyncio.get_event_loop())
    except Exception as exc:
        logger.warning("Main loop registration failed: %s", exc)
    # Phase 6: init metrics + Sprint 2 telemetry→Prometheus bridge
    try:
        from shail.observability.metrics import init_metrics
        init_metrics()
        from shail.observability.bridge import install_bridge
        install_bridge()
    except Exception as exc:
        logger.warning("Metrics init failed: %s", exc)
    # Phase 3: start ingest queue drain worker
    try:
        from shail.memory.ingest_queue import get_ingest_queue
        get_ingest_queue().start()
    except Exception as exc:
        logger.warning("IngestQueue start failed: %s", exc)

    # Launch background async startup tasks
    asyncio.create_task(_startup_index_run())
    asyncio.create_task(_start_blueprint_queue_worker_run())
    asyncio.create_task(_restart_filesystem_watchers_run())

    yield

    # --- SHUTDOWN ---
    try:
        from shail.memory.ingest_queue import get_ingest_queue
        await get_ingest_queue().stop()
    except Exception as exc:
        logger.warning("IngestQueue stop failed: %s", exc)
    try:
        from shail.memory.supermemory_client import close_supermemory_client
        await close_supermemory_client()
    except Exception as exc:
        logger.warning("SupermemoryClient close failed: %s", exc)
    try:
        from shail.integrations.local.filesystem.adapter import get_adapter
        get_adapter().stop_all()
    except Exception:
        pass


async def _startup_index_run():
    await asyncio.sleep(6)
    loop = asyncio.get_event_loop()
    try:
        from pathlib import Path
        from shail.memory.path_index import (
            scan, ingest_spotlight_recent, _default_roots, backfill_snippets,
            get_persisted_roots,
        )
        from shail.integrations.local.filesystem.adapter import get_adapter
        from apps.shail.auth_store import _conn as _auth_conn

        settings = get_settings()
        default_roots = _default_roots()
        env_roots = [r for r in settings.scan_roots if r and Path(r).is_dir()]
        persisted_roots = []
        try:
            persisted_roots = get_persisted_roots(settings.path_index_db)
        except Exception:
            pass
        # Merge all sources, deduplicate, preserve order.
        seen: set = set()
        roots: list = []
        for r in env_roots + persisted_roots + default_roots:
            if r not in seen:
                seen.add(r)
                roots.append(r)
        logger.info(
            "Scan roots: %d env, %d persisted, %d default → %d total: %s",
            len(env_roots), len(persisted_roots), len(default_roots), len(roots), roots,
        )

        # 1. Bulk scan in thread
        file_count = await loop.run_in_executor(
            None, lambda: scan(settings.path_index_db, roots=roots or None)
        )
        logger.info("Startup path index walk complete: %d new/changed files", file_count)

        # 1b. Backfill summary_snippet
        try:
            sn = await loop.run_in_executor(
                None, lambda: backfill_snippets(settings.path_index_db, max_files=2000)
            )
            if sn:
                logger.info("Backfilled summary_snippet for %d existing rows", sn)
        except Exception as exc:
            logger.debug("snippet backfill skipped: %s", exc)

        # 2. Spotlight (macOS)
        try:
            sl = await loop.run_in_executor(
                None, lambda: ingest_spotlight_recent(settings.path_index_db, days=30, max_files=1000)
            )
            if sl:
                logger.info("Spotlight added %d recently-modified files", sl)
        except Exception as exc:
            logger.debug("Spotlight ingest skipped: %s", exc)

        # 3. Auto-attach watchdog observers
        try:
            with _auth_conn() as con:
                row = con.execute("SELECT id FROM users ORDER BY created_at LIMIT 1").fetchone()
            resident_user = row["id"] if row else None
        except Exception:
            resident_user = None
        if resident_user:
            adapter = get_adapter()
            attached = 0
            for r in roots:
                res = await loop.run_in_executor(None, lambda root=r: adapter.start_watch(resident_user, root))
                if res.get("ok"):
                    attached += 1
            logger.info("Auto-attached %d watchdog observers for user=%s", attached, resident_user)
        else:
            logger.info("No registered user — skipping auto-watch attach")
    except Exception as e:
        logger.warning("Startup index failed: %s", e)


async def _start_blueprint_queue_worker_run():
    await asyncio.sleep(4)
    try:
        from apps.shail.blueprint_queue import start_worker
        start_worker()
    except Exception as e:
        logger.warning("blueprint queue worker failed to start: %s", e)


async def _restart_filesystem_watchers_run():
    await asyncio.sleep(3)
    try:
        from shail.integrations.local.filesystem.adapter import get_adapter
        count = get_adapter().restart_persisted_watches()
        if count:
            logger.info("Restarted %d filesystem watcher(s) from persisted state", count)
    except Exception as e:
        logger.warning("Filesystem watcher restart failed: %s", e)


app = FastAPI(title="Shail Service", version="0.1.0", lifespan=lifespan)

from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from apps.shail.limiter import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
        base_dir = _Path(_UI_DIST).resolve()
        try:
            candidate = (base_dir / full_path).resolve()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid path")

        if not candidate.is_relative_to(base_dir):
            raise HTTPException(status_code=403, detail="Access denied")

        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(base_dir / "index.html")

router = ShailCoreRouter()
logger = logging.getLogger(__name__)





@app.get("/metrics", include_in_schema=False)
def prometheus_metrics(request: Request):
    """Prometheus metrics endpoint (Phase 6)."""
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Access denied")
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
async def health() -> HealthResponse:
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
        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        async with httpx.AsyncClient(timeout=0.5) as c:
            r = await c.get(f"{host}/api/tags")
            ollama_reachable = r.status_code == 200
            # If Ollama is up, treat embedder as ready without a live ping
            # (embed_query("ping") on every /health call blocks for ~1s).
            embedder_ready = ollama_reachable
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
        logger.info("WebSocket /ws/brain endpoint called")
        await websocket_endpoint(websocket)
    except Exception as e:
        logger.error(f"WebSocket route error: {e}", exc_info=True)
        raise


@app.post("/tasks", response_model=TaskQueuedResponse, status_code=202)
def submit_task(
    req: TaskRequest,
    user_id: str = Depends(get_current_user),
) -> TaskQueuedResponse:
    """
    Submit a new task for asynchronous execution.
    
    Tasks are queued and processed by a background worker.
    Returns immediately with task_id for status tracking.
    
    Use GET /tasks/{task_id} to check status.
    """
    try:
        # Generate task ID — full UUID4 to avoid birthday collisions on
        # shared-context namespaces (Phase 5).
        task_id = str(uuid.uuid4())
        
        req_dict = req.dict()
        
        # Store task in database
        try:
            create_task(task_id, req_dict)
        except Exception as e:
            logger.error(f"Failed to create task in database: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to store task."
            )
        
        # Queue task for worker processing
        try:
            queue = TaskQueue()
            queue.enqueue(task_id, req_dict)
        except (ConnectionError, ImportError, RuntimeError, Exception) as e:
            # Redis not available - log warning but don't fail
            # Task is still stored in database, worker can poll database instead
            logger.warning(f"Redis queue unavailable: {e}. Task {task_id} stored in database only.")
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
            detail="Task submission failed."
        )


@app.get("/tasks/all")
def get_all_tasks_endpoint(
    limit: int = 100,
    offset: int = 0,
    user_id: str = Depends(get_current_user),
) -> List[Dict[str, Any]]:
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
        logger.error(f"Failed to retrieve tasks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve tasks")


@app.get("/tasks/awaiting-approval")
def get_tasks_awaiting_approval(
    user_id: str = Depends(get_current_user),
) -> List[Dict[str, Any]]:
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
        logger.error(f"Failed to retrieve tasks awaiting approval: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve tasks awaiting approval")

@app.get("/tasks/{task_id}", response_model=TaskResult)
def get_task_status(
    task_id: str,
    user_id: str = Depends(get_current_user),
) -> TaskResult:
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
        logger.error(f"Failed to retrieve task status for {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve task status")


@app.get("/tasks/{task_id}/results")
def get_task_results(
    task_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
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
        logger.error(f"Failed to retrieve task results for {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve task results")

@app.post("/tasks/{task_id}/approve", response_model=ApprovalResponse)
def approve_task(
    task_id: str,
    user_id: str = Depends(get_current_user),
) -> ApprovalResponse:
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
        logger.error(f"Failed to approve task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to approve task")


@app.post("/tasks/{task_id}/deny", response_model=ApprovalResponse)
def deny_task(
    task_id: str,
    user_id: str = Depends(get_current_user),
) -> ApprovalResponse:
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
        logger.error(f"Failed to deny task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to deny task")


@app.post("/permissions/bulk-approve")
async def bulk_approve_permissions(
    categories: List[str],
    user_id: str = Depends(get_current_user),
):
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
        logger.error(f"Failed bulk permission approval: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed bulk permission approval")


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
        logger.error(f"Failed to retrieve permission categories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve permission categories")


@app.get("/chat/history", response_model=List[Dict[str, Any]])
async def chat_history(
    limit: int = 200,
    user_id: str = Depends(get_current_user),
):
    """
    Return chat history from the local store.
    """
    try:
        return get_chat_history(limit=limit)
    except Exception as e:
        logger.error(f"History retrieval error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve history")



async def rag_retrieve(query: str, user_id: str) -> str:
    """Retrieve context from all memory tiers for a query, scoped to a user.

    Always uses the canonical user namespace — no "local" fallback.
    """
    try:
        from shail.memory.rag import _get_store
        from shail.memory.path_index import search as path_search
        from shail.memory.embeddings import embed_query as emb_q
        s = get_settings()

        q_embed = emb_q(query)
        results: list = []

        store = _get_store()
        # Always scoped to the authenticated user — no anonymous namespace
        namespace = f"user_{user_id}"

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


class LocalFileSource(BaseModel):
    """Local-file citation surfaced to the desktop client.

    Same shape as chat_api.LocalFileCitation but minted here so the macOS
    desktop can render Finder-reveal buttons without importing the chat
    module's pydantic class.
    """
    id: str
    title: str
    path: str
    snippet: str = ""
    file_type: str = ""
    score: float = 0.0


class QueryResponse(BaseModel):
    answer: str
    text: str = ""       # backward-compat: old ChatService decodes .text
    tier_used: str
    model: str = "gemma3:4b-it-q4_K_M"
    sources: List[WebSource] = Field(default_factory=list)
    local_files: List[LocalFileSource] = Field(default_factory=list)
    used_web: bool = False


@app.post("/query", response_model=QueryResponse)
async def unified_query(
    req: QueryRequest,
    user_id: str = Depends(get_current_user),
) -> QueryResponse:
    """
    Unified query: routes through the SAME pipeline as /browser/chat so the
    macOS desktop (which still POSTs here) gets identical retrieval, context
    packet, MCP integration, formatting prompt, and citation contract as the
    web dashboard. Previously this used a simpler `rag_retrieve()` + a bare
    system prompt — so the desktop produced visibly different (worse) answers
    than the dashboard for the same query.
    """
    from apps.shail.chat_api import _build_context, _system_prompt as _chat_system_prompt
    from apps.shail.web_search import format_for_prompt

    slot = classify(req.text)

    # Full retrieval: memories (hybrid) + past chats + MCP live + MCP RAG + web
    # + local files (pointer-only, content read at answer time).
    context, _citations, _past, web_sources, _mcp, local_files = await _build_context(
        user_id, req.text, is_first_in_session=not bool(req.history),
        task_id=None,
    )

    messages = req.history + [{"role": "user", "content": req.text}]
    answer, meta = await call_llm(
        messages=messages,
        user_id=user_id,
        context=context,
        system_prompt=_chat_system_prompt(),
    )

    try:
        append_message("user", req.text)
        append_message("assistant", answer)
    except Exception:
        pass

    # Legacy WebSource shape for backward-compat with the Swift desktop client.
    sources = [WebSource(title=w.title, url=w.url, snippet=w.snippet) for w in web_sources] if web_sources else []
    local_file_sources = [
        LocalFileSource(
            id=f.id, title=f.title, path=f.path, snippet=f.snippet,
            file_type=f.file_type, score=f.score,
        )
        for f in (local_files or [])
    ]

    return QueryResponse(
        answer=answer,
        text=answer,
        tier_used=slot,
        model=meta.get("model", get_settings().ollama_chat_model),
        sources=sources,
        local_files=local_file_sources,
        used_web=bool(web_sources),
    )


@app.post("/chat", response_model=QueryResponse)
async def chat_compat(
    req: QueryRequest,
    user_id: str = Depends(get_current_user),
) -> QueryResponse:
    """/chat kept for backward-compat — delegates to /query."""
    return await unified_query(req, user_id=user_id)


@app.post("/query/stream")
async def stream_query(
    req: QueryRequest,
    user_id: str = Depends(get_current_user),
) -> StreamingResponse:
    """
    Streaming SSE version of /query — token streaming + parallel web search.

    Events:
      data: {"token": "..."}                              — partial token
      data: {"sources": [...]}                            — emitted ASAP after web fetch
      data: {"done": true, "answer": "...", "sources":[]} — final
      data: {"error": "..."}                              — backend error
    """
    # Route through the full chat_api pipeline so desktop streaming gets the
    # same retrieval (hybrid + past chats + MCP) and the same formatting prompt.
    from apps.shail.chat_api import _build_context, _system_prompt as _chat_system_prompt

    s = get_settings()
    slot = classify(req.text)

    context, _citations, _past, web_sources, _mcp, local_files = await _build_context(
        user_id, req.text, is_first_in_session=not bool(req.history),
        task_id=None,
    )
    web_results = [{"title": w.title, "url": w.url, "snippet": w.snippet} for w in (web_sources or [])]
    local_file_payload = [
        {"id": f.id, "title": f.title, "path": f.path, "snippet": f.snippet,
         "file_type": f.file_type, "score": f.score}
        for f in (local_files or [])
    ]

    sys_base = _chat_system_prompt()
    system_content = sys_base + (f"\n\nRelevant context:\n{context}" if context else "")

    messages = req.history + [{"role": "user", "content": req.text}]
    payload = {
        "model": s.ollama_chat_model,
        "messages": [{"role": "system", "content": system_content}] + messages,
        "stream": True,
        "options": {"num_ctx": s.ollama_num_ctx, "num_thread": s.ollama_num_thread, "num_gpu": 99},
    }

    async def event_stream() -> AsyncIterator[str]:
        full_answer = ""
        # Emit sources upfront so UI can render link icons early
        if web_results:
            yield f"data: {json.dumps({'sources': web_results})}\n\n"
        if local_file_payload:
            yield f"data: {json.dumps({'local_files': local_file_payload})}\n\n"
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
                            yield f"data: {json.dumps({'done': True, 'answer': full_answer, 'sources': web_results, 'local_files': local_file_payload})}\n\n"
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



# ── Lifespan Tasks completed ──────────────────────────────────────────────────



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
