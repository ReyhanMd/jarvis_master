"""GitHub connector — owner repos only in v1."""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlencode

from apps.shail.mcp.base import FetchHit, MCPProvider
from apps.shail.mcp._oauth import get_json, ingest_record, post_form
from apps.shail.mcp_store import update_index_status, update_sync_cursor
from apps.shail.settings import get_settings

logger = logging.getLogger(__name__)

AUTH_URL  = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API       = "https://api.github.com"


class _GitHub:
    name   = "github"
    label  = "GitHub"
    scopes = ["read:user", "repo"]   # repo grants private-repo read; user can revoke

    def is_configured(self) -> bool:
        s = get_settings()
        return bool(s.github_client_id and s.github_client_secret)

    def oauth_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        s = get_settings()
        params = {
            "client_id":    s.github_client_id,
            "redirect_uri": redirect_uri,
            "scope":        " ".join(self.scopes),
            "state":        state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> dict:
        s = get_settings()
        token = await post_form(
            TOKEN_URL,
            {
                "code":          code,
                "client_id":     s.github_client_id,
                "client_secret": s.github_client_secret,
                "redirect_uri":  redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        # GitHub doesn't return expires_in for normal OAuth tokens
        info: dict = {}
        try:
            info = await get_json(
                f"{API}/user",
                headers={"Authorization": f"Bearer {token['access_token']}",
                         "Accept": "application/vnd.github+json"},
            )
        except Exception as e:
            logger.warning("github userinfo failed: %s", e)
        return {
            "access_token":  token["access_token"],
            "refresh_token": token.get("refresh_token"),
            "expires_at":    None,
            "scope":         token.get("scope", ""),
            "metadata":      {"login": info.get("login", ""), "name": info.get("name", "")},
        }

    async def index(self, *, user_id: str, access_token: str, refresh_token: Optional[str], settings: dict) -> int:
        """Index README + repo metadata for owner repos.

        Incremental sync: if `settings.sync_cursor` is set (ISO timestamp),
        only repos pushed after that time are re-indexed. v1 cap: 50 repos.
        """
        from datetime import datetime, timezone
        update_index_status(user_id, self.name, status="indexing", indexed_count=0)
        headers = self._headers(access_token)
        ingested = 0
        sync_cursor = settings.get("sync_cursor")
        sync_start = datetime.now(timezone.utc).isoformat()
        try:
            repos = await get_json(
                f"{API}/user/repos",
                headers=headers,
                params={"per_page": "100", "type": "owner", "sort": "updated"},
            )
            if not isinstance(repos, list):
                repos = []
            # Incremental: skip repos with pushed_at <= cursor
            if sync_cursor:
                repos = [r for r in repos if (r.get("pushed_at") or "") > sync_cursor]
                logger.info("github incremental: %d repos changed since %s", len(repos), sync_cursor)
            for r in repos[:50]:
                full = r.get("full_name", "")
                desc = r.get("description") or ""
                readme_text = ""
                try:
                    readme = await get_json(f"{API}/repos/{full}/readme", headers=headers)
                    import base64
                    if readme.get("content"):
                        readme_text = base64.b64decode(readme["content"]).decode("utf-8", errors="ignore")[:8000]
                except Exception:
                    pass  # repos without README are fine
                content = (
                    f"Repository: {full}\n"
                    f"Description: {desc}\n"
                    f"Stars: {r.get('stargazers_count', 0)} · Language: {r.get('language', '')}\n\n"
                    f"{readme_text}"
                )
                ingested += ingest_record(
                    user_id=user_id, provider=self.name, doc_id=full,
                    title=full, content=content,
                    url=r.get("html_url"),
                    extra_meta={
                        "language":   r.get("language", ""),
                        "stars":      r.get("stargazers_count", 0),
                        "is_private": r.get("private", False),
                    },
                )
                update_index_status(user_id, self.name, status="indexing", indexed_count=ingested)
            update_index_status(user_id, self.name, status="idle", indexed_count=ingested)
            update_sync_cursor(user_id, self.name, sync_start)
        except Exception as e:
            logger.exception("github index failed: %s", e)
            update_index_status(user_id, self.name, status="error", error=str(e)[:300])
        return ingested

    async def fetch_relevant(
        self, *, user_id: str, query: str, k: int,
        access_token: str, refresh_token: Optional[str], settings: dict,
    ) -> list[FetchHit]:
        headers = self._headers(access_token)
        # Search across owner-scoped issues + code. Cap each at k/2 to stay snappy.
        login = settings.get("login") or ""
        hits: list[FetchHit] = []
        try:
            # Issues / PRs
            issues = await get_json(
                f"{API}/search/issues",
                headers=headers,
                params={"q": f"{query} user:{login}" if login else query, "per_page": str(k)},
                timeout=2.0,
            )
            for it in (issues.get("items") or [])[:k]:
                hits.append(FetchHit(
                    id=str(it.get("id")),
                    title=it.get("title", ""),
                    snippet=(it.get("body") or "")[:200],
                    url=it.get("html_url"),
                ))
        except Exception as e:
            logger.warning("github issue search failed: %s", e)
        return hits[:k]

    @staticmethod
    def _headers(token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept":        "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }


github_provider = _GitHub()
