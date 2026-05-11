"""Redis cache backend (Phase 2 — optional, requires redis>=5.0).

Falls back gracefully if redis is unreachable.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


class RedisCacheBackend:
    def __init__(self, redis_url: str, key_prefix: str = "shail:cache:") -> None:
        self._url    = redis_url
        self._prefix = key_prefix
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        if not _REDIS_AVAILABLE:
            raise RuntimeError("redis package not installed. Run: pip install redis")
        if self._client is None:
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    def _key(self, query_hash: str) -> str:
        return f"{self._prefix}{query_hash}"

    async def get(self, query_hash: str) -> Optional[List[Dict[str, Any]]]:
        if not _REDIS_AVAILABLE:
            return None
        try:
            client = self._get_client()
            val = await client.get(self._key(query_hash))
            if val is None:
                return None
            return json.loads(val)
        except Exception as exc:
            logger.debug("RedisCacheBackend.get failed: %s", exc)
            return None

    async def set(self, query_hash: str, namespace: str, hits: List[Dict[str, Any]], ttl_sec: int) -> None:
        if not _REDIS_AVAILABLE:
            return
        try:
            client = self._get_client()
            payload = json.dumps({"hits": hits, "ns": namespace})
            await client.setex(self._key(query_hash), ttl_sec, payload)
        except Exception as exc:
            logger.debug("RedisCacheBackend.set failed: %s", exc)

    async def invalidate_namespace(self, namespace: str) -> int:
        if not _REDIS_AVAILABLE:
            return 0
        try:
            client = self._get_client()
            keys = await client.keys(f"{self._prefix}*")
            count = 0
            for k in keys:
                val = await client.get(k)
                if val:
                    data = json.loads(val)
                    if data.get("ns") == namespace:
                        await client.delete(k)
                        count += 1
            return count
        except Exception as exc:
            logger.debug("RedisCacheBackend.invalidate failed: %s", exc)
            return 0

    async def size_bytes(self) -> int:
        if not _REDIS_AVAILABLE:
            return 0
        try:
            client = self._get_client()
            info = await client.info("memory")
            return int(info.get("used_memory", 0))
        except Exception:
            return 0
