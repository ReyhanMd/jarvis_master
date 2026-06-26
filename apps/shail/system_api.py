"""
SHAIL System Management API
────────────────────────────
Endpoints for starting, stopping, and monitoring SHAIL services.

Mounted at /system in main.py.

GET  /system/status           → current state of each service (no auth)
POST /system/start            → start all services, SSE stream of progress (auth required)
POST /system/stop             → stop managed services cleanly (auth required)
POST /system/restart/{service}→ stop + start a single service (auth required)
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import AsyncIterator, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from apps.shail.auth_store import get_user_by_api_key, get_user_tier

logger = logging.getLogger(__name__)

system_router = APIRouter()
_bearer = HTTPBearer(auto_error=False)

# ── Managed subprocesses spawned by this process ─────────────────────────────
_managed_procs: Dict[str, subprocess.Popen] = {}
_managed_proc_owners: Dict[str, str] = {}
_blueprint_ollama_idle_since: Optional[float] = None
BLUEPRINT_OLLAMA_IDLE_SECONDS = 10

# ── Service definitions ───────────────────────────────────────────────────────

FREE_SERVICES = ["ollama", "chroma"]          # backend is always running
PRO_SERVICES  = ["redis", "worker"]           # pro-only additions

PORTS = {
    "backend": 8000,
    "ollama":  11434,
    "redis":   6379,
}

OLLAMA_HEALTH = "http://localhost:11434/api/tags"
BACKEND_HEALTH = "http://localhost:8000/health"


# ── Auth helper ───────────────────────────────────────────────────────────────

def _require_auth(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id = get_user_by_api_key(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user_id


# ── Live detection helpers ────────────────────────────────────────────────────

def _port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _proc_alive(name: str) -> bool:
    proc = _managed_procs.get(name)
    if proc is None:
        return False
    return proc.poll() is None


async def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
            return r.status_code == 200
    except Exception:
        return False


_OLLAMA_COMMON_PATHS = [
    "/opt/homebrew/opt/ollama/bin/ollama",
    "/opt/homebrew/bin/ollama",
    "/usr/local/bin/ollama",
    "/usr/bin/ollama",
    os.path.expanduser("~/Applications/Ollama.app/Contents/Resources/ollama"),
    "/Applications/Ollama.app/Contents/Resources/ollama",
]


def _ollama_binary_path() -> Optional[str]:
    """Find ollama binary on PATH or in known install locations.
    Independent of the parent process's $PATH (which may be venv-stripped).
    """
    found = shutil.which("ollama")
    if found:
        return found
    for p in _OLLAMA_COMMON_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def _ollama_on_path() -> bool:
    return _ollama_binary_path() is not None


async def _chroma_ready() -> bool:
    """Chroma is embedded — healthy iff the backend /health says so."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(BACKEND_HEALTH)
            if r.status_code == 200:
                return r.json().get("chroma_ready", False)
    except Exception:
        pass
    return False


async def _service_status(name: str) -> dict:
    """Return a status dict for one service. Always reflects live state."""
    if name == "backend":
        return {"status": "running", "port": 8000, "pid": os.getpid()}

    if name == "chroma":
        ok = await _chroma_ready()
        return {"status": "running" if ok else "stopped", "port": None, "pid": None}

    if name == "ollama":
        # Reachability is the source of truth — if the port responds, it's
        # running, regardless of whether the binary is on this process's PATH.
        # This handles the common case where uvicorn was launched from a venv
        # whose PATH doesn't include /opt/homebrew/opt/ollama/bin.
        if await _http_ok(OLLAMA_HEALTH):
            return {"status": "running", "port": 11434, "pid": None}
        if _ollama_binary_path():
            return {"status": "stopped", "port": 11434, "pid": None}
        return {"status": "not_installed", "port": 11434, "pid": None}

    if name == "redis":
        ok = _port_open(6379)
        return {"status": "running" if ok else "stopped", "port": 6379, "pid": None}

    if name == "worker":
        alive = _proc_alive("worker")
        return {"status": "running" if alive else "stopped", "port": None, "pid": None}

    return {"status": "unknown", "port": None, "pid": None}


# ── Start helpers ─────────────────────────────────────────────────────────────

async def _wait_healthy(name: str, timeout: int = 30) -> bool:
    for _ in range(timeout * 2):
        s = await _service_status(name)
        if s["status"] == "running":
            return True
        await asyncio.sleep(0.5)
    return False


async def _start_ollama() -> bool:
    if await _http_ok(OLLAMA_HEALTH):
        if _managed_proc_owners.get("ollama") == "blueprint_queue":
            _managed_proc_owners["ollama"] = "manual"
        return True  # already running
    binary = _ollama_binary_path()
    if not binary:
        return False
    proc = subprocess.Popen(
        [binary, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _managed_procs["ollama"] = proc
    _managed_proc_owners["ollama"] = "manual"
    return await _wait_healthy("ollama", timeout=30)


async def start_ollama_for_blueprint_queue() -> bool:
    """Start Ollama for blueprint work only when it is not already running.

    Ownership is explicit. If Ollama was already reachable, SHAIL did not
    start it and the blueprint queue is not allowed to auto-stop it later.
    """
    global _blueprint_ollama_idle_since
    if await _http_ok(OLLAMA_HEALTH):
        _blueprint_ollama_idle_since = None
        return True
    binary = _ollama_binary_path()
    if not binary:
        return False
    proc = subprocess.Popen(
        [binary, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _managed_procs["ollama"] = proc
    _managed_proc_owners["ollama"] = "blueprint_queue"
    _blueprint_ollama_idle_since = None
    return await _wait_healthy("ollama", timeout=30)


async def stop_blueprint_queue_ollama_if_idle() -> bool:
    """Auto-stop only the Ollama process started by blueprint queue.

    Never kills by port and never stops a user/manual Ollama process.
    """
    global _blueprint_ollama_idle_since
    proc = _managed_procs.get("ollama")
    if _managed_proc_owners.get("ollama") != "blueprint_queue":
        _blueprint_ollama_idle_since = None
        return False
    if proc is None or proc.poll() is not None:
        _managed_procs.pop("ollama", None)
        _managed_proc_owners.pop("ollama", None)
        _blueprint_ollama_idle_since = None
        return False

    try:
        from apps.shail.blueprint_queue import stats as queue_stats
        qs = queue_stats()
    except Exception:
        qs = {"pending": 0, "running": 0}
    if int(qs.get("pending") or 0) > 0 or int(qs.get("running") or 0) > 0:
        _blueprint_ollama_idle_since = None
        return False

    now = time.time()
    if _blueprint_ollama_idle_since is None:
        _blueprint_ollama_idle_since = now
        return False
    if now - _blueprint_ollama_idle_since < BLUEPRINT_OLLAMA_IDLE_SECONDS:
        return False

    proc.send_signal(signal.SIGTERM)
    for _ in range(10):
        if proc.poll() is not None:
            break
        await asyncio.sleep(0.5)
    if proc.poll() is None:
        proc.kill()
    _managed_procs.pop("ollama", None)
    _managed_proc_owners.pop("ollama", None)
    _blueprint_ollama_idle_since = None
    return True


async def _start_redis() -> bool:
    if _port_open(6379):
        return True
    proc = subprocess.Popen(
        ["redis-server"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _managed_procs["redis"] = proc
    return await _wait_healthy("redis", timeout=10)


async def _start_worker() -> bool:
    if _proc_alive("worker"):
        return True
    env = os.environ.copy()
    env["PYTHONPATH"] = str(os.path.join(os.path.dirname(__file__), "..", ".."))
    proc = subprocess.Popen(
        [sys.executable, "-m", "shail.workers.task_worker"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _managed_procs["worker"] = proc
    await asyncio.sleep(1)
    return _proc_alive("worker")


# ── Stop helpers ──────────────────────────────────────────────────────────────

async def _stop_service(name: str) -> bool:
    proc = _managed_procs.pop(name, None)
    _managed_proc_owners.pop(name, None)
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        for _ in range(10):
            if proc.poll() is not None:
                break
            await asyncio.sleep(0.5)
        if proc.poll() is None:
            proc.kill()

    # For services not in _managed_procs (e.g. user-started Ollama), also kill by port
    port = PORTS.get(name)
    if port and _port_open(port):
        # Find and kill process on port via lsof
        try:
            out = subprocess.check_output(
                ["lsof", "-ti", f":{port}"], text=True
            ).strip()
            for pid_str in out.splitlines():
                try:
                    os.kill(int(pid_str), signal.SIGTERM)
                except ProcessLookupError:
                    pass
        except subprocess.CalledProcessError:
            pass
        for _ in range(10):
            if not _port_open(port):
                break
            await asyncio.sleep(0.5)

    return True


# ── SSE stream helpers ────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    import json as _json
    return f"data: {_json.dumps(data)}\n\n"


async def _start_stream(services: list[str]) -> AsyncIterator[str]:
    for name in services:
        status = await _service_status(name)
        if status["status"] == "running":
            yield _sse({"service": name, "status": "already_running"})
            continue

        if name == "chroma":
            # Chroma is embedded — trigger init by probing the health endpoint
            yield _sse({"service": name, "status": "starting"})
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    await client.get(BACKEND_HEALTH)
            except Exception:
                pass
            ok = await _chroma_ready()
            yield _sse({"service": name, "status": "running" if ok else "error",
                         "message": "" if ok else "Chroma failed to initialise"})
            if not ok:
                yield _sse({"done": True, "error": True})
                return
            continue

        yield _sse({"service": name, "status": "starting"})

        if name == "ollama":
            ok = await _start_ollama()
        elif name == "redis":
            ok = await _start_redis()
        elif name == "worker":
            ok = await _start_worker()
        else:
            ok = False

        if ok:
            yield _sse({"service": name, "status": "running"})
        else:
            msg = "not installed" if name == "ollama" and not _ollama_on_path() else "failed to start"
            yield _sse({"service": name, "status": "error", "message": msg})
            yield _sse({"done": True, "error": True})
            return

    yield _sse({"done": True, "error": False})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@system_router.get("/status")
async def system_status(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
):
    """
    Returns live status of all SHAIL services.
    No auth required — called on dashboard load before sign-in.
    """
    tier = "free"
    if credentials:
        uid = get_user_by_api_key(credentials.credentials)
        if uid:
            tier = get_user_tier(uid)

    services_to_check = ["backend", "chroma", "ollama"]
    if tier == "pro":
        services_to_check += ["redis", "worker"]

    results = {}
    for name in services_to_check:
        results[name] = await _service_status(name)
        owner = _managed_proc_owners.get(name)
        if owner:
            results[name]["managed_owner"] = owner

    try:
        from apps.shail.blueprint_queue import stats as queue_stats
        blueprint_queue = queue_stats()
    except Exception:
        blueprint_queue = {"total": 0, "pending": 0, "running": 0, "done": 0, "failed": 0}

    return {"services": results, "tier": tier, "blueprint_queue": blueprint_queue}


@system_router.post("/start")
async def system_start(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
):
    """
    Start all services in dependency order.
    Returns an SSE stream of per-service progress events.
    Auth required.
    """
    user_id = _require_auth(credentials)
    tier = get_user_tier(user_id)

    services = ["ollama", "chroma"]
    if tier == "pro":
        services += ["redis", "worker"]

    return StreamingResponse(
        _start_stream(services),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@system_router.post("/stop")
async def system_stop(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
):
    """
    Stop managed services in reverse dependency order.
    FastAPI itself is never stopped from here.
    Auth required.
    """
    user_id = _require_auth(credentials)
    tier = get_user_tier(user_id)

    stop_order = []
    if tier == "pro":
        stop_order += ["worker", "redis"]
    stop_order += ["ollama"]  # chroma is embedded, stops with backend

    stopped = []
    for name in stop_order:
        await _stop_service(name)
        stopped.append(name)

    return {
        "stopped": stopped,
        "note": "FastAPI backend was not stopped. Run ./scripts/stop_shail.sh to fully shut down.",
    }


@system_router.post("/restart/{service}")
async def system_restart_service(
    service: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
):
    """Stop and restart a single named service."""
    user_id = _require_auth(credentials)
    tier = get_user_tier(user_id)

    allowed = {"ollama", "chroma"}
    if tier == "pro":
        allowed |= {"redis", "worker"}

    if service not in allowed:
        raise HTTPException(status_code=400, detail=f"Unknown or not-allowed service: {service}")

    await _stop_service(service)
    await asyncio.sleep(1)

    async def _stream():
        async for chunk in _start_stream([service]):
            yield chunk

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@system_router.get("/ollama-models")
async def ollama_models():
    """List installed Ollama models. No auth — used to drive the dashboard's
    'connect to existing Ollama' UX. Returns reachable + binary state so the
    UI can decide between three states: not_installed / stopped / running.
    """
    binary = _ollama_binary_path()
    reachable = await _http_ok(OLLAMA_HEALTH)

    models: list[dict] = []
    if reachable:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(OLLAMA_HEALTH)
                if r.status_code == 200:
                    for m in r.json().get("models", []) or []:
                        models.append({
                            "name": m.get("name", ""),
                            "size": m.get("size", 0),
                            "modified_at": m.get("modified_at", ""),
                        })
        except Exception:
            pass

    if reachable:
        status = "running"
    elif binary:
        status = "stopped"
    else:
        status = "not_installed"

    return {
        "status": status,
        "binary_path": binary,
        "models": models,
        "has_gemma": any("gemma" in (m["name"] or "").lower() for m in models),
        "install_url": "https://ollama.com/download",
    }
