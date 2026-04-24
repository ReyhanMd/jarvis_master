"""
SHAIL Auth API
──────────────
FastAPI router for user registration, login, and API key management.

Endpoints (mounted at /auth):
  POST /register   { email, password, name? }   → { user_id, api_key, email, name }
  POST /login      { email, password }           → { user_id, api_key, email, name }
  GET  /me         (Bearer required)             → { user_id, email, name, created_at }
  GET  /keys       (Bearer required)             → [{ key_prefix, label, created_at, last_used }]
  POST /keys       { label? }                    → { key, label }
  DELETE /keys/{key}                             → { ok: true }

The `get_current_user` dependency is exported for use by other routers
(browser_api, memory_dashboard_api, etc.).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from apps.shail.auth_store import (
    create_api_key,
    create_user,
    get_user_by_id,
    list_api_keys,
    revoke_api_key,
    touch_api_key_last_used,
    touch_user_last_seen,
    verify_password,
    get_user_by_api_key,
)

auth_router = APIRouter()
_security = HTTPBearer(auto_error=False)


# ── Auth dependency ────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> str:
    """
    FastAPI dependency. Returns user_id string.
    Raises HTTP 401 if the bearer token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization required")
    key = credentials.credentials
    user_id = get_user_by_api_key(key)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    touch_api_key_last_used(key)
    touch_user_last_seen(user_id)
    return user_id


# ── Request / Response models ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=6)
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    user_id: str
    api_key: str
    email: str
    name: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    name: str
    created_at: str


class ApiKeyListItem(BaseModel):
    key_prefix: str
    label: str
    created_at: str
    last_used: Optional[str]


class NewKeyRequest(BaseModel):
    label: str = ""


class NewKeyResponse(BaseModel):
    key: str
    label: str


class RevokeResponse(BaseModel):
    ok: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@auth_router.post("/register", response_model=AuthResponse, status_code=201)
async def register(req: RegisterRequest) -> AuthResponse:
    """Register a new account and return the first API key."""
    try:
        user = create_user(email=req.email, password=req.password, name=req.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    api_key = create_api_key(user["id"], label="Default")
    return AuthResponse(
        user_id=user["id"],
        api_key=api_key,
        email=user["email"],
        name=user["name"] or "",
    )


@auth_router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest) -> AuthResponse:
    """Authenticate and return a new API key for this session."""
    user = verify_password(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    api_key = create_api_key(user["id"], label="Login")
    return AuthResponse(
        user_id=user["id"],
        api_key=api_key,
        email=user["email"],
        name=user["name"] or "",
    )


@auth_router.get("/me", response_model=MeResponse)
async def me(user_id: str = Depends(get_current_user)) -> MeResponse:
    """Return current user profile."""
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return MeResponse(
        user_id=user["id"],
        email=user["email"],
        name=user["name"] or "",
        created_at=user["created_at"],
    )


@auth_router.get("/keys", response_model=List[ApiKeyListItem])
async def get_keys(user_id: str = Depends(get_current_user)) -> List[ApiKeyListItem]:
    """List all active API keys for the current user."""
    keys = list_api_keys(user_id)
    return [ApiKeyListItem(**k) for k in keys]


@auth_router.post("/keys", response_model=NewKeyResponse, status_code=201)
async def add_key(
    req: NewKeyRequest,
    user_id: str = Depends(get_current_user),
) -> NewKeyResponse:
    """Create an additional API key (e.g. for a second browser)."""
    key = create_api_key(user_id, label=req.label or "New device")
    return NewKeyResponse(key=key, label=req.label or "New device")


@auth_router.delete("/keys/{key}", response_model=RevokeResponse)
async def delete_key(
    key: str,
    user_id: str = Depends(get_current_user),
) -> RevokeResponse:
    """Revoke an API key. Only works on keys owned by the current user."""
    ok = revoke_api_key(key, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found or not owned by you")
    return RevokeResponse(ok=True)
