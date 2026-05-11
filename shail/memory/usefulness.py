"""Retrieval usefulness feedback loop (Sprint 2).

Goal: after a task completes, evaluate which retrieved memories actually
helped. Persist per-memory usefulness scores. Future retrievals consult
the score to rerank.

Pipeline:
  1. `record_retrieval(task_id, memories)` — called by hybrid_search after
     it produces results. Stashes the retrieved set for later evaluation.
  2. `evaluate_task(task_id, result_summary, success)` — called by router
     after task completes. Computes a usefulness score for each retrieved
     memory based on cheap heuristics (NO LLM calls by default):
       * lexical overlap between memory content and result summary
       * task success bonus
       * retry penalty (if task retried)
  3. `get_usefulness(memory_id)` — returns running mean + sample count
     for a memory id (used by retrieval reranking).
  4. `apply_usefulness_boost(hits)` — rerank hook called by fusion.

Storage: SQLite (single table). Lightweight — one row per memory_id.
"""
from __future__ import annotations

import logging
import math
import re
import sqlite3
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_usefulness (
    memory_id     TEXT PRIMARY KEY,
    score_sum     REAL NOT NULL DEFAULT 0,
    sample_count  INTEGER NOT NULL DEFAULT 0,
    last_used_at  REAL,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_failure_at REAL
);
CREATE INDEX IF NOT EXISTS idx_use_used ON memory_usefulness(last_used_at);
"""


# In-memory pending-retrieval registry: task_id → [(memory_id, content), ...]
_PENDING: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
_PENDING_LOCK = threading.Lock()
_PENDING_TTL_SEC = 3600  # drop pending entries older than 1h
_PENDING_TS: Dict[str, float] = {}


# ── Token utilities for cheap lexical overlap ──────────────────────────── #

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{3,}")


def _tokenize(text: str) -> set:
    if not text:
        return set()
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ── Public registry API ────────────────────────────────────────────────── #

def record_retrieval(task_id: str, hits: Iterable[Tuple[str, float, Dict[str, Any]]]) -> None:
    """Stash retrieved memories for later evaluation.

    Called by hybrid_search after producing results. Lightweight — just
    remembers memory_id + content. Cleared on task completion or TTL.
    """
    if not task_id:
        return
    now = time.time()
    _prune_pending(now)
    with _PENDING_LOCK:
        _PENDING_TS[task_id] = now
        bucket = _PENDING[task_id]
        for content, _score, meta in hits:
            mem_id = _extract_id(meta)
            if mem_id and content:
                bucket.append((mem_id, content))


def evaluate_task(
    task_id: str,
    result_summary: str,
    *,
    success: bool = True,
    retry_count: int = 0,
) -> int:
    """Score each retrieved memory's contribution to this task.

    Returns the number of memories evaluated.

    Heuristics:
      base       = jaccard(memory_tokens, summary_tokens)  in [0, 1]
      success    = +0.2 if success else 0.0
      retry_pen  = -0.1 * retry_count  (capped at -0.3)
      final      = clamp(base + success + retry_pen, 0, 1)

    Failures (success=False) get a smaller boost AND increment failure_count
    on the memory provenance.
    """
    with _PENDING_LOCK:
        memories = _PENDING.pop(task_id, [])
        _PENDING_TS.pop(task_id, None)
    if not memories:
        return 0

    summary_tokens = _tokenize(result_summary)
    success_lift = 0.2 if success else 0.0
    retry_pen = max(-0.3, -0.1 * retry_count)

    store = get_usefulness_store()
    n = 0
    for mem_id, content in memories:
        if not mem_id:
            continue
        base = _jaccard(_tokenize(content), summary_tokens)
        score = max(0.0, min(1.0, base + success_lift + retry_pen))
        store.record(mem_id, score=score, failure=not success)
        try:
            from apps.shail import telemetry
            from shail.observability.bridge import USEFULNESS_SCORE, USEFULNESS_APPLIED
            telemetry.observe(USEFULNESS_SCORE, score)
            status = "positive" if score > 0.5 else ("neutral" if score > 0.2 else "negative")
            telemetry.incr(USEFULNESS_APPLIED, status=status)
        except Exception:
            pass
        n += 1
    return n


def get_usefulness(memory_id: str) -> Tuple[float, int]:
    """Return (running_mean_score, sample_count). Defaults (0.5, 0)."""
    return get_usefulness_store().get(memory_id)


def apply_usefulness_boost(
    hits: List[Tuple[str, float, Dict[str, Any]]],
    *,
    boost_weight: float = 0.15,
) -> List[Tuple[str, float, Dict[str, Any]]]:
    """Rerank hits by mixing usefulness into the score.

      new_score = (1 - w) * orig_score + w * usefulness_score
    """
    if not hits:
        return hits
    store = get_usefulness_store()
    reranked = []
    for content, score, meta in hits:
        mem_id = _extract_id(meta)
        if mem_id:
            use_score, samples = store.get(mem_id)
            # Confidence-weight the boost by sample count
            conf = samples / (samples + 5) if samples else 0.0
            effective_w = boost_weight * conf
            new_score = (1 - effective_w) * score + effective_w * use_score
            meta = dict(meta)
            meta["usefulness_score"] = round(use_score, 4)
            meta["usefulness_samples"] = samples
            reranked.append((content, round(new_score, 4), meta))
        else:
            reranked.append((content, score, meta))
    reranked.sort(key=lambda h: h[1], reverse=True)
    return reranked


# ── Usefulness store (SQLite) ──────────────────────────────────────────── #

class UsefulnessStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        from apps.shail.settings import get_settings
        s = get_settings()
        path = db_path or getattr(s, "usefulness_db",
                                   "~/Library/Application Support/SHAIL/usefulness.db")
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._path), check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def record(self, memory_id: str, *, score: float, failure: bool = False) -> None:
        now = time.time()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT score_sum, sample_count, failure_count FROM memory_usefulness WHERE memory_id=?",
                (memory_id,),
            ).fetchone()
            if row is None:
                c.execute(
                    """INSERT INTO memory_usefulness
                       (memory_id, score_sum, sample_count, last_used_at,
                        failure_count, last_failure_at)
                       VALUES (?, ?, 1, ?, ?, ?)""",
                    (memory_id, score, now,
                     1 if failure else 0,
                     now if failure else None),
                )
            else:
                score_sum, sample_count, fail_count = row
                new_fail = fail_count + (1 if failure else 0)
                c.execute(
                    """UPDATE memory_usefulness
                       SET score_sum = score_sum + ?,
                           sample_count = sample_count + 1,
                           last_used_at = ?,
                           failure_count = ?,
                           last_failure_at = CASE WHEN ? THEN ? ELSE last_failure_at END
                       WHERE memory_id = ?""",
                    (score, now, new_fail, failure, now, memory_id),
                )

    def get(self, memory_id: str) -> Tuple[float, int]:
        with self._conn() as c:
            row = c.execute(
                "SELECT score_sum, sample_count FROM memory_usefulness WHERE memory_id=?",
                (memory_id,),
            ).fetchone()
        if row is None or row[1] == 0:
            return (0.5, 0)
        score_sum, count = row
        return (score_sum / count, count)

    def stats(self) -> Dict[str, Any]:
        with self._conn() as c:
            row = c.execute(
                """SELECT COUNT(*), AVG(score_sum/NULLIF(sample_count,0)),
                          SUM(sample_count), SUM(failure_count)
                   FROM memory_usefulness""",
            ).fetchone()
        total, avg, samples, failures = row
        return {
            "tracked_memories": total or 0,
            "mean_usefulness":  round(float(avg or 0.5), 4),
            "total_samples":    samples or 0,
            "total_failures":   failures or 0,
        }


# ── Singleton ──────────────────────────────────────────────────────────── #

_store: Optional[UsefulnessStore] = None
_store_lock = threading.Lock()


def get_usefulness_store() -> UsefulnessStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = UsefulnessStore()
    return _store


def reset_for_tests() -> None:
    global _store
    with _store_lock:
        _store = None
    with _PENDING_LOCK:
        _PENDING.clear()
        _PENDING_TS.clear()


# ── Internals ──────────────────────────────────────────────────────────── #

def _extract_id(meta: Dict[str, Any]) -> Optional[str]:
    if not meta:
        return None
    for key in ("memory_id", "id", "customId"):
        v = meta.get(key)
        if v:
            return str(v)
    return None


def _prune_pending(now: float) -> None:
    """Drop pending entries older than TTL."""
    expired = [tid for tid, ts in _PENDING_TS.items() if now - ts > _PENDING_TTL_SEC]
    for tid in expired:
        _PENDING.pop(tid, None)
        _PENDING_TS.pop(tid, None)
