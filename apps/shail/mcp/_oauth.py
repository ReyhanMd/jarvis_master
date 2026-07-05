"""
OAuth + chunked-ingest helpers shared across MCP providers.

Keeps the per-provider modules focused on their unique endpoints/scopes
rather than reinventing token exchange + indexing plumbing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from shail.memory.rag import ingest

logger = logging.getLogger(__name__)

# ── Google token refresh ─────────────────────────────────────────────────────

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REFRESH_WINDOW = 300  # refresh when < 5 min remain


def _is_token_expired(expires_at: Optional[str]) -> bool:
    """True if the token is within the refresh window or already expired."""
    if not expires_at:
        return False  # no expiry stored → assume permanent (e.g. GitHub)
    try:
        exp = datetime.fromisoformat(expires_at)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return (exp - datetime.now(timezone.utc)).total_seconds() < _REFRESH_WINDOW
    except ValueError:
        return False


async def maybe_refresh_google_token(conn: dict) -> dict:
    """If the stored Google access_token is near expiry, exchange the
    refresh_token for a fresh one. Returns the (possibly updated) connection
    dict and persists the new token to the DB.

    Safe to call for non-Google providers or connections without refresh_token
    — returns the connection unchanged in those cases.
    """
    if not _is_token_expired(conn.get("expires_at")):
        return conn
    refresh_token = conn.get("refresh_token")
    if not refresh_token:
        logger.warning(
            "mcp token expired for %s/%s but no refresh_token stored — "
            "user must reconnect the provider.",
            conn.get("user_id"), conn.get("provider"),
        )
        return conn
    from apps.shail.settings import get_settings
    s = get_settings()
    try:
        resp = await post_form(
            GOOGLE_TOKEN_URL,
            {
                "grant_type":    "refresh_token",
                "refresh_token": refresh_token,
                "client_id":     s.google_client_id,
                "client_secret": s.google_client_secret,
            },
        )
        new_access = resp.get("access_token")
        if not new_access:
            raise ValueError(f"token refresh response missing access_token: {resp}")
        expires_in = resp.get("expires_in")
        new_expires = expires_at_iso(expires_in)
        # Some responses re-issue a new refresh_token (rotation).
        new_refresh = resp.get("refresh_token") or refresh_token
        from apps.shail.mcp_store import save_connection
        updated = save_connection(
            conn["user_id"], conn["provider"],
            access_token=new_access,
            refresh_token=new_refresh,
            expires_at=new_expires,
            scope=conn.get("scope"),
            metadata=conn.get("metadata"),
        )
        logger.info(
            "mcp token refreshed for %s/%s expires_at=%s",
            conn["user_id"], conn["provider"], new_expires,
        )
        return updated
    except Exception as exc:
        logger.error(
            "mcp token refresh FAILED for %s/%s: %s — using stale token",
            conn.get("user_id"), conn.get("provider"), exc,
        )
        return conn


def expires_at_iso(expires_in_seconds: Optional[int]) -> Optional[str]:
    if not expires_in_seconds:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in_seconds))).isoformat()


async def post_form(
    url: str, data: dict, *, headers: Optional[dict] = None, timeout: float = 15.0,
) -> dict:
    """POST application/x-www-form-urlencoded; raise on non-2xx; return JSON."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, data=data, headers=headers or {})
        resp.raise_for_status()
        return resp.json()


async def post_json(
    url: str, payload: dict, *, headers: Optional[dict] = None, timeout: float = 15.0,
) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers or {})
        resp.raise_for_status()
        return resp.json()


async def get_json(
    url: str, *, headers: Optional[dict] = None, params: Optional[dict] = None, timeout: float = 15.0,
) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, headers=headers or {}, params=params or {})
        resp.raise_for_status()
        return resp.json()


def mcp_namespace(user_id: str, provider: str) -> str:
    return f"mcp_{user_id}_{provider}"


def ingest_record(
    *, user_id: str, provider: str, doc_id: str,
    title: str, content: str, url: Optional[str] = None,
    extra_meta: Optional[dict] = None,
) -> int:
    """Embed and store one MCP document. Returns 1 on success, 0 on empty/failed."""
    if not content or len(content.strip()) < 10:
        return 0
    namespace = mcp_namespace(user_id, provider)
    metadata = {
        "id":          f"{provider}:{doc_id}",
        "customId":    f"{provider}:{doc_id}",
        "provider":    provider,
        "provider_id": doc_id,
        "title":       title or "(untitled)",
        "summary":     (content or "")[:400],
        "tier":        "important",
        "source":      f"mcp_{provider}",
        "namespace":   namespace,
    }
    if url:
        metadata["sourceUrl"] = url
    if extra_meta:
        metadata.update(extra_meta)
    try:
        chunks = ingest(records=[{
            "id":        f"{provider}:{doc_id}",
            "content":   content[:10_000],
            "namespace": namespace,
            "metadata":  metadata,
        }])
        return 1 if chunks else 0
    except Exception as e:
        logger.warning("mcp ingest failed (%s/%s): %s", provider, doc_id, e)
        return 0
