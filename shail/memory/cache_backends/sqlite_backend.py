"""SQLite cache backend (default for Phase 2).

Thread-safe via WAL mode. Stores serialised FusedHit lists keyed by
query hash with TTL support. No external dependencies beyond stdlib.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS retrieval_cache (
    query_hash  TEXT PRIMARY KEY,
    namespace   TEXT NOT NULL DEFAULT '',
    hits_json   TEXT NOT NULL,
    created_at  REAL NOT NULL,
    ttl_sec     INTEGER NOT NULL DEFAULT 3600
);
CREATE INDEX IF NOT EXISTS idx_rc_namespace ON retrieval_cache(namespace);
"""


class SQLiteCacheBackend:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(_CREATE_SQL)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=10,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def get(self, query_hash: str) -> Optional[List[Dict[str, Any]]]:
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT hits_json, created_at, ttl_sec FROM retrieval_cache WHERE query_hash = ?",
                (query_hash,),
            ).fetchone()
            if row is None:
                return None
            hits_json, created_at, ttl_sec = row
            if time.time() - created_at > ttl_sec:
                conn.execute("DELETE FROM retrieval_cache WHERE query_hash = ?", (query_hash,))
                conn.commit()
                return None
            return json.loads(hits_json)
        except Exception as exc:
            logger.debug("SQLiteCacheBackend.get failed: %s", exc)
            return None

    def set(self, query_hash: str, namespace: str, hits: List[Dict[str, Any]], ttl_sec: int) -> None:
        try:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO retrieval_cache
                   (query_hash, namespace, hits_json, created_at, ttl_sec)
                   VALUES (?, ?, ?, ?, ?)""",
                (query_hash, namespace or "", json.dumps(hits), time.time(), ttl_sec),
            )
            conn.commit()
        except Exception as exc:
            logger.debug("SQLiteCacheBackend.set failed: %s", exc)

    def invalidate_namespace(self, namespace: str) -> int:
        try:
            conn = self._get_conn()
            cur = conn.execute(
                "DELETE FROM retrieval_cache WHERE namespace = ?", (namespace,)
            )
            conn.commit()
            return cur.rowcount
        except Exception as exc:
            logger.debug("SQLiteCacheBackend.invalidate failed: %s", exc)
            return 0

    def purge_expired(self) -> int:
        try:
            conn = self._get_conn()
            cur = conn.execute(
                "DELETE FROM retrieval_cache WHERE (? - created_at) > ttl_sec",
                (time.time(),),
            )
            conn.commit()
            return cur.rowcount
        except Exception as exc:
            logger.debug("SQLiteCacheBackend.purge_expired failed: %s", exc)
            return 0

    def size_bytes(self) -> int:
        try:
            return self._db_path.stat().st_size
        except Exception:
            return 0
