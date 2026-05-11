"""Shared RAG retrieval cache (SuperMemory Phase 2).

Hash-keyed, TTL-aware cache for hybrid_search results.
Backend priority: Redis → SQLite → Disk (configurable via settings).

Usage in hybrid.py:
    from shail.memory.cache import get_retrieval_cache
    cache = get_retrieval_cache()
    hits = await cache.get(query, namespace, k)
    if hits is None:
        hits = ... # run retrieval
        await cache.set(query, namespace, k, hits)
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Legacy SemanticHit shape: (content, score, metadata)
SemanticHit = Tuple[str, float, dict]


def _hits_to_json(hits: List[SemanticHit]) -> List[Dict[str, Any]]:
    return [{"content": c, "score": s, "metadata": m} for c, s, m in hits]


def _json_to_hits(records: List[Dict[str, Any]]) -> List[SemanticHit]:
    return [(r["content"], float(r["score"]), r.get("metadata") or {}) for r in records]


class RetrievalCache:
    """Unified cache abstraction over Redis / SQLite / Disk backends.

    All public methods are async-safe. The SQLite and Disk backends wrap
    sync I/O in asyncio.to_thread internally so the event loop is never blocked.
    """

    def __init__(self) -> None:
        from apps.shail.settings import get_settings
        s = self._settings = get_settings()
        self._ttl     = s.cache_ttl_sec
        self._enabled = s.cache_enabled
        self._backend_type = s.cache_backend
        self._backend = self._build_backend()

    def _build_backend(self):
        s = self._settings
        if self._backend_type == "redis":
            try:
                from shail.memory.cache_backends.redis_backend import RedisCacheBackend
                return RedisCacheBackend(s.redis_url)
            except Exception as exc:
                logger.warning("Redis cache backend init failed (%s) — falling back to SQLite", exc)
        if self._backend_type in ("redis", "sqlite"):
            from shail.memory.cache_backends.sqlite_backend import SQLiteCacheBackend
            return SQLiteCacheBackend(s.cache_sqlite_path)
        # disk fallback
        from shail.memory.cache_backends.disk_backend import DiskCacheBackend
        return DiskCacheBackend(s.cache_disk_dir)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def hash_query(self, query: str, namespace: str, k: int) -> str:
        """Stable SHA-256 hash used as cache key."""
        raw = f"{query.strip()}|{namespace or ''}|{k}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def get(
        self, query: str, namespace: Optional[str], k: int
    ) -> Optional[List[SemanticHit]]:
        if not self._enabled:
            return None
        qhash = self.hash_query(query, namespace or "", k)
        try:
            import asyncio
            backend = self._backend
            # Redis backend is already async; SQLite/Disk are sync → thread
            if hasattr(backend, "get") and asyncio.iscoroutinefunction(backend.get):
                raw = await backend.get(qhash)
            else:
                raw = await asyncio.to_thread(backend.get, qhash)
            if raw is None:
                return None
            return _json_to_hits(raw)
        except Exception as exc:
            logger.debug("RetrievalCache.get error: %s", exc)
            return None

    async def set(
        self,
        query: str,
        namespace: Optional[str],
        k: int,
        hits: List[SemanticHit],
        ttl: Optional[int] = None,
    ) -> None:
        if not self._enabled or not hits:
            return
        qhash = self.hash_query(query, namespace or "", k)
        records = _hits_to_json(hits)
        ttl_sec = ttl if ttl is not None else self._ttl
        try:
            import asyncio
            backend = self._backend
            ns = namespace or ""
            if asyncio.iscoroutinefunction(backend.set):
                await backend.set(qhash, ns, records, ttl_sec)
            else:
                await asyncio.to_thread(backend.set, qhash, ns, records, ttl_sec)
        except Exception as exc:
            logger.debug("RetrievalCache.set error: %s", exc)

    async def invalidate(self, namespace: str) -> int:
        """Invalidate all cached results for a namespace."""
        if not self._enabled:
            return 0
        try:
            import asyncio
            backend = self._backend
            if asyncio.iscoroutinefunction(getattr(backend, "invalidate_namespace", None)):
                return await backend.invalidate_namespace(namespace)
            return await asyncio.to_thread(backend.invalidate_namespace, namespace)
        except Exception as exc:
            logger.debug("RetrievalCache.invalidate error: %s", exc)
            return 0

    def size_bytes(self) -> int:
        try:
            return self._backend.size_bytes()
        except Exception:
            return 0


# Module-level singleton
_cache: Optional[RetrievalCache] = None


def get_retrieval_cache() -> RetrievalCache:
    global _cache
    if _cache is None:
        _cache = RetrievalCache()
    return _cache
