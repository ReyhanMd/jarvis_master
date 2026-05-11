"""Cross-agent shared context store (Phase 5).

Per-task namespace, isolated, replay-safe.
Backend: SQLite (default) or Redis (if configured).
TTL-aware — entries expire after shared_context_ttl_hours.

Usage:
    from shail.memory.shared_context import get_shared_context
    store = get_shared_context()
    await store.write("task-123", "code", "plan", {"steps": [...]})
    plan = await store.read("task-123", "code", "plan")
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── SQLite backend ─────────────────────────────────────────────────────── #

class _SQLiteContextBackend:
    """Sync SQLite backend; callers wrap in asyncio.to_thread."""

    def __init__(self, db_path: str, ttl_hours: int) -> None:
        self._path = Path(db_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ttl_sec = ttl_hours * 3600
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._path), check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS shared_context (
                    context_id TEXT NOT NULL,
                    namespace  TEXT NOT NULL,
                    key        TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    ttl_sec    REAL NOT NULL,
                    PRIMARY KEY (context_id, namespace, key)
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_sc_ctx ON shared_context (context_id)")

    def write(self, context_id: str, namespace: str, key: str, value: Any) -> None:
        now = time.time()
        val_json = json.dumps(value, default=str)
        with self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO shared_context
                   (context_id, namespace, key, value_json, created_at, ttl_sec)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (context_id, namespace, key, val_json, now, self._ttl_sec),
            )

    def read(self, context_id: str, namespace: str, key: str) -> Optional[Any]:
        with self._conn() as c:
            row = c.execute(
                "SELECT value_json, created_at, ttl_sec FROM shared_context "
                "WHERE context_id=? AND namespace=? AND key=?",
                (context_id, namespace, key),
            ).fetchone()
        if row is None:
            return None
        val_json, created_at, ttl_sec = row
        if time.time() - created_at > ttl_sec:
            self.clear_key(context_id, namespace, key)
            return None
        return json.loads(val_json)

    def list_keys(self, context_id: str, namespace: str) -> List[str]:
        now = time.time()
        with self._conn() as c:
            rows = c.execute(
                "SELECT key FROM shared_context WHERE context_id=? AND namespace=? "
                "AND (? - created_at) <= ttl_sec",
                (context_id, namespace, now),
            ).fetchall()
        return [r[0] for r in rows]

    def clear(self, context_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM shared_context WHERE context_id=?", (context_id,))

    def clear_key(self, context_id: str, namespace: str, key: str) -> None:
        with self._conn() as c:
            c.execute(
                "DELETE FROM shared_context WHERE context_id=? AND namespace=? AND key=?",
                (context_id, namespace, key),
            )

    def purge_expired(self) -> int:
        now = time.time()
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM shared_context WHERE (? - created_at) > ttl_sec", (now,)
            )
            return cur.rowcount


# ── Redis backend ──────────────────────────────────────────────────────── #

class _RedisContextBackend:
    """Fully async Redis backend."""

    def __init__(self, redis_url: str, ttl_hours: int, prefix: str = "shail:ctx:") -> None:
        self._url = redis_url
        self._ttl_sec = ttl_hours * 3600
        self._prefix = prefix
        self._client = None

    def _key(self, context_id: str, namespace: str, key: str) -> str:
        return f"{self._prefix}{context_id}:{namespace}:{key}"

    def _index_key(self, context_id: str, namespace: str) -> str:
        return f"{self._prefix}idx:{context_id}:{namespace}"

    async def _get_client(self):
        if self._client is None:
            import redis.asyncio as aioredis
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    async def write(self, context_id: str, namespace: str, key: str, value: Any) -> None:
        c = await self._get_client()
        k = self._key(context_id, namespace, key)
        await c.setex(k, self._ttl_sec, json.dumps(value, default=str))
        await c.sadd(self._index_key(context_id, namespace), key)
        await c.expire(self._index_key(context_id, namespace), self._ttl_sec)

    async def read(self, context_id: str, namespace: str, key: str) -> Optional[Any]:
        c = await self._get_client()
        val = await c.get(self._key(context_id, namespace, key))
        return json.loads(val) if val else None

    async def list_keys(self, context_id: str, namespace: str) -> List[str]:
        c = await self._get_client()
        return list(await c.smembers(self._index_key(context_id, namespace)))

    async def clear(self, context_id: str) -> None:
        c = await self._get_client()
        keys = await c.keys(f"{self._prefix}{context_id}:*")
        if keys:
            await c.delete(*keys)


# ── Public facade ──────────────────────────────────────────────────────── #

class SharedContextStore:
    """Async facade over SQLite or Redis backend."""

    def __init__(self) -> None:
        from apps.shail.settings import get_settings
        s = get_settings()
        self._enabled = s.enable_shared_context
        self._ttl = s.shared_context_ttl_hours
        if s.shared_context_backend == "redis" and s.redis_url:
            try:
                self._backend = _RedisContextBackend(s.redis_url, self._ttl)
                self._async = True
                return
            except Exception as exc:
                logger.warning("SharedContext: Redis init failed (%s) — falling back to SQLite", exc)
        db_path = getattr(s, "shared_context_sqlite_path",
                          "~/Library/Application Support/SHAIL/shared_context.db")
        self._backend = _SQLiteContextBackend(db_path, self._ttl)
        self._async = False

    async def write(self, context_id: str, namespace: str, key: str, value: Any) -> None:
        if not self._enabled:
            return
        try:
            if self._async:
                await self._backend.write(context_id, namespace, key, value)
            else:
                await asyncio.to_thread(self._backend.write, context_id, namespace, key, value)
        except Exception as exc:
            logger.debug("SharedContextStore.write error: %s", exc)

    async def read(self, context_id: str, namespace: str, key: str) -> Optional[Any]:
        if not self._enabled:
            return None
        try:
            if self._async:
                return await self._backend.read(context_id, namespace, key)
            return await asyncio.to_thread(self._backend.read, context_id, namespace, key)
        except Exception as exc:
            logger.debug("SharedContextStore.read error: %s", exc)
            return None

    async def list_keys(self, context_id: str, namespace: str) -> List[str]:
        if not self._enabled:
            return []
        try:
            if self._async:
                return await self._backend.list_keys(context_id, namespace)
            return await asyncio.to_thread(self._backend.list_keys, context_id, namespace)
        except Exception as exc:
            logger.debug("SharedContextStore.list_keys error: %s", exc)
            return []

    async def clear(self, context_id: str) -> None:
        if not self._enabled:
            return
        try:
            if self._async:
                await self._backend.clear(context_id)
            else:
                await asyncio.to_thread(self._backend.clear, context_id)
        except Exception as exc:
            logger.debug("SharedContextStore.clear error: %s", exc)


# ── Singleton ──────────────────────────────────────────────────────────── #

_store: Optional[SharedContextStore] = None


def get_shared_context() -> SharedContextStore:
    global _store
    if _store is None:
        _store = SharedContextStore()
    return _store
