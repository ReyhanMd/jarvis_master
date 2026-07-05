"""
MCP FastAPI router — OAuth flows + connection list + index status + settings.

Mounted at /mcp by main.py. All endpoints require auth except the OAuth
callback (which uses signed state to identify the user).

Endpoints:
    GET    /mcp/providers                       provider catalog (configured? scopes?)
    GET    /mcp/connections                     list user's connections
    DELETE /mcp/connections/{provider}          disconnect

    GET    /mcp/{provider}/auth/start           returns {authorize_url}
    GET    /mcp/{provider}/auth/callback        public — completes OAuth (state-bound)
    GET    /mcp/{provider}/index/status         {indexed_count, status, error}
    POST   /mcp/{provider}/index/run            kick off (re-)index
    GET    /mcp/{provider}/settings             provider settings (e.g. Gmail labels)
    PUT    /mcp/{provider}/settings             update settings
    GET    /mcp/{provider}/labels               Gmail-only: list labels for picker
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from apps.shail.auth_store import (
    get_user_by_api_key, touch_api_key_last_used, touch_user_last_seen,
)
from apps.shail.mcp import PROVIDERS, get_provider
from apps.shail.mcp._oauth import get_json
from apps.shail.mcp_store import (
    delete_connection, get_connection, get_settings as get_mcp_settings,
    list_connections, save_connection, save_settings, update_index_status,
)
from apps.shail.settings import get_settings as get_app_settings

logger = logging.getLogger(__name__)

mcp_router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


# ── Auth helper ─────────────────────────────────────────────────────────────

def _require_user(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id = get_user_by_api_key(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid API key")
    touch_api_key_last_used(credentials.credentials)
    touch_user_last_seen(user_id)
    return user_id


# ── In-memory state map for OAuth state→user_id+provider ────────────────────
# OAuth flows are short (typically < 60s), so a TTL dict in process memory is
# enough. The state token is opaque and unguessable; if the server restarts
# mid-flow the user just retries.

_STATE_TTL = 600  # 10 minutes
_state_map: dict[str, dict] = {}


def _gc_states() -> None:
    now = time.time()
    expired = [k for k, v in _state_map.items() if v["exp"] < now]
    for k in expired:
        _state_map.pop(k, None)


def _new_state(user_id: str, provider: str) -> str:
    _gc_states()
    state = secrets.token_urlsafe(32)
    _state_map[state] = {
        "user_id": user_id, "provider": provider,
        "exp": time.time() + _STATE_TTL,
    }
    return state


def _consume_state(state: str) -> Optional[dict]:
    _gc_states()
    return _state_map.pop(state, None)


def _redirect_uri(provider: str) -> str:
    s = get_app_settings()
    base = s.public_origin.rstrip("/")
    return f"{base}/mcp/{provider}/auth/callback"


# ── Provider catalog ────────────────────────────────────────────────────────

@mcp_router.get("/providers")
async def list_providers(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    user_conns = {c["provider"]: c for c in list_connections(user_id)}
    items = []
    for name, prov in PROVIDERS.items():
        c = user_conns.get(name)
        items.append({
            "name":          name,
            "label":         prov.label,
            "scopes":        prov.scopes,
            "configured":    prov.is_configured(),
            "connected":     bool(c),
            "metadata":      (c or {}).get("metadata", {}),
            "indexed_count": (c or {}).get("indexed_count", 0),
            "index_status":  (c or {}).get("index_status", "idle"),
            "index_error":   (c or {}).get("index_error"),
            "last_synced":   (c or {}).get("last_synced"),
        })
    return {"items": items}


@mcp_router.get("/connections")
async def get_connections(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    return {"items": [
        {k: v for k, v in c.items() if k not in ("access_token", "refresh_token")}
        for c in list_connections(user_id)
    ]}


@mcp_router.delete("/connections/{provider}")
async def disconnect_provider(
    provider: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="unknown provider")
    delete_connection(user_id, provider)
    return {"ok": True, "provider": provider}


# ── OAuth start / callback ──────────────────────────────────────────────────

@mcp_router.get("/{provider}/auth/start")
async def auth_start(
    provider: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    prov = get_provider(provider)
    if not prov:
        raise HTTPException(status_code=404, detail="unknown provider")
    if not prov.is_configured():
        raise HTTPException(
            status_code=503,
            detail=f"OAuth credentials missing for {provider}. "
                   f"Set the appropriate CLIENT_ID/CLIENT_SECRET in .env.",
        )
    state = _new_state(user_id, provider)
    redirect_uri = _redirect_uri(provider)
    return {"authorize_url": prov.oauth_authorize_url(state=state, redirect_uri=redirect_uri)}


@mcp_router.get("/{provider}/auth/callback")
async def auth_callback(
    provider: str,
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """Public endpoint — OAuth provider redirects here after consent.
    State token binds the callback to the original user/provider pair.
    Returns a tiny HTML page that closes the popup window.
    """
    if error:
        return _callback_html(error=f"Provider returned error: {error}")
    if not code or not state:
        return _callback_html(error="Missing code or state")
    binding = _consume_state(state)
    if not binding or binding["provider"] != provider:
        return _callback_html(error="Invalid or expired state")
    user_id = binding["user_id"]
    prov = get_provider(provider)
    if not prov:
        return _callback_html(error="Unknown provider")
    redirect_uri = _redirect_uri(provider)
    try:
        tokens = await prov.exchange_code(code=code, redirect_uri=redirect_uri)
    except Exception as e:
        logger.exception("oauth exchange failed for %s: %s", provider, e)
        return _callback_html(error=f"Token exchange failed: {e}")
    save_connection(
        user_id, provider,
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        expires_at=tokens.get("expires_at"),
        scope=tokens.get("scope"),
        metadata=tokens.get("metadata"),
    )
    # Fire indexer in background — don't block the popup close
    asyncio.create_task(_run_index(user_id, provider))
    return _callback_html(provider=provider)


def _callback_html(*, provider: Optional[str] = None, error: Optional[str] = None) -> HTMLResponse:
    import json as _json
    if error:
        body = (
            "<h2 style='color:#ef4444'>Connection failed</h2>"
            f"<p style='color:#666;font-family:monospace'>{error}</p>"
            "<p>You can close this window.</p>"
        )
        msg_json = _json.dumps({"type": "shail-mcp-result", "ok": False, "error": error})
    else:
        body = (
            f"<h2 style='color:#22c55e'>Connected to {provider}</h2>"
            "<p>Indexing has started in the background. You can close this window.</p>"
        )
        msg_json = _json.dumps({"type": "shail-mcp-result", "ok": True, "provider": provider})
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>SHAIL · MCP</title></head>
<body style="background:#000;color:#fff;font-family:system-ui;padding:40px;text-align:center">
{body}
<script>
try {{ window.opener && window.opener.postMessage({msg_json}, '*'); }} catch(e) {{}}
setTimeout(() => window.close(), 1500);
</script>
</body></html>"""
    return HTMLResponse(html)


# ── Indexing ────────────────────────────────────────────────────────────────

async def _run_index(user_id: str, provider: str) -> None:
    conn = get_connection(user_id, provider)
    prov = get_provider(provider)
    if not conn or not prov:
        return
    # Refresh Google tokens before indexing — they expire in 1hr.
    try:
        from apps.shail.mcp._oauth import maybe_refresh_google_token
        conn = await maybe_refresh_google_token(conn)
    except Exception as _ref_err:
        logger.debug("pre-index token refresh failed: %s", _ref_err)
    settings = get_mcp_settings(user_id, provider)
    # Pass sync_cursor so providers can do incremental re-index.
    # Forced full re-index: DELETE /connections/{provider} then reconnect,
    # or call /index/run with ?full=true (below).
    settings = {**settings, "sync_cursor": conn.get("sync_cursor")}
    try:
        await prov.index(
            user_id=user_id,
            access_token=conn["access_token"],
            refresh_token=conn.get("refresh_token"),
            settings=settings,
        )
    except Exception as e:
        logger.exception("indexer crashed for %s/%s: %s", user_id, provider, e)
        update_index_status(user_id, provider, status="error", error=str(e)[:300])


@mcp_router.get("/{provider}/index/status")
async def index_status(
    provider: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    conn = get_connection(user_id, provider)
    if not conn:
        raise HTTPException(status_code=404, detail="not connected")
    return {
        "indexed_count": conn["indexed_count"],
        "status":        conn["index_status"],
        "error":         conn["index_error"],
        "last_synced":   conn["last_synced"],
    }


@mcp_router.post("/{provider}/index/run")
async def index_run(
    provider: str,
    full: bool = Query(False, description="Force full re-index, ignoring sync cursor"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    if not get_connection(user_id, provider):
        raise HTTPException(status_code=404, detail="not connected")
    if full:
        # Reset cursor so _run_index passes sync_cursor=None to the provider
        from apps.shail.mcp_store import update_sync_cursor
        update_sync_cursor(user_id, provider, None)
    asyncio.create_task(_run_index(user_id, provider))
    return {"ok": True, "status": "indexing", "full": full}


# ── Settings ────────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    settings: dict


@mcp_router.get("/{provider}/settings")
async def get_provider_settings(
    provider: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    return {"settings": get_mcp_settings(user_id, provider)}


@mcp_router.put("/{provider}/settings")
async def put_provider_settings(
    provider: str,
    body: SettingsUpdate,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="unknown provider")
    saved = save_settings(user_id, provider, body.settings)
    return {"settings": saved}


# ── Gmail label picker ──────────────────────────────────────────────────────

GMAIL_LABELS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/labels"


@mcp_router.get("/gmail/labels")
async def gmail_labels(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    conn = get_connection(user_id, "gmail")
    if not conn:
        raise HTTPException(status_code=404, detail="Gmail not connected")
    try:
        resp = await get_json(
            GMAIL_LABELS_URL,
            headers={"Authorization": f"Bearer {conn['access_token']}"},
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gmail labels fetch failed: {e}")
    return {"labels": resp.get("labels", [])}


# ── Core MCP JSON-RPC Server Loop ───────────────────────────────────────────

from typing import Any

class JsonRpcRequest(BaseModel):
    jsonrpc: str
    method: str
    params: Optional[dict] = None
    id: Optional[Any] = None

class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[dict] = None
    id: Optional[Any] = None

@mcp_router.post("/rpc", response_model=JsonRpcResponse)
async def mcp_jsonrpc_endpoint(
    req: JsonRpcRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> JsonRpcResponse:
    """
    JSON-RPC 2.0 server loop endpoint for secure workspace MCP routing.
    Requires valid authorization bearer credentials.
    """
    try:
        user_id = _require_user(credentials)
    except HTTPException as auth_err:
        return JsonRpcResponse(
            error={"code": -32000, "message": f"Unauthorized: {auth_err.detail}"},
            id=req.id
        )

    if req.jsonrpc != "2.0":
        return JsonRpcResponse(
            error={"code": -32600, "message": "Invalid Request: jsonrpc version must be '2.0'"},
            id=req.id
        )

    method = req.method
    params = req.params or {}

    try:
        from shail.integrations.mcp.provider import get_provider as get_mcp_provider

        if method == "ping":
            return JsonRpcResponse(result="pong", id=req.id)

        elif method == "mcp.ping":
            return JsonRpcResponse(result={"status": "ok"}, id=req.id)

        elif method == "mcp.list_tools":
            provider = get_mcp_provider()
            tools = provider.list_tools()
            return JsonRpcResponse(result={"tools": tools}, id=req.id)

        elif method == "mcp.call_tool":
            tool_name = params.get("name")
            tool_args = params.get("arguments") or {}
            if not tool_name:
                return JsonRpcResponse(
                    error={"code": -32602, "message": "Invalid params: 'name' is required"},
                    id=req.id
                )
            provider = get_mcp_provider()
            tool_func = provider.get_tool(tool_name)
            if not tool_func:
                return JsonRpcResponse(
                    error={"code": -32601, "message": f"Method not found: tool '{tool_name}'"},
                    id=req.id
                )

            # Invoke tool function
            if asyncio.iscoroutinefunction(tool_func):
                res = await tool_func(**tool_args)
            else:
                res = tool_func(**tool_args)
            
            # Format return value to MCP schema
            return JsonRpcResponse(
                result={"content": [{"type": "text", "text": str(res)}]},
                id=req.id
            )

        else:
            return JsonRpcResponse(
                error={"code": -32601, "message": f"Method not found: '{method}'"},
                id=req.id
            )

    except Exception as exc:
        logger.error("JSON-RPC error in method %s: %s", method, exc)
        return JsonRpcResponse(
            error={"code": -32603, "message": f"Internal error: {exc}"},
            id=req.id
        )
