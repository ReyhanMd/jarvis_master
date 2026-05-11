"""
Google OAuth2 flow for SHAIL.

Endpoints (mounted at /auth/google by main.py):
  GET /start?state={uuid}   → redirect to Google consent page
  GET /callback             → exchange code, create/login user, store result
  GET /token?state={uuid}   → polled by the macOS app (200 = ready, 204 = wait)

Env vars required:
  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET

Register http://localhost:8000/auth/google/callback as an authorized
redirect URI in the Google Cloud Console OAuth 2.0 credentials.
"""

from __future__ import annotations

import os
import secrets
import ssl
from urllib.parse import urlencode

import certifi
import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from apps.shail.auth_store import create_api_key, create_user, get_user_by_api_key, get_user_by_email

google_auth_router = APIRouter()

# ── Config ──────────────────────────────────────────────────────────────────

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI         = "http://localhost:8000/auth/google/callback"

# ── In-memory state (single-instance; resets on server restart) ─────────────
# state → "pending" (TTL-bounded so abandoned auth flows are cleaned up)
try:
    from cachetools import TTLCache
    _pending = TTLCache(maxsize=128, ttl=600)   # 10 minutes
    _tokens  = TTLCache(maxsize=128, ttl=600)
except Exception:
    # Fallback if cachetools missing — same shape, no TTL
    _pending = {}     # type: ignore[assignment]
    _tokens  = {}     # type: ignore[assignment]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _oauth_http_client() -> httpx.AsyncClient:
    """
    Build an HTTPS client with an explicit CA bundle.

    Some local macOS Python/OpenSSL installs end up with a broken default
    certificate path, which causes `httpx.AsyncClient()` construction itself to
    fail with FileNotFoundError before we even reach Google's token endpoint.
    Pinning to certifi avoids that machine-specific failure mode.
    """
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return httpx.AsyncClient(verify=ssl_context)

def _get_or_create_user(email: str, name: str) -> tuple[str, str]:
    """Return (api_key, user_id) for this Google user (create account if new)."""
    existing = get_user_by_email(email)
    if existing:
        api_key = create_api_key(existing["id"], label="Google OAuth")
        return api_key, existing["id"]
    try:
        user = create_user(email=email, password=f"google_sso_{email}", name=name)
        api_key = create_api_key(user["id"], label="Google OAuth")
        return api_key, user["id"]
    except ValueError:
        existing = get_user_by_email(email)
        if existing:
            api_key = create_api_key(existing["id"], label="Google OAuth")
            return api_key, existing["id"]
        raise


# ── Routes ───────────────────────────────────────────────────────────────────

@google_auth_router.get("/start")
async def google_start(state: str = ""):
    """
    Begin Google OAuth2 flow.
    The macOS app generates a UUID state and passes it here so it can poll /token.
    """
    if not GOOGLE_CLIENT_ID:
        return HTMLResponse(
            "<h2>Google OAuth not configured — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET</h2>",
            status_code=503,
        )
    # Use caller-supplied state (preferred) or generate one
    s = state or secrets.token_urlsafe(16)
    _pending[s] = "pending"

    params = urlencode({
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         s,
        "access_type":   "offline",
        "prompt":        "select_account",
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@google_auth_router.get("/callback")
async def google_callback(code: str = "", state: str = "", error: str = ""):
    """Google redirects here after the user consents (or denies)."""
    if error:
        return HTMLResponse(
            f"<h2>Google sign-in denied: {error}</h2><p>Close this tab and try again.</p>",
            status_code=400,
        )
    if not code or state not in _pending:
        return HTMLResponse("<h2>Invalid or expired auth session.</h2>", status_code=400)

    # Exchange authorization code for tokens
    async with _oauth_http_client() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
            timeout=15,
        )
    token_data = token_resp.json()
    access_token = token_data.get("access_token", "")
    if not access_token:
        return HTMLResponse("<h2>Token exchange failed.</h2>", status_code=502)

    # Fetch user info from Google
    async with _oauth_http_client() as client:
        info_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    userinfo = info_resp.json()
    email = userinfo.get("email", "")
    name  = userinfo.get("name", "")

    if not email:
        return HTMLResponse("<h2>Could not retrieve email from Google.</h2>", status_code=502)

    try:
        api_key, user_id = _get_or_create_user(email, name)
    except Exception as exc:
        return HTMLResponse(f"<h2>Account creation failed: {exc}</h2>", status_code=500)

    # Store result for polling
    _tokens[state] = {"email": email, "name": name, "api_key": api_key, "user_id": user_id}
    del _pending[state]

    return HTMLResponse("""
    <html>
    <head><title>SHAIL — Signed In</title></head>
    <body style="font-family:system-ui;padding:40px;background:#0d0d0f;color:#fff;text-align:center">
      <h2 style="color:#4d9fff">✓ Signed in to SHAIL</h2>
      <p style="color:rgba(255,255,255,.6)">Return to the app — this tab can be closed.</p>
      <script>setTimeout(()=>window.close(),2000)</script>
    </body>
    </html>
    """)


@google_auth_router.get("/token")
async def google_token_poll(state: str = "", response: Response = None):
    """
    Polled by the macOS app every 2 s.
    Returns 200 + JSON when ready, 204 when still waiting.
    """
    if state and state in _tokens:
        result = _tokens.pop(state)
        return result
    # Without state: return the first available token (single-user convenience)
    if not state and _tokens:
        _, result = next(iter(_tokens.items()))
        _tokens.clear()
        return result
    response.status_code = 204
    return None
