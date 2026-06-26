"""Pipeline status — explicit per-memory stage tracker.

Answers the question: "where is capture X in the pipeline RIGHT NOW?"

Before this module the answer had to be inferred by joining flags across
`raw_transcripts.embedded`, `raw_transcripts.blueprinted`, `blueprint_jobs.state`,
and `blueprints` existence. Three separate tables. No single source of truth.

This table stores one row per memory_id with the explicit stage of every
phase the capture flows through:

    captured       - raw input persisted (always reached when row exists)
    segmented      - structured segments parsed + stored
    embedded       - vector ingest complete (or degraded)
    transcript_ready - full transcript built and saved
    blueprint_queued - job sitting in blueprint_jobs
    blueprint_extracting - LLM call in progress (active stage)
    blueprint_ready - blueprint row exists
    promoted       - blueprint materialized for RAG injection

Each phase carries `started_at`, `completed_at`, optional `error`, and
optional `size_bytes` so a UI can render a true timeline. Idempotent: any
re-entry into a stage updates the timestamp without losing history.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STAGES = (
    "captured",
    "segmented",
    "embedded",
    "transcript_ready",
    "blueprint_queued",
    "blueprint_extracting",
    "blueprint_ready",
    "promoted",
)


def _conn():
    from apps.shail.auth_store import _conn as auth_conn
    return auth_conn()


def init_pipeline_status_schema() -> None:
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS pipeline_status (
                memory_id   TEXT NOT NULL,
                stage       TEXT NOT NULL,
                state       TEXT NOT NULL,
                started_at  TEXT,
                completed_at TEXT,
                size_bytes  INTEGER,
                error       TEXT,
                detail      TEXT,
                updated_at  TEXT NOT NULL,
                PRIMARY KEY (memory_id, stage)
            );
            CREATE INDEX IF NOT EXISTS idx_pipeline_status_memory
                ON pipeline_status(memory_id);
            CREATE INDEX IF NOT EXISTS idx_pipeline_status_active
                ON pipeline_status(state) WHERE state = 'active';
        """)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_stage(
    memory_id: str,
    stage: str,
    state: str,
    *,
    size_bytes: Optional[int] = None,
    error: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Update one stage. `state` is one of: pending|active|done|failed|skipped.

    Best-effort: failures here never raise into callers. Pipeline observability
    must not become a load-bearing blocker.
    """
    if stage not in STAGES:
        logger.debug("unknown pipeline stage %r — recorded anyway", stage)
    init_pipeline_status_schema()
    try:
        now = _now()
        started_at = now if state == "active" else None
        completed_at = now if state in ("done", "failed", "skipped") else None
        detail_blob = json.dumps(detail) if detail else None
        with _conn() as con:
            existing = con.execute(
                "SELECT started_at FROM pipeline_status WHERE memory_id = ? AND stage = ?",
                (memory_id, stage),
            ).fetchone()
            keep_started = existing["started_at"] if existing else None
            final_started = started_at or keep_started
            con.execute(
                """INSERT INTO pipeline_status
                   (memory_id, stage, state, started_at, completed_at,
                    size_bytes, error, detail, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(memory_id, stage) DO UPDATE SET
                       state = excluded.state,
                       started_at = COALESCE(pipeline_status.started_at, excluded.started_at),
                       completed_at = COALESCE(excluded.completed_at, pipeline_status.completed_at),
                       size_bytes = COALESCE(excluded.size_bytes, pipeline_status.size_bytes),
                       error = excluded.error,
                       detail = COALESCE(excluded.detail, pipeline_status.detail),
                       updated_at = excluded.updated_at""",
                (memory_id, stage, state, final_started, completed_at,
                 size_bytes, (error or None), detail_blob, now),
            )
    except Exception as exc:
        logger.debug("pipeline_status.mark_stage failed (%s,%s): %s", memory_id, stage, exc)


def get_status(memory_id: str) -> Dict[str, Any]:
    """Return all stage rows for one memory_id."""
    init_pipeline_status_schema()
    with _conn() as con:
        rows = con.execute(
            "SELECT stage, state, started_at, completed_at, size_bytes, error, detail, updated_at "
            "FROM pipeline_status WHERE memory_id = ?",
            (memory_id,),
        ).fetchall()
    stages: Dict[str, Any] = {}
    for r in rows:
        d = dict(r)
        if d.get("detail"):
            try:
                d["detail"] = json.loads(d["detail"])
            except (TypeError, json.JSONDecodeError):
                pass
        stages[d["stage"]] = d
    # Build a summary that names the current logical stage (most recent active
    # one, or the latest done one if nothing is active).
    active = [d for d in stages.values() if d.get("state") == "active"]
    failed = [d for d in stages.values() if d.get("state") == "failed"]
    done = [d for d in stages.values() if d.get("state") == "done"]
    current = None
    if active:
        current = max(active, key=lambda x: x.get("updated_at") or "")
    elif failed:
        current = max(failed, key=lambda x: x.get("updated_at") or "")
    elif done:
        current = max(done, key=lambda x: x.get("updated_at") or "")
    return {
        "memory_id": memory_id,
        "current_stage": current.get("stage") if current else None,
        "current_state": current.get("state") if current else None,
        "stages": stages,
    }


def list_active(limit: int = 100) -> List[Dict[str, Any]]:
    """Captures currently mid-pipeline. Used by a status dashboard."""
    init_pipeline_status_schema()
    with _conn() as con:
        rows = con.execute(
            "SELECT memory_id, stage, state, started_at, updated_at "
            "FROM pipeline_status WHERE state = 'active' "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_status(memory_id: str) -> None:
    init_pipeline_status_schema()
    with _conn() as con:
        con.execute("DELETE FROM pipeline_status WHERE memory_id = ?", (memory_id,))
