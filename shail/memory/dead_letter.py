"""Dead-letter queue for failed memory ingests (Sprint 2).

Behavior:
  - Failed ingest events never disappear silently
  - Each failure is persisted with full payload + error + attempt count
  - Quarantine threshold: after MAX_ATTEMPTS, status flips to "quarantined"
  - Replay API for operators

SQLite-backed. Single-writer; safe under FastAPI single-worker.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


MAX_ATTEMPTS = 3   # quarantine after this many failures

STATUS_PENDING     = "pending"
STATUS_RECOVERED   = "recovered"
STATUS_QUARANTINED = "quarantined"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS dead_letters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash    TEXT NOT NULL,
    content         TEXT NOT NULL,
    metadata_json   TEXT NOT NULL,
    namespace       TEXT,
    error_msg       TEXT NOT NULL,
    attempt_count   INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'pending',
    first_seen_at   REAL NOT NULL,
    last_attempt_at REAL NOT NULL,
    quarantined_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_dl_hash    ON dead_letters(content_hash);
CREATE INDEX IF NOT EXISTS idx_dl_status  ON dead_letters(status);
"""


class DeadLetterQueue:
    """Persistent quarantine for failed ingests."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        from apps.shail.settings import get_settings
        s = get_settings()
        path = db_path or getattr(s, "dead_letter_db",
                                   "~/Library/Application Support/SHAIL/dead_letter.db")
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._path), check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    # ------------------------------------------------------------------ #
    # Public API                                                            #
    # ------------------------------------------------------------------ #

    def record(
        self,
        content: str,
        metadata: Dict[str, Any],
        error_msg: str,
        namespace: Optional[str] = None,
    ) -> int:
        """Record a failed ingest. Returns dead-letter row id.

        If content_hash already exists with status=pending, increments
        attempt_count instead of creating a duplicate row. If attempt_count
        reaches MAX_ATTEMPTS, status flips to quarantined.
        """
        import hashlib
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        now = time.time()
        meta_json = json.dumps(metadata or {}, default=str)

        with self._lock, self._conn() as c:
            row = c.execute(
                """SELECT id, attempt_count, status FROM dead_letters
                   WHERE content_hash=? AND status=?""",
                (h, STATUS_PENDING),
            ).fetchone()
            if row:
                row_id, attempts, _ = row
                new_attempts = attempts + 1
                new_status = STATUS_QUARANTINED if new_attempts >= MAX_ATTEMPTS else STATUS_PENDING
                c.execute(
                    """UPDATE dead_letters
                       SET attempt_count=?, last_attempt_at=?, error_msg=?,
                           status=?,
                           quarantined_at=CASE WHEN ?='quarantined' THEN ? ELSE quarantined_at END
                       WHERE id=?""",
                    (new_attempts, now, error_msg, new_status, new_status, now, row_id),
                )
                _emit("dead_letter", status="retry")
                if new_status == STATUS_QUARANTINED:
                    _emit("dead_letter", status="quarantined")
                return row_id
            cur = c.execute(
                """INSERT INTO dead_letters
                   (content_hash, content, metadata_json, namespace, error_msg,
                    attempt_count, status, first_seen_at, last_attempt_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (h, content, meta_json, namespace, error_msg,
                 STATUS_PENDING, now, now),
            )
            _emit("dead_letter", status="created")
            return int(cur.lastrowid)

    def mark_recovered(self, row_id: int) -> None:
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE dead_letters SET status=?, last_attempt_at=? WHERE id=?",
                (STATUS_RECOVERED, now, row_id),
            )
        _emit("dead_letter", status="recovered")

    def list_pending(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT id, content_hash, content, metadata_json, namespace,
                          error_msg, attempt_count, status, first_seen_at,
                          last_attempt_at, quarantined_at
                   FROM dead_letters
                   WHERE status=? ORDER BY first_seen_at ASC LIMIT ?""",
                (STATUS_PENDING, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def list_quarantined(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT id, content_hash, content, metadata_json, namespace,
                          error_msg, attempt_count, status, first_seen_at,
                          last_attempt_at, quarantined_at
                   FROM dead_letters
                   WHERE status=? ORDER BY quarantined_at DESC LIMIT ?""",
                (STATUS_QUARANTINED, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def stats(self) -> Dict[str, int]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) FROM dead_letters GROUP BY status",
            ).fetchall()
        return {status: count for status, count in rows}

    def purge_recovered(self, older_than_sec: float = 86400 * 7) -> int:
        cutoff = time.time() - older_than_sec
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM dead_letters WHERE status=? AND last_attempt_at < ?",
                (STATUS_RECOVERED, cutoff),
            )
            return cur.rowcount


def _row_to_dict(row) -> Dict[str, Any]:
    keys = ("id", "content_hash", "content", "metadata_json", "namespace",
            "error_msg", "attempt_count", "status", "first_seen_at",
            "last_attempt_at", "quarantined_at")
    out = dict(zip(keys, row))
    try:
        out["metadata"] = json.loads(out.pop("metadata_json") or "{}")
    except Exception:
        out["metadata"] = {}
    return out


def _emit(name: str, **labels) -> None:
    try:
        from apps.shail import telemetry
        telemetry.incr(name, **labels)
    except Exception:
        pass


# ── Singleton ──────────────────────────────────────────────────────────── #

_dlq: Optional[DeadLetterQueue] = None
_dlq_lock = threading.Lock()


def get_dead_letter_queue() -> DeadLetterQueue:
    global _dlq
    if _dlq is None:
        with _dlq_lock:
            if _dlq is None:
                _dlq = DeadLetterQueue()
    return _dlq


def reset_for_tests() -> None:
    global _dlq
    with _dlq_lock:
        _dlq = None
