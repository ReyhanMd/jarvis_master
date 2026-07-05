"""
SHAIL Auth API
──────────────
FastAPI router for user registration, login, and API key management.

Endpoints (mounted at /auth):
  POST /register   { email, password, name? }   → 403 (registration disabled in single-user mode)
  POST /login      { email, password }           → { user_id, api_key, email, name }
  GET  /me         (Bearer required)             → { user_id, email, name, created_at }
  GET  /keys       (Bearer required)             → [{ key_prefix, label, created_at, last_used }]
  POST /keys       { label? }                    → { key, label }
  DELETE /keys/{key}                             → { ok: true }

Single-User Mode:
  SHAIL_ALLOW_REGISTRATION=false  → POST /register returns 403
  SHAIL_CANONICAL_EMAIL set       → OAuth flows reject non-canonical accounts
  get_user_or_local()             → raises 401 (no fallback to "local" ever)
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from apps.shail.limiter import limiter
from pydantic import BaseModel, Field

from apps.shail.auth_store import (
    create_api_key,
    create_user,
    get_user_by_email,
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


# ── Canonical user guard ───────────────────────────────────────────────────────

def assert_canonical_email(email: str) -> None:
    """
    Reject any email that is not the canonical account.
    Only active when SHAIL_CANONICAL_EMAIL is set in settings.
    Call this in every OAuth and login handler that creates a session.
    """
    from apps.shail.settings import get_settings
    canonical = get_settings().canonical_user_email
    if canonical and email.lower().strip() != canonical.lower().strip():
        raise HTTPException(
            status_code=403,
            detail=(
                f"This SHAIL instance is restricted to {canonical}. "
                "Sign in with the correct account."
            ),
        )


# ── Auth dependencies ──────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> str:
    """
    FastAPI dependency. Returns user_id string.
    Raises HTTP 401 if the bearer token is missing or invalid.
    No fallback — authentication is always required.
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Sign in at http://localhost:8000/dashboard",
        )
    key = credentials.credentials
    user_id = get_user_by_api_key(key)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    touch_api_key_last_used(key)
    touch_user_last_seen(user_id)
    return user_id


async def get_user_or_local(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> str:
    """
    SINGLE-USER MODE: This dependency no longer has an anonymous fallback.
    Behaviour is now identical to get_current_user — raises 401 when
    no valid token is present.

    The function name is preserved for import compatibility only.
    The 'or_local' path is permanently removed.
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Sign in at http://localhost:8000/dashboard",
        )
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
@limiter.limit("5/minute")
async def register(request: Request, req: RegisterRequest) -> AuthResponse:
    """
    Register a new account.
    DISABLED in single-user mode (SHAIL_ALLOW_REGISTRATION=false).
    """
    from apps.shail.settings import get_settings
    if not get_settings().allow_registration:
        raise HTTPException(
            status_code=403,
            detail=(
                "Registration is disabled. This SHAIL instance is single-user. "
                f"Sign in as {get_settings().canonical_user_email or 'the configured account'}."
            ),
        )
    # Canonical email guard — even when registration is open, only allow the configured email
    assert_canonical_email(req.email)
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
@limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest) -> AuthResponse:
    """Authenticate and return a new API key for this session."""
    # Canonical email guard
    assert_canonical_email(req.email)
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


# ── Apple Sign In ─────────────────────────────────────────────────────────────

class AppleSignInRequest(BaseModel):
    identity_token: str
    full_name: str = ""


_APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER   = "https://appleid.apple.com"
_apple_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}


def _get_apple_jwks() -> list:
    """Fetch Apple's JWKS once per hour."""
    import time as _time
    import httpx as _httpx
    if _apple_jwks_cache["keys"] and (_time.time() - _apple_jwks_cache["fetched_at"]) < 3600:
        return _apple_jwks_cache["keys"]
    with _httpx.Client(timeout=5.0) as c:
        r = c.get(_APPLE_JWKS_URL)
        r.raise_for_status()
        keys = r.json().get("keys", [])
    _apple_jwks_cache["keys"] = keys
    _apple_jwks_cache["fetched_at"] = _time.time()
    return keys


@auth_router.post("/apple", response_model=AuthResponse)
@limiter.limit("5/minute")
async def apple_sign_in(request: Request, req: AppleSignInRequest) -> AuthResponse:
    """
    Verify an Apple identity token (JWT signed by Apple) and return a SHAIL API key.
    Canonical user guard: rejects non-canonical Apple accounts.
    """
    import os as _os
    try:
        import jwt as _jwt
        from jwt import PyJWKClient  # noqa: F401
    except Exception:
        raise HTTPException(status_code=500, detail="PyJWT not installed on backend")

    audience = _os.getenv("APPLE_AUDIENCE", "")
    if not audience:
        raise HTTPException(status_code=503, detail="APPLE_AUDIENCE env var not configured on backend")

    try:
        header = _jwt.get_unverified_header(req.identity_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Malformed identity_token: {exc}")

    kid = header.get("kid")
    keys = _get_apple_jwks()
    matching = next((k for k in keys if k.get("kid") == kid), None)
    if not matching:
        raise HTTPException(status_code=401, detail="No matching Apple JWKS key")

    try:
        public_key = _jwt.algorithms.RSAAlgorithm.from_jwk(matching)
        claims = _jwt.decode(
            req.identity_token,
            key=public_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=_APPLE_ISSUER,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Apple token: {exc}")

    sub = claims.get("sub")
    email = claims.get("email", "")
    if not sub:
        raise HTTPException(status_code=401, detail="Apple token has no sub claim")

    # Canonical user guard — only the configured account may use Apple SSO
    if email:
        assert_canonical_email(email)

    name = req.full_name or claims.get("email", "Apple User")
    existing = get_user_by_email(email) if email else None
    if existing:
        user_id = existing["id"]
        api_key = create_api_key(user_id, label="Apple SSO")
        return AuthResponse(
            user_id=user_id,
            api_key=api_key,
            email=existing["email"],
            name=existing["name"] or name,
        )

    import secrets as _secrets
    placeholder_pw = _secrets.token_urlsafe(32)
    try:
        user = create_user(email=email or f"apple_{sub}@privaterelay.appleid.com",
                            password=placeholder_pw, name=name)
    except ValueError:
        import asyncio as _asyncio
        user = None
        for _ in range(5):
            user = get_user_by_email(email or f"apple_{sub}@privaterelay.appleid.com")
            if user:
                break
            await _asyncio.sleep(0.1)
        if not user:
            raise HTTPException(status_code=500, detail="Failed to create or retrieve user")

    api_key = create_api_key(user["id"], label="Apple SSO")
    return AuthResponse(
        user_id=user["id"],
        api_key=api_key,
        email=user["email"],
        name=user["name"] or name,
    )
