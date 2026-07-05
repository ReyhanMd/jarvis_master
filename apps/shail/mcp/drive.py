"""Google Drive connector — OAuth + file indexing + active query fetch."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx

from apps.shail.mcp.base import FetchHit, MCPProvider
from apps.shail.mcp._oauth import (
    expires_at_iso, get_json, ingest_record, post_form,
)
from apps.shail.mcp_store import update_index_status, update_sync_cursor
from apps.shail.settings import get_settings

logger = logging.getLogger(__name__)

AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO  = "https://www.googleapis.com/oauth2/v2/userinfo"
DRIVE_API = "https://www.googleapis.com/drive/v3"

# Doc-like MIME types we know how to extract text from.
TEXT_MIMES = {
    "text/plain", "text/markdown", "text/html",
    "application/vnd.google-apps.document",
}
INDEX_QUERY = (
    "trashed=false and ("
    "mimeType='application/vnd.google-apps.document' or "
    "mimeType='text/plain' or mimeType='text/markdown'"
    ")"
)


class _Drive:
    name   = "drive"
    label  = "Google Drive"
    scopes = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/userinfo.email",
        "openid",
    ]

    def is_configured(self) -> bool:
        s = get_settings()
        return bool(s.google_client_id and s.google_client_secret)

    def oauth_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        s = get_settings()
        params = {
            "client_id":     s.google_client_id,
            "redirect_uri":  redirect_uri,
            "response_type": "code",
            "scope":         " ".join(self.scopes),
            "access_type":   "offline",
            "prompt":        "consent",
            "state":         state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> dict:
        s = get_settings()
        token = await post_form(TOKEN_URL, {
            "code":          code,
            "client_id":     s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri":  redirect_uri,
            "grant_type":    "authorization_code",
        })
        # Fetch user info for the metadata block (account email shown in UI)
        info: dict = {}
        try:
            info = await get_json(USERINFO, headers={"Authorization": f"Bearer {token['access_token']}"})
        except Exception as e:
            logger.warning("drive userinfo failed: %s", e)
        return {
            "access_token":  token["access_token"],
            "refresh_token": token.get("refresh_token"),
            "expires_at":    expires_at_iso(token.get("expires_in")),
            "scope":         token.get("scope", ""),
            "metadata":      {"email": info.get("email", ""), "name": info.get("name", "")},
        }

    async def index(self, *, user_id: str, access_token: str, refresh_token: Optional[str], settings: dict) -> int:
        """Full or incremental index. `settings.get("sync_cursor")` is an ISO
        timestamp — when present, only files modified after that time are indexed.
        """
        update_index_status(user_id, self.name, status="indexing", indexed_count=0)
        headers = {"Authorization": f"Bearer {access_token}"}
        ingested = 0
        page_token: Optional[str] = None
        max_docs = 200
        sync_cursor = settings.get("sync_cursor")  # ISO timestamp or None (full)
        sync_start = datetime.now(timezone.utc).isoformat()
        # Build base query: full index or incremental delta
        base_q = INDEX_QUERY
        if sync_cursor:
            # Drive accepts RFC3339 timestamps in modifiedTime filter
            base_q = f"{base_q} and modifiedTime > '{sync_cursor}'"
            logger.info("drive incremental sync from cursor=%s for user=%s", sync_cursor, user_id)
        try:
            while ingested < max_docs:
                params = {
                    "q":         base_q,
                    "fields":    "nextPageToken, files(id,name,mimeType,modifiedTime,webViewLink)",
                    "pageSize":  50,
                    "orderBy":   "modifiedTime desc",
                }
                if page_token:
                    params["pageToken"] = page_token
                resp = await get_json(f"{DRIVE_API}/files", headers=headers, params=params)
                files = resp.get("files", [])
                if not files:
                    break
                for f in files:
                    if ingested >= max_docs:
                        break
                    text = await self._fetch_file_text(f, headers)
                    if not text:
                        continue
                    ingested += ingest_record(
                        user_id=user_id, provider=self.name, doc_id=f["id"],
                        title=f.get("name", "(untitled)"),
                        content=text,
                        url=f.get("webViewLink"),
                        extra_meta={"mime": f.get("mimeType", ""),
                                    "modified": f.get("modifiedTime", "")},
                    )
                    update_index_status(user_id, self.name, status="indexing", indexed_count=ingested)
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
            update_index_status(user_id, self.name, status="idle", indexed_count=ingested)
            # Persist cursor so next sync is incremental
            update_sync_cursor(user_id, self.name, sync_start)
        except Exception as e:
            logger.exception("drive index failed: %s", e)
            update_index_status(user_id, self.name, status="error", error=str(e)[:300])
        return ingested

    async def _fetch_file_text(self, f: dict, headers: dict) -> str:
        mime = f.get("mimeType", "")
        fid = f["id"]
        # Google Docs need export; plain text/markdown can be downloaded directly.
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                if mime == "application/vnd.google-apps.document":
                    r = await client.get(
                        f"{DRIVE_API}/files/{fid}/export",
                        headers=headers, params={"mimeType": "text/plain"},
                    )
                elif mime in TEXT_MIMES:
                    r = await client.get(
                        f"{DRIVE_API}/files/{fid}",
                        headers=headers, params={"alt": "media"},
                    )
                else:
                    return ""
                r.raise_for_status()
                return r.text[:10_000]
            except Exception as e:
                logger.warning("drive fetch text failed (%s): %s", fid, e)
                return ""

    async def fetch_relevant(
        self, *, user_id: str, query: str, k: int,
        access_token: str, refresh_token: Optional[str], settings: dict,
    ) -> list[FetchHit]:
        # Use Drive's full-text search live for active fetch — it's already
        # what the user expects when they ask about a doc.
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {
            "q":      f"fullText contains '{query.replace(chr(39), '')}' and trashed=false",
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
            "pageSize": str(max(k, 3)),
        }
        try:
            resp = await get_json(f"{DRIVE_API}/files", headers=headers, params=params, timeout=2.0)
        except Exception as e:
            logger.warning("drive fetch_relevant failed: %s", e)
            return []
        hits: list[FetchHit] = []
        for f in resp.get("files", [])[:k]:
            hits.append(FetchHit(
                id=f["id"],
                title=f.get("name", "(untitled)"),
                snippet=f"{f.get('mimeType','')} · modified {f.get('modifiedTime','')[:10]}",
                url=f.get("webViewLink"),
            ))
        return hits


drive_provider = _Drive()
