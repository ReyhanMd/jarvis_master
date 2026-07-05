"""Blueprint job queue + background worker (Plan B6 + B7).

The capture pipeline used to fire blueprint generation as a `create_task()`
fire-and-forget. When Ollama was down, the generation failed silently and no
blueprint ever existed — sessions sat in `degraded` state forever.

This module replaces that with a persistent queue:

  - `enqueue()` writes a `blueprint_jobs` row (state=pending) and returns.
  - A `worker_loop()` started at backend startup polls the table every 30s,
    picks the oldest job whose `next_attempt_at <= now`, probes Ollama, and
    either runs `generate_blueprint()` / `generate_session_blueprint()` or
    backs off exponentially.
  - On success: state=done, `quality_score` populated. If the originating
    session has `auto_redact_on_blueprint=1` AND score >= threshold, the
    raw transcript is redacted via `redact_session_transcript()`.

Idempotent — re-running a `done` job is a no-op.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 30.0
_MAX_BACKOFF_SECONDS = 3600  # 1h cap
_MAX_ATTEMPTS_DEFAULT = 5


def _conn():
    from apps.shail.auth_store import _conn as auth_conn
    return auth_conn()


def init_blueprint_queue_schema() -> None:
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS blueprint_jobs (
                id              TEXT PRIMARY KEY,
                memory_id       TEXT NOT NULL,
                session_id      TEXT,
                user_id         TEXT NOT NULL,
                content_type    TEXT NOT NULL,
                state           TEXT DEFAULT 'pending',
                attempts        INTEGER DEFAULT 0,
                max_attempts    INTEGER DEFAULT 5,
                last_error      TEXT,
                next_attempt_at TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                quality_score   REAL,
                priority        INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_blueprint_jobs_pending
                ON blueprint_jobs(state, next_attempt_at);
            CREATE INDEX IF NOT EXISTS idx_blueprint_jobs_memory
                ON blueprint_jobs(memory_id);
            CREATE INDEX IF NOT EXISTS idx_blueprint_jobs_session
                ON blueprint_jobs(session_id);
        """)
        # Add priority column to legacy tables.
        try:
            con.execute("ALTER TABLE blueprint_jobs ADD COLUMN priority INTEGER DEFAULT 0")
        except Exception:
            pass  # already exists


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Enqueue ──────────────────────────────────────────────────────────────────

def enqueue(
    memory_id: str,
    *,
    session_id: Optional[str],
    user_id: str,
    content_type: str,
    max_attempts: int = _MAX_ATTEMPTS_DEFAULT,
    priority: int = 0,
) -> str:
    """Add a pending blueprint job. Returns the new job id.

    If a non-`done`, non-`failed` job for the same memory_id already exists,
    it's reused (no duplicate enqueue). This makes the call safe for retries
    and for the capture-time + backfill-time call sites to both invoke it.

    `priority`: 0 = normal (live captures), -1 = low (bulk/retroactive),
                1 = high (user-requested re-blueprint).
    """
    init_blueprint_queue_schema()
    with _conn() as con:
        row = con.execute(
            "SELECT id, state FROM blueprint_jobs "
            "WHERE memory_id = ? AND state NOT IN ('done', 'failed') "
            "ORDER BY created_at DESC LIMIT 1",
            (memory_id,),
        ).fetchone()
        if row:
            return row["id"]
        job_id = str(uuid.uuid4())
        now = _now()
        con.execute(
            """INSERT INTO blueprint_jobs
               (id, memory_id, session_id, user_id, content_type, state, attempts,
                max_attempts, next_attempt_at, created_at, updated_at, priority)
               VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, ?)""",
            (job_id, memory_id, session_id, user_id, content_type,
             max_attempts, now, now, now, priority),
        )
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    init_blueprint_queue_schema()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM blueprint_jobs WHERE id = ?", (job_id,),
        ).fetchone()
    return dict(row) if row else None


def list_jobs(state: Optional[str] = None, *, limit: int = 100) -> List[Dict[str, Any]]:
    init_blueprint_queue_schema()
    with _conn() as con:
        if state:
            rows = con.execute(
                "SELECT * FROM blueprint_jobs WHERE state = ? "
                "ORDER BY created_at DESC LIMIT ?", (state, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM blueprint_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def jobs_for_session(session_id: str) -> List[Dict[str, Any]]:
    init_blueprint_queue_schema()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM blueprint_jobs WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def job_for_memory(memory_id: str) -> Optional[Dict[str, Any]]:
    init_blueprint_queue_schema()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM blueprint_jobs WHERE memory_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (memory_id,),
        ).fetchone()
    return dict(row) if row else None


# ── State transitions ────────────────────────────────────────────────────────

def _mark_running(job_id: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE blueprint_jobs SET state = 'running', updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )


def _mark_done(job_id: str, quality_score: float) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE blueprint_jobs SET state = 'done', quality_score = ?, "
            "last_error = NULL, updated_at = ? WHERE id = ?",
            (float(quality_score), _now(), job_id),
        )


def _mark_failure(job_id: str, error: str, attempts: int, max_attempts: int) -> None:
    """Schedule next attempt with exponential backoff (60s * 2^attempts) up to cap."""
    delay = min(_MAX_BACKOFF_SECONDS, 60 * (2 ** min(attempts, 10)))
    next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    new_state = "failed" if attempts >= max_attempts else "pending"
    with _conn() as con:
        con.execute(
            "UPDATE blueprint_jobs SET state = ?, attempts = ?, last_error = ?, "
            "next_attempt_at = ?, updated_at = ? WHERE id = ?",
            (new_state, attempts, (error or "")[:500], next_at, _now(), job_id),
        )


def _claim_next(now_iso: str) -> Optional[Dict[str, Any]]:
    """Pop the oldest pending job whose next_attempt_at <= now.
    Higher priority jobs are processed first."""
    init_blueprint_queue_schema()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM blueprint_jobs WHERE state = 'pending' "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY priority DESC, created_at LIMIT 1",
            (now_iso,),
        ).fetchone()
    return dict(row) if row else None


def stats() -> Dict[str, Any]:
    """Blueprint queue health stats for monitoring / dashboard."""
    init_blueprint_queue_schema()
    with _conn() as con:
        total = con.execute("SELECT COUNT(*) FROM blueprint_jobs").fetchone()[0]
        pending = con.execute("SELECT COUNT(*) FROM blueprint_jobs WHERE state = 'pending'").fetchone()[0]
        running = con.execute("SELECT COUNT(*) FROM blueprint_jobs WHERE state = 'running'").fetchone()[0]
        done = con.execute("SELECT COUNT(*) FROM blueprint_jobs WHERE state = 'done'").fetchone()[0]
        failed = con.execute("SELECT COUNT(*) FROM blueprint_jobs WHERE state = 'failed'").fetchone()[0]
        avg_score = con.execute(
            "SELECT AVG(quality_score) FROM blueprint_jobs WHERE state = 'done' AND quality_score IS NOT NULL"
        ).fetchone()[0]
    return {
        "total": total,
        "pending": pending,
        "running": running,
        "done": done,
        "failed": failed,
        "avg_quality_score": round(avg_score, 3) if avg_score else None,
    }


# ── Quality scoring (B7) ─────────────────────────────────────────────────────

# Fields whose populated-ness signals a high-quality blueprint. Each present
# field contributes proportional weight; total clamped to [0, 1].
_QUALITY_FIELDS = {
    "decisions":          0.20,
    "key_entities":       0.20,
    "facts":              0.15,
    "next_actions":       0.15,
    "questions_answered": 0.10,
    "open_questions":     0.10,
    "metrics":            0.05,
    "tables":             0.05,
}


def compute_quality_score(bp: Optional[dict]) -> float:
    """Score in [0, 1] based on how many durable-knowledge fields are populated.

    A field counts if it's a non-empty list/dict/string. Tunable threshold
    in settings.blueprint_quality_threshold drives the auto-redact gate.
    """
    if not bp or not isinstance(bp, dict):
        return 0.0
    total = 0.0
    for field, weight in _QUALITY_FIELDS.items():
        v = bp.get(field)
        if isinstance(v, (list, dict, str)) and len(v) > 0:
            total += weight
    return min(1.0, total)


# ── Ollama health probe ──────────────────────────────────────────────────────

async def _ollama_alive() -> bool:
    """Cheap probe: embed_query("ping") returns a non-zero vector when up."""
    try:
        from shail.memory.embeddings import embed_query, is_zero_vector
        vec = await asyncio.to_thread(embed_query, "ping")
        return not is_zero_vector(vec)
    except Exception as exc:
        logger.debug("ollama probe failed: %s", exc)
        return False


async def _ensure_ollama_for_blueprint_queue() -> bool:
    """Start Ollama only for queued blueprint work, with ownership tracked.

    If the user already had Ollama running, this is a no-op and later idle
    auto-stop will not touch that process.
    """
    if await _ollama_alive():
        return True
    try:
        from apps.shail.system_api import start_ollama_for_blueprint_queue
        return await start_ollama_for_blueprint_queue()
    except Exception as exc:
        logger.debug("blueprint queue could not auto-start Ollama: %s", exc)
        return False


async def _maybe_stop_blueprint_ollama_when_idle() -> None:
    try:
        from apps.shail.system_api import stop_blueprint_queue_ollama_if_idle
        await stop_blueprint_queue_ollama_if_idle()
    except Exception as exc:
        logger.debug("blueprint queue Ollama idle-stop skipped: %s", exc)


# ── Job execution ────────────────────────────────────────────────────────────

async def _run_session_job(job: Dict[str, Any]) -> Optional[dict]:
    """Generate (or regenerate) a session blueprint and return it."""
    from apps.shail.session_backfill import generate_session_blueprint
    return await generate_session_blueprint(job["session_id"], job["user_id"])


async def _run_capture_job(job: Dict[str, Any]) -> Optional[dict]:
    """Generate a blueprint for a single browser-capture memory."""
    from apps.shail.blueprints import generate_blueprint
    from apps.shail import raw_transcripts
    rt = raw_transcripts.get(job["memory_id"])
    if not rt:
        # Nothing to blueprint — treat as success with zero score so we don't
        # loop forever on a deleted record.
        return {}
    bp = await generate_blueprint(
        job["memory_id"],
        content=rt.get("content", ""),
        content_type=rt.get("content_type") or job["content_type"],
        user_id=job["user_id"],
        namespace=rt.get("namespace") or f"user_{job['user_id']}",
    )
    if bp:
        raw_transcripts.mark_blueprinted(job["memory_id"], True)
    return bp


async def _try_auto_redact(job: Dict[str, Any], score: float) -> None:
    """B7: if quality clears the threshold AND the session opted in, drop the
    raw transcript. Safe — redact_session_transcript refuses to delete without
    a blueprint stored.
    """
    if not job.get("session_id"):
        return
    from apps.shail.settings import get_settings
    threshold = get_settings().blueprint_quality_threshold
    if score < threshold:
        return
    # Check per-session opt-in flag
    try:
        from apps.shail.session_backfill import (
            _get_session_auto_redact_flag,
            redact_session_transcript,
        )
        if not _get_session_auto_redact_flag(job["session_id"]):
            return
        result = redact_session_transcript(job["session_id"], job["user_id"])
        if result.get("ok"):
            from apps.shail.capture_log import write_event
            write_event(
                "REDACT",
                f"auto-redacted session {job['session_id'][:8]} after blueprint "
                f"(score={score:.2f} >= {threshold:.2f}, "
                f"deleted={result.get('messages_deleted')})",
                user_id=job["user_id"], ref_id=job["session_id"],
            )
    except Exception as exc:
        logger.warning("auto-redact attempt failed for session %s: %s",
                       job.get("session_id"), exc)


async def _process_job(job: Dict[str, Any]) -> None:
    """Run one job. On success: mark done + score + maybe redact. On failure:
    increment attempts + schedule backoff."""
    _mark_running(job["id"])
    new_attempts = (job.get("attempts") or 0) + 1
    max_attempts = job.get("max_attempts") or _MAX_ATTEMPTS_DEFAULT
    try:
        if job.get("session_id"):
            bp = await _run_session_job(job)
        else:
            bp = await _run_capture_job(job)
        score = compute_quality_score(bp)
        _mark_done(job["id"], score)
        logger.info(
            "blueprint job %s done (memory_id=%s session=%s score=%.2f)",
            job["id"][:8], job["memory_id"][:32], job.get("session_id"), score,
        )
        # Auto-redact gate (B7)
        if job.get("session_id"):
            await _try_auto_redact(job, score)
    except Exception as exc:
        logger.warning("blueprint job %s failed (attempt %d/%d): %s",
                       job["id"][:8], new_attempts, max_attempts, exc)
        _mark_failure(job["id"], str(exc), new_attempts, max_attempts)


# ── Worker loop ──────────────────────────────────────────────────────────────

_worker_started = False


async def worker_loop(poll_interval_seconds: float = _POLL_INTERVAL_SECONDS) -> None:
    """Forever-loop: probe Ollama, claim next pending job, process. Stops only
    on CancelledError so the app shutdown can tear it down cleanly.
    """
    logger.info("blueprint queue worker started (poll=%.0fs)", poll_interval_seconds)
    while True:
        try:
            now_iso = _now()
            if not await _ensure_ollama_for_blueprint_queue():
                # Sleep without claiming — leaves rows pending for the next pass.
                await asyncio.sleep(poll_interval_seconds)
                continue
            job = _claim_next(now_iso)
            if not job:
                await _maybe_stop_blueprint_ollama_when_idle()
                await asyncio.sleep(poll_interval_seconds)
                continue
            await _process_job(job)
            # Tight loop while there's pending work AND Ollama stays up.
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.info("blueprint queue worker stopping")
            raise
        except Exception as exc:
            logger.exception("blueprint queue worker tick error: %s", exc)
            await asyncio.sleep(poll_interval_seconds)


def start_worker() -> Optional[asyncio.Task]:
    """Idempotent: start the worker as an asyncio.Task in the current loop.
    Safe to call from FastAPI startup hook. Returns the Task or None if the
    worker was already running.
    """
    global _worker_started
    if _worker_started:
        return None
    _worker_started = True
    init_blueprint_queue_schema()
    task = asyncio.create_task(worker_loop())
    logger.info("blueprint queue worker task scheduled")
    return task
