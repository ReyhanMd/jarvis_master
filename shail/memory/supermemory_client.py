"""SuperMemory REST adapter (SuperMemory Phase 1).

Thin async HTTP wrapper around the SuperMemory v3/v4 API.
SHAIL uses this to fall back to global memory when local retrieval
returns fewer hits than the configured threshold.

Design rules:
- No tight coupling to SHAIL runtime. Import only stdlib + httpx + settings.
- All methods fail silently (log + return []) so caller is never disrupted.
- Feature flag checked by CALLER (hybrid.py), not here.
- Timeout is respected; never blocks the retrieval path.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False
    logger.warning("httpx not installed — SupermemoryClient will no-op. Run: pip install httpx")

from shail.memory.retrieval_strategy import GlobalHit


class SupermemoryClient:
    """Async REST client for SuperMemory API.

    Usage (injected into hybrid_search):
        client = SupermemoryClient()
        hits = await client.query_global(query="...", k=5, namespace="default")
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 5.0,
    ) -> None:
        from apps.shail.settings import get_settings
        s = get_settings()
        self._api_url  = (api_url  or s.supermemory_api_url).rstrip("/")
        self._api_key  = api_key  or s.supermemory_api_key
        self._timeout  = timeout  or s.supermemory_timeout_sec
        self._headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            self._headers["Authorization"] = f"Bearer {self._api_key}"

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def query_global(
        self,
        query: str,
        *,
        k: int = 5,
        namespace: Optional[str] = None,
        threshold: float = 0.0,
    ) -> List[GlobalHit]:
        """Search SuperMemory global store. Returns [] on any failure."""
        if not _HTTPX_AVAILABLE:
            return []
        if not query or not query.strip():
            return []

        payload: Dict[str, Any] = {
            "q":     query.strip(),
            "limit": k,
        }
        if threshold > 0:
            payload["threshold"] = threshold
        if namespace:
            payload["containerTag"] = namespace

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._api_url}/v4/search",
                    json=payload,
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            logger.warning("SupermemoryClient: query_global timeout (%.1fs) for q=%r", self._timeout, query[:60])
            return []
        except Exception as exc:
            logger.warning("SupermemoryClient: query_global failed: %s", exc)
            return []

        return self._parse_v4_results(data.get("results", []))

    async def ingest_global(
        self,
        content: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        container_tags: Optional[List[str]] = None,
        custom_id: Optional[str] = None,
    ) -> Optional[str]:
        """Ingest content into SuperMemory global store.

        Returns the document ID on success, None on failure.
        """
        if not _HTTPX_AVAILABLE:
            return None
        if not content or not content.strip():
            return None

        payload: Dict[str, Any] = {"content": content.strip()}
        if container_tags:
            payload["containerTags"] = container_tags
        if metadata:
            # SuperMemory metadata values must be str/int/bool
            payload["metadata"] = {
                k: v for k, v in metadata.items()
                if isinstance(v, (str, int, float, bool))
            }
        if custom_id:
            payload["customId"] = custom_id
        else:
            # Deterministic ID from content hash so re-ingestion is idempotent
            payload["customId"] = "shail-" + hashlib.sha256(content.encode()).hexdigest()[:16]

        try:
            async with httpx.AsyncClient(timeout=self._timeout * 2) as client:
                resp = await client.post(
                    f"{self._api_url}/v3/documents",
                    json=payload,
                    headers=self._headers,
                )
                resp.raise_for_status()
                return resp.json().get("id")
        except Exception as exc:
            logger.warning("SupermemoryClient: ingest_global failed: %s", exc)
            return None

    async def health_check(self) -> bool:
        """Return True if SuperMemory API is reachable."""
        if not _HTTPX_AVAILABLE:
            return False
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(
                    f"{self._api_url}/health",
                    headers=self._headers,
                )
                return resp.status_code < 500
        except Exception:
            return False

    async def get_stats(self) -> Dict[str, Any]:
        """Return analytics/usage stats from SuperMemory."""
        if not _HTTPX_AVAILABLE:
            return {}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._api_url}/v3/analytics/usage",
                    headers=self._headers,
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("SupermemoryClient: get_stats failed: %s", exc)
            return {}

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _parse_v4_results(self, results: List[Dict[str, Any]]) -> List[GlobalHit]:
        hits: List[GlobalHit] = []
        for r in results:
            memory_id = r.get("id", "")
            content   = r.get("memory", "") or r.get("content", "")
            score     = float(r.get("similarity", 0.0))
            version   = r.get("version")
            meta      = dict(r.get("metadata") or {})
            meta["title"] = r.get("title", "")
            meta["updated_at"] = r.get("updatedAt", "")
            if not content or not memory_id:
                continue
            hits.append(GlobalHit(
                memory_id=memory_id,
                content=content,
                score=score,
                metadata=meta,
                version=version,
            ))
        return hits


# Module-level singleton — lazy-initialised on first call.
_client: Optional[SupermemoryClient] = None


def get_supermemory_client() -> SupermemoryClient:
    global _client
    if _client is None:
        _client = SupermemoryClient()
    return _client
