"""raw_transcripts — provenance store for browser captures (Plan B5).

Decouples raw transcript persistence from embedding. Before this table,
`/browser/capture` called `ingest()` immediately — if Ollama was down the
transcript text was never saved anywhere outside the failed embed attempt.

Now: every capture writes a row here FIRST, then attempts embed. The row
carries `embedded` and `blueprinted` flags so the queue worker can revisit
incomplete records once Ollama comes back online.

Schema is minimal — the canonical content also lives in Chroma + the
session-backed `chat_messages` table for chat-style captures. This store
exists primarily for non-session captures (page visits, single AI
conversations) where there's no chat_messages row to lean on.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _conn():
    from apps.shail.auth_store import _conn as auth_conn
    return auth_conn()


def init_raw_transcripts_schema() -> None:
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS raw_transcripts (
                memory_id    TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                namespace    TEXT NOT NULL,
                content_type TEXT NOT NULL,
                content      TEXT NOT NULL,
                metadata     TEXT,
                captured_at  TEXT NOT NULL,
                embedded     INTEGER DEFAULT 0,
                blueprinted  INTEGER DEFAULT 0,
                segments     TEXT,
                content_chars INTEGER,
                segment_count INTEGER,
                capture_mode TEXT DEFAULT 'active',
                retention_policy TEXT DEFAULT 'keep_raw',
                transcript_deleted_at TEXT,
                redaction_reason TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_raw_transcripts_user ON raw_transcripts(user_id, captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_raw_transcripts_unembedded
                ON raw_transcripts(embedded) WHERE embedded = 0;
            CREATE INDEX IF NOT EXISTS idx_raw_transcripts_unblueprinted
                ON raw_transcripts(blueprinted) WHERE blueprinted = 0;
        """)
        # Add columns to legacy tables that pre-date segment support.
        for col, ddl in (
            ("segments", "TEXT"),
            ("content_chars", "INTEGER"),
            ("segment_count", "INTEGER"),
            ("capture_mode", "TEXT DEFAULT 'active'"),
            ("retention_policy", "TEXT DEFAULT 'keep_raw'"),
            ("transcript_deleted_at", "TEXT"),
            ("redaction_reason", "TEXT"),
        ):
            try:
                con.execute(f"ALTER TABLE raw_transcripts ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass  # already exists


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(
    *,
    memory_id: str,
    user_id: str,
    namespace: str,
    content_type: str,
    content: str,
    metadata: Optional[dict] = None,
    segments: Optional[list] = None,
    capture_mode: str = "active",
) -> None:
    """Persist a raw transcript. Idempotent on memory_id (UPSERT).

    `segments`: optional pre-parsed Segment list (typed content). When omitted,
    segments are parsed from `content` so downstream consumers always have a
    typed projection available. Pass `[]` (empty list) to explicitly skip
    segment parsing — useful for binary or opaque payloads.
    """
    from apps.shail import segments as _segs
    from apps.shail import pipeline_status as _ps

    init_raw_transcripts_schema()
    md = json.dumps(metadata or {})

    with _conn() as con:
        existing = con.execute(
            "SELECT retention_policy FROM raw_transcripts WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
    if existing and existing["retention_policy"] == "transcript_deleted":
        content = ""
        segments = []

    if segments is None:
        parsed = _segs.parse_segments(content)
    elif isinstance(segments, list) and segments and isinstance(segments[0], _segs.Segment):
        parsed = segments
    elif isinstance(segments, list):
        parsed = [_segs.Segment.from_dict(s) if isinstance(s, dict) else _segs.Segment(kind="text", content=str(s)) for s in segments]
    else:
        parsed = []

    seg_blob = _segs.segments_to_json(parsed) if parsed else None
    seg_count = len(parsed)
    content_chars = len(content or "")

    with _conn() as con:
        con.execute(
            """INSERT INTO raw_transcripts
               (memory_id, user_id, namespace, content_type, content, metadata, captured_at,
                segments, content_chars, segment_count, capture_mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(memory_id) DO UPDATE SET
                   content = excluded.content,
                   metadata = excluded.metadata,
                   captured_at = excluded.captured_at,
                   segments = excluded.segments,
                   content_chars = excluded.content_chars,
                   segment_count = excluded.segment_count,
                   capture_mode = excluded.capture_mode""",
            (memory_id, user_id, namespace, content_type, content, md, _now(),
             seg_blob, content_chars, seg_count, capture_mode),
        )

    _ps.mark_stage(memory_id, "captured", "done", size_bytes=content_chars,
                   detail={"content_type": content_type, "segments": seg_count})
    _ps.mark_stage(memory_id, "transcript_ready", "done", size_bytes=content_chars,
                   detail={"capture_mode": capture_mode})
    if parsed:
        _ps.mark_stage(memory_id, "segmented", "done", size_bytes=seg_count,
                       detail={"kinds": _kind_histogram(parsed)})


def _kind_histogram(segments: list) -> dict:
    out: dict = {}
    for s in segments:
        out[s.kind] = out.get(s.kind, 0) + 1
    return out


def get_segments(memory_id: str) -> list:
    """Return parsed Segment objects for a memory, or [] if none stored."""
    from apps.shail import segments as _segs
    init_raw_transcripts_schema()
    with _conn() as con:
        row = con.execute(
            "SELECT segments FROM raw_transcripts WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
    if not row:
        return []
    return _segs.segments_from_json(row["segments"] if hasattr(row, "keys") else row[0])


def mark_embedded(memory_id: str, embedded: bool = True) -> None:
    from apps.shail import pipeline_status as _ps
    init_raw_transcripts_schema()
    with _conn() as con:
        con.execute(
            "UPDATE raw_transcripts SET embedded = ? WHERE memory_id = ?",
            (1 if embedded else 0, memory_id),
        )
    _ps.mark_stage(memory_id, "embedded", "done" if embedded else "failed")


def mark_blueprinted(memory_id: str, blueprinted: bool = True) -> None:
    from apps.shail import pipeline_status as _ps
    init_raw_transcripts_schema()
    with _conn() as con:
        con.execute(
            "UPDATE raw_transcripts SET blueprinted = ? WHERE memory_id = ?",
            (1 if blueprinted else 0, memory_id),
        )
    _ps.mark_stage(memory_id, "blueprint_ready", "done" if blueprinted else "failed")
    if blueprinted:
        apply_pending_redaction(memory_id)


def set_retention_policy(memory_id: str, policy: str) -> Dict[str, Any]:
    """Set retention policy for a browser capture.

    `blueprint_only` is safe before the blueprint exists: the raw transcript is
    retained until `mark_blueprinted()` confirms a stored blueprint, then
    redacted by `apply_pending_redaction()`.
    """
    if policy not in {"keep_raw", "blueprint_only", "decide_later"}:
        raise ValueError(f"unsupported retention policy: {policy}")
    init_raw_transcripts_schema()
    with _conn() as con:
        row = con.execute(
            "SELECT blueprinted FROM raw_transcripts WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not_found", "memory_id": memory_id}
        con.execute(
            "UPDATE raw_transcripts SET retention_policy = ? WHERE memory_id = ?",
            (policy, memory_id),
        )
    if policy == "blueprint_only" and bool(row["blueprinted"]):
        return redact_if_blueprinted(memory_id, reason="blueprint_only")
    return {"ok": True, "memory_id": memory_id, "retention_policy": policy, "redacted": False}


def redact_if_blueprinted(memory_id: str, *, reason: str = "manual") -> Dict[str, Any]:
    """Redact raw browser-capture transcript only when a blueprint exists.

    Keeps the raw_transcripts row, metadata, vector memory, and blueprint. The
    content is replaced with an empty string so state and provenance survive.
    """
    from apps.shail.blueprints import get_blueprint
    from apps.shail import pipeline_status as _ps

    init_raw_transcripts_schema()
    if not get_blueprint(memory_id):
        return {"ok": False, "reason": "no_blueprint_stored", "memory_id": memory_id}

    deleted_at = _now()
    with _conn() as con:
        row = con.execute(
            "SELECT content_chars FROM raw_transcripts WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not_found", "memory_id": memory_id}
        previous_chars = int(row["content_chars"] or 0)
        con.execute(
            """UPDATE raw_transcripts
               SET content = '',
                   segments = NULL,
                   content_chars = 0,
                   segment_count = 0,
                   retention_policy = 'transcript_deleted',
                   transcript_deleted_at = ?,
                   redaction_reason = ?
               WHERE memory_id = ?""",
            (deleted_at, reason, memory_id),
        )
    _ps.mark_stage(
        memory_id,
        "transcript_ready",
        "skipped",
        size_bytes=0,
        detail={"redacted": True, "previous_chars": previous_chars, "reason": reason},
    )
    return {
        "ok": True,
        "memory_id": memory_id,
        "retention_policy": "transcript_deleted",
        "redacted": True,
        "previous_chars": previous_chars,
        "transcript_deleted_at": deleted_at,
    }


def apply_pending_redaction(memory_id: str) -> Dict[str, Any]:
    init_raw_transcripts_schema()
    with _conn() as con:
        row = con.execute(
            "SELECT retention_policy, transcript_deleted_at FROM raw_transcripts WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
    if not row:
        return {"ok": False, "reason": "not_found", "memory_id": memory_id}
    if row["transcript_deleted_at"]:
        return {"ok": True, "memory_id": memory_id, "redacted": True, "already": True}
    if row["retention_policy"] != "blueprint_only":
        return {"ok": True, "memory_id": memory_id, "redacted": False}
    return redact_if_blueprinted(memory_id, reason="blueprint_only")


def get(memory_id: str) -> Optional[Dict[str, Any]]:
    init_raw_transcripts_schema()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM raw_transcripts WHERE memory_id = ?", (memory_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["metadata"] = json.loads(d.get("metadata") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["metadata"] = {}
    return d


def find_latest(
    *,
    memory_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    source_url: Optional[str] = None,
    namespace: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Find the latest raw transcript by one of the public capture keys."""
    if memory_id:
        row = get(memory_id)
        if row and (namespace is None or row.get("namespace") == namespace):
            return row
        return None

    clauses: list[str] = []
    args: list[Any] = []
    if namespace:
        clauses.append("namespace = ?")
        args.append(namespace)
    if conversation_id:
        clauses.append("json_extract(metadata, '$.conversationId') = ?")
        args.append(conversation_id)
    if source_url:
        clauses.append("json_extract(metadata, '$.sourceUrl') = ?")
        args.append(source_url)
    if not clauses:
        return None

    init_raw_transcripts_schema()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM raw_transcripts WHERE "
            + " AND ".join(clauses)
            + " ORDER BY captured_at DESC LIMIT 1",
            args,
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["metadata"] = json.loads(d.get("metadata") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["metadata"] = {}
    return d


def list_recent(
    *,
    namespace: Optional[str] = None,
    limit: int = 5000,
    after: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List newest raw transcripts, used to surface pending captures before embedding."""
    clauses: list[str] = []
    args: list[Any] = []
    if namespace:
        clauses.append("namespace = ?")
        args.append(namespace)
    if after:
        clauses.append("captured_at >= ?")
        args.append(after)

    sql = "SELECT * FROM raw_transcripts"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY captured_at DESC LIMIT ?"
    args.append(limit)

    init_raw_transcripts_schema()
    with _conn() as con:
        rows = con.execute(sql, args).fetchall()

    out: List[Dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        try:
            d["metadata"] = json.loads(d.get("metadata") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
        out.append(d)
    return out


def list_unembedded(limit: int = 100) -> List[Dict[str, Any]]:
    init_raw_transcripts_schema()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM raw_transcripts WHERE embedded = 0 ORDER BY captured_at LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_unblueprinted(limit: int = 100) -> List[Dict[str, Any]]:
    init_raw_transcripts_schema()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM raw_transcripts WHERE blueprinted = 0 ORDER BY captured_at LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete(memory_id: str) -> None:
    init_raw_transcripts_schema()
    with _conn() as con:
        con.execute("DELETE FROM raw_transcripts WHERE memory_id = ?", (memory_id,))


def stats() -> Dict[str, int]:
    init_raw_transcripts_schema()
    with _conn() as con:
        total = con.execute("SELECT COUNT(*) FROM raw_transcripts").fetchone()[0]
        unembedded = con.execute("SELECT COUNT(*) FROM raw_transcripts WHERE embedded = 0").fetchone()[0]
        unblueprinted = con.execute("SELECT COUNT(*) FROM raw_transcripts WHERE blueprinted = 0").fetchone()[0]
    return {"total": total, "unembedded": unembedded, "unblueprinted": unblueprinted}
