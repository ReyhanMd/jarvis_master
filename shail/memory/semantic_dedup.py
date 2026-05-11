"""Semantic dedup (Sprint 2).

Pre-ingest filter: rejects content whose embedding is too similar to a
recently-seen embedding in the same namespace.

Design:
  - Per-namespace rolling window of (text_hash, embedding) tuples.
  - Window size + similarity threshold configurable.
  - SQLite persistence for cross-restart durability.
  - In-memory cache for hot path (last N per namespace).
  - O(N·dim) cosine compare per ingest where N = window size (default 256).
    Tunable down to 64 for high-throughput deployments.

Public API:
    is_duplicate(content, namespace, embedding) -> Tuple[bool, float, Optional[str]]
        returns (duplicate?, max_similarity, matched_hash)

    record(content_hash, namespace, embedding) -> None
        add to window after successful ingest

Telemetry hooks via apps.shail.telemetry.
"""
from __future__ import annotations

import hashlib
import logging
import math
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


DEFAULT_WINDOW_SIZE = 256
DEFAULT_THRESHOLD   = 0.95


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na  += x * x
        nb  += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


# Vectorised cosine — used when numpy is available
def _cosine_batch(query: List[float], candidates: List[List[float]]) -> List[float]:
    try:
        import numpy as _np
        q = _np.asarray(query, dtype=_np.float32)
        c = _np.asarray(candidates, dtype=_np.float32)
        q_norm = _np.linalg.norm(q)
        c_norms = _np.linalg.norm(c, axis=1)
        denom = q_norm * c_norms
        # Avoid division by zero
        denom[denom == 0.0] = 1.0
        sims = (c @ q) / denom
        return sims.tolist()
    except ImportError:
        return [_cosine(query, cand) for cand in candidates]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── SQLite backend ─────────────────────────────────────────────────────── #

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dedup_window (
    namespace   TEXT NOT NULL,
    text_hash   TEXT NOT NULL,
    embedding   BLOB NOT NULL,
    created_at  REAL NOT NULL,
    PRIMARY KEY (namespace, text_hash)
);
CREATE INDEX IF NOT EXISTS idx_dedup_ns ON dedup_window(namespace, created_at DESC);
"""


class _SQLiteDedupBackend:
    """Persistent dedup window in SQLite, per namespace."""

    def __init__(self, db_path: str, window_size: int) -> None:
        self._path = Path(db_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._window_size = window_size
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._path), check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    @staticmethod
    def _enc(emb: List[float]) -> bytes:
        try:
            import numpy as _np
            return _np.asarray(emb, dtype=_np.float32).tobytes()
        except ImportError:
            import struct
            return struct.pack(f"{len(emb)}f", *emb)

    @staticmethod
    def _dec(blob: bytes) -> List[float]:
        try:
            import numpy as _np
            return _np.frombuffer(blob, dtype=_np.float32).tolist()
        except ImportError:
            import struct
            cnt = len(blob) // 4
            return list(struct.unpack(f"{cnt}f", blob))

    def recent(self, namespace: str) -> List[Tuple[str, List[float]]]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT text_hash, embedding FROM dedup_window
                   WHERE namespace=? ORDER BY created_at DESC LIMIT ?""",
                (namespace, self._window_size),
            ).fetchall()
        return [(h, self._dec(b)) for h, b in rows]

    def add(self, namespace: str, text_hash: str, embedding: List[float]) -> None:
        blob = self._enc(embedding)
        now = time.time()
        with self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO dedup_window
                   (namespace, text_hash, embedding, created_at)
                   VALUES (?, ?, ?, ?)""",
                (namespace, text_hash, blob, now),
            )
            # Trim window
            c.execute(
                """DELETE FROM dedup_window WHERE namespace=? AND text_hash NOT IN (
                       SELECT text_hash FROM dedup_window WHERE namespace=?
                       ORDER BY created_at DESC LIMIT ?
                   )""",
                (namespace, namespace, self._window_size),
            )


# ── Public facade ──────────────────────────────────────────────────────── #

class SemanticDedup:
    """Per-namespace semantic dedup with in-memory cache + SQLite persistence."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        window_size: int = DEFAULT_WINDOW_SIZE,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        from apps.shail.settings import get_settings
        s = get_settings()
        path = db_path or getattr(s, "semantic_dedup_db",
                                   "~/Library/Application Support/SHAIL/dedup.db")
        self._backend = _SQLiteDedupBackend(path, window_size)
        self._threshold = threshold
        self._cache: Dict[str, Deque[Tuple[str, List[float]]]] = {}
        self._lock = threading.Lock()
        self._window_size = window_size

    def _get_window(self, namespace: str) -> Deque[Tuple[str, List[float]]]:
        with self._lock:
            if namespace not in self._cache:
                items = self._backend.recent(namespace)
                self._cache[namespace] = deque(items, maxlen=self._window_size)
            return self._cache[namespace]

    def is_duplicate(
        self,
        content: str,
        namespace: str,
        embedding: List[float],
    ) -> Tuple[bool, float, Optional[str]]:
        """Return (is_dup, max_sim, matched_hash).

        Hash dedup happens first (exact match). Then semantic against window.
        """
        if not embedding:
            return (False, 0.0, None)
        h = content_hash(content)
        window = self._get_window(namespace)

        # Exact hash check
        for existing_h, _ in window:
            if existing_h == h:
                return (True, 1.0, existing_h)

        # Semantic check (vectorised)
        if not window:
            return (False, 0.0, None)
        hashes = [h_e for h_e, _ in window]
        embs   = [e for _, e in window]
        sims   = _cosine_batch(embedding, embs)
        if not sims:
            return (False, 0.0, None)
        max_idx = max(range(len(sims)), key=lambda i: sims[i])
        max_sim = sims[max_idx]
        if max_sim >= self._threshold:
            return (True, float(max_sim), hashes[max_idx])
        return (False, float(max_sim), None)

    def record(self, content: str, namespace: str, embedding: List[float]) -> None:
        """Add to window after ingest succeeds."""
        if not embedding:
            return
        h = content_hash(content)
        window = self._get_window(namespace)
        with self._lock:
            window.append((h, embedding))
        try:
            self._backend.add(namespace, h, embedding)
        except Exception as exc:
            logger.debug("SemanticDedup.record persistence failed: %s", exc)


# ── Singleton ──────────────────────────────────────────────────────────── #

_dedup: Optional[SemanticDedup] = None
_dedup_lock = threading.Lock()


def get_semantic_dedup() -> SemanticDedup:
    global _dedup
    if _dedup is None:
        with _dedup_lock:
            if _dedup is None:
                from apps.shail.settings import get_settings
                s = get_settings()
                _dedup = SemanticDedup(
                    window_size=getattr(s, "semantic_dedup_window", DEFAULT_WINDOW_SIZE),
                    threshold=getattr(s, "semantic_dedup_threshold", DEFAULT_THRESHOLD),
                )
    return _dedup


def reset_for_tests() -> None:
    global _dedup
    with _dedup_lock:
        _dedup = None
