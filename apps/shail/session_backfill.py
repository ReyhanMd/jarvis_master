"""
Session backfill — Phase C: retroactive chat session capture.

Walks every turn in a chat session from the first to the latest, re-indexes
Q+A pairs into the past-chat RAG namespace (idempotent), and generates a
SESSION-LEVEL blueprint summarizing the whole conversation.

Continue-capture: per-turn indexing already runs automatically via
`chat_api._schedule_post_reply()` after each new turn. Backfill is the
one-shot operation that catches up the historical tail.

Retention policy is enforced separately (see `redact_session_transcript`).

This module is intentionally independent of the streaming chat path so it
can be invoked from:
  - HTTP endpoint (POST /browser/chat/sessions/{id}/backfill)
  - CLI / scheduled task
  - one-off scripts
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from apps.shail import chat_store
from apps.shail.blueprints import (
    _merge_blueprints,
    generate_blueprint,
    get_blueprint,
    save_blueprint,
)
from apps.shail.settings import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class BackfillSummary:
    session_id: str
    turns_seen: int = 0
    turns_indexed: int = 0
    turns_skipped: int = 0
    blueprint_generated: bool = False
    blueprint_memory_id: Optional[str] = None
    raw_transcript_chars: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    # Sprint 1: degraded_mode signals vector indexing failed (e.g. Ollama down).
    # FTS5 keyword fallback populates via chat_messages triggers so content
    # remains keyword-searchable even when vectors are unavailable.
    degraded_mode: bool = False
    degraded_reason: Optional[str] = None
    fts_fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turns_seen": self.turns_seen,
            "turns_indexed": self.turns_indexed,
            "turns_skipped": self.turns_skipped,
            "blueprint_generated": self.blueprint_generated,
            "blueprint_memory_id": self.blueprint_memory_id,
            "raw_transcript_chars": self.raw_transcript_chars,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "degraded_mode": self.degraded_mode,
            "degraded_reason": self.degraded_reason,
            "fts_fallback_used": self.fts_fallback_used,
        }


# ---------------------------------------------------------------------------
# Schema bootstrap — Phase C columns on chat_sessions
# ---------------------------------------------------------------------------

PHASE_C_COLUMNS = {
    "retention_policy": "TEXT NOT NULL DEFAULT 'keep_raw'",
    # 'keep_raw' | 'blueprint_only' | 'transcript_deleted'
    "capture_enabled": "INTEGER NOT NULL DEFAULT 1",
    "blueprint_memory_id": "TEXT",
    "backfilled_at": "TEXT",
    # Sprint 2 — long-session safety / resumability
    "backfill_cursor": "INTEGER NOT NULL DEFAULT 0",
    # 'idle' | 'running' | 'done' | 'failed' | 'degraded'
    "backfill_state": "TEXT NOT NULL DEFAULT 'idle'",
    "backfill_job_id": "TEXT",
    "backfill_error": "TEXT",
    # Sprint 6 — proper source provenance (replaces title prefix hack)
    # NULL = native SHAIL session; 'chatgpt' | 'claude' | 'cursor' |
    # 'gemini' | 'grok' | 'perplexity' = imported
    "source": "TEXT",
    # Plan B7 — per-session opt-in for auto-deleting raw transcript once a
    # blueprint clears the quality threshold. 0 = keep raw (default), 1 = redact.
    "auto_redact_on_blueprint": "INTEGER NOT NULL DEFAULT 0",
}

# Sprint 2: batch size for chunked backfill. Each batch = one ingest() call
# (one Ollama batch embed round-trip) + one cursor commit.
_BACKFILL_BATCH_SIZE = 50


def ensure_phase_c_schema() -> None:
    """Idempotently add Phase C columns + FTS5 fallback table.

    Safe to call repeatedly. ALTER TABLE ADD COLUMN is non-blocking on SQLite
    and silently ignored if the column already exists (via probe).
    Also bootstraps chat_messages_fts (Sprint 1 — Ollama-down fallback).
    """
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        existing = {r[1] for r in con.execute("PRAGMA table_info(chat_sessions)")}
        for col, decl in PHASE_C_COLUMNS.items():
            if col not in existing:
                con.execute(f"ALTER TABLE chat_sessions ADD COLUMN {col} {decl}")
                logger.info("phase-c: added chat_sessions.%s", col)
    # FTS5 fallback for keyword-only search when vectors fail
    chat_store.ensure_chat_fts_schema()


# ---------------------------------------------------------------------------
# Session metadata helpers
# ---------------------------------------------------------------------------

def get_session_meta(session_id: str, user_id: str) -> Optional[dict]:
    """Return session row including Phase C fields."""
    ensure_phase_c_schema()
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def set_session_capture(session_id: str, user_id: str, enabled: bool) -> bool:
    """Enable / disable automatic continue-capture for new turns."""
    ensure_phase_c_schema()
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        cur = con.execute(
            "UPDATE chat_sessions SET capture_enabled = ? WHERE id = ? AND user_id = ?",
            (1 if enabled else 0, session_id, user_id),
        )
    return cur.rowcount > 0


def set_session_retention(session_id: str, user_id: str, policy: str) -> bool:
    """Set retention policy. policy ∈ {keep_raw, blueprint_only, transcript_deleted}."""
    if policy not in ("keep_raw", "blueprint_only", "transcript_deleted"):
        raise ValueError(f"invalid retention policy: {policy}")
    ensure_phase_c_schema()
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        cur = con.execute(
            "UPDATE chat_sessions SET retention_policy = ? WHERE id = ? AND user_id = ?",
            (policy, session_id, user_id),
        )
    return cur.rowcount > 0


def set_session_auto_redact(session_id: str, user_id: str, enabled: bool) -> bool:
    """Plan B7: opt session in/out of auto-deleting raw transcript after a
    high-quality blueprint. Quality threshold from settings."""
    ensure_phase_c_schema()
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        cur = con.execute(
            "UPDATE chat_sessions SET auto_redact_on_blueprint = ? "
            "WHERE id = ? AND user_id = ?",
            (1 if enabled else 0, session_id, user_id),
        )
    return cur.rowcount > 0


def _get_session_auto_redact_flag(session_id: str) -> bool:
    """Read the auto_redact_on_blueprint flag. Used by the blueprint queue."""
    ensure_phase_c_schema()
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        row = con.execute(
            "SELECT auto_redact_on_blueprint FROM chat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    if not row:
        # Default — respect global setting if no per-session flag.
        try:
            return bool(get_settings().auto_redact_default)
        except Exception:
            return False
    return bool(row[0] if row[0] is not None else 0)


# ---------------------------------------------------------------------------
# Sprint 2 — backfill state machine
# ---------------------------------------------------------------------------

def _set_backfill_state(
    session_id: str,
    *,
    state: Optional[str] = None,
    cursor: Optional[int] = None,
    job_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Update backfill state columns in chat_sessions. Only sets provided fields."""
    fields: list[str] = []
    values: list[Any] = []
    if state is not None:
        fields.append("backfill_state = ?"); values.append(state)
    if cursor is not None:
        fields.append("backfill_cursor = ?"); values.append(int(cursor))
    if job_id is not None:
        fields.append("backfill_job_id = ?"); values.append(job_id)
    if error is not None:
        fields.append("backfill_error = ?"); values.append(error)
    if not fields:
        return
    values.append(session_id)
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        con.execute(
            f"UPDATE chat_sessions SET {', '.join(fields)} WHERE id = ?",
            values,
        )


def get_backfill_stats(user_id: str) -> dict:
    """Sprint 7: aggregate backfill state across all of user's sessions."""
    ensure_phase_c_schema()
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        rows = list(con.execute(
            "SELECT id, backfill_state, backfill_cursor, source FROM chat_sessions WHERE user_id = ?",
            (user_id,),
        ))
    total = len(rows)
    by_state: dict[str, int] = {
        "idle": 0, "running": 0, "done": 0, "failed": 0, "degraded": 0,
    }
    by_source: dict[str, int] = {}
    total_turns = 0
    for r in rows:
        state = r["backfill_state"] or "idle"
        by_state[state] = by_state.get(state, 0) + 1
        src = r["source"] or "native"
        by_source[src] = by_source.get(src, 0) + 1
        # cursor approximates messages indexed; pairs ~= cursor / 2
        total_turns += int((r["backfill_cursor"] or 0) // 2)
    degraded_pct = (
        round(by_state["degraded"] / total * 100.0, 1) if total > 0 else 0.0
    )
    return {
        "user_id": user_id,
        "total_sessions": total,
        "by_state": by_state,
        "by_source": by_source,
        "total_turns_indexed": total_turns,
        "degraded_sessions_pct": degraded_pct,
    }


def list_backfillable_sessions(user_id: str) -> list[dict]:
    """Sprint 7: sessions eligible for backfill (not currently running, not done).

    Returns rows with id, title, current state, total messages.
    """
    ensure_phase_c_schema()
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        rows = list(con.execute(
            "SELECT s.id, s.title, s.backfill_state, "
            "(SELECT COUNT(*) FROM chat_messages WHERE session_id = s.id) AS msg_count "
            "FROM chat_sessions s WHERE s.user_id = ? "
            "AND COALESCE(s.backfill_state, 'idle') NOT IN ('running')",
            (user_id,),
        ))
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "state": r["backfill_state"] or "idle",
            "message_count": int(r["msg_count"] or 0),
        }
        for r in rows
    ]


def get_backfill_status(session_id: str, user_id: str) -> Optional[dict]:
    """Return current backfill progress for a session, or None if not found."""
    meta = get_session_meta(session_id, user_id)
    if not meta:
        return None
    total = chat_store.get_message_count(session_id)
    cursor = int(meta.get("backfill_cursor") or 0)
    state = meta.get("backfill_state") or "idle"
    return {
        "session_id": session_id,
        "state": state,
        "cursor": cursor,
        "total_messages": total,
        "progress_pct": round((cursor / total * 100.0), 1) if total > 0 else 0.0,
        "remaining": max(0, total - cursor),
        "job_id": meta.get("backfill_job_id"),
        "error": meta.get("backfill_error"),
        "backfilled_at": meta.get("backfilled_at"),
    }


def is_capture_enabled(session_id: str) -> bool:
    """Read capture_enabled flag for a session — defaults True if column missing."""
    try:
        ensure_phase_c_schema()
        path = get_settings().sqlite_path
        with sqlite3.connect(path) as con:
            row = con.execute(
                "SELECT capture_enabled FROM chat_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return True
        return bool(row[0])
    except Exception as exc:
        logger.warning("capture flag read failed for %s: %s", session_id, exc)
        return True


# ---------------------------------------------------------------------------
# Session-level blueprint
# ---------------------------------------------------------------------------

def _session_blueprint_memory_id(session_id: str) -> str:
    """Deterministic memory_id for the session-level blueprint."""
    return f"session_{session_id}"


def _build_transcript(messages: list[dict], char_cap: int = 0) -> str:
    """Render messages as a transcript for blueprint extraction.

    Segment-aware: each message's content is parsed into typed Segments and
    rendered with markdown fences preserved, so code blocks, tables, mermaid
    diagrams, and inline markdown survive intact through to the blueprint LLM.

    `char_cap` is a hard safety bound for pathological inputs only.
    `0` means unbounded (subject to the global blueprint_transcript_max_chars
    ceiling). The old default of 24_000 caused tail truncation; sizing is now
    handled by chunked extraction in `_extract_chunked`.
    """
    from apps.shail import segments as _segs

    settings = get_settings()
    if char_cap <= 0:
        char_cap = settings.blueprint_transcript_max_chars or 10**12

    typed_segments: list[_segs.Segment] = []
    truncated = False
    running = 0
    for m in messages:
        role = (m.get("role") or "?").lower()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        msg_segments = _segs.parse_segments(content)
        for seg in msg_segments:
            seg.role = role
            seg_chars = seg.char_len()
            if char_cap and running + seg_chars > char_cap:
                truncated = True
                break
            typed_segments.append(seg)
            running += seg_chars
        if truncated:
            break

    rendered = _segs.render_for_llm(typed_segments)
    if truncated:
        rendered = rendered + "\n\n[transcript truncated at safety cap]"
    return rendered


def _build_transcript_segments(messages: list[dict]):
    """Build a typed Segment list spanning the whole session (no truncation).

    Returns (segments, total_chars). Used by callers that need the structured
    projection — capture stores, status pages, exporters.
    """
    from apps.shail import segments as _segs
    out: list[_segs.Segment] = []
    for m in messages:
        role = (m.get("role") or "?").lower()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        msg_segments = _segs.parse_segments(content)
        for seg in msg_segments:
            seg.role = role
            out.append(seg)
    return out, _segs.total_chars(out)


def _slice_transcript_windows(
    transcript: str, window_size: int, overlap: int,
) -> list[str]:
    """Slice transcript into overlapping windows. Last window may be shorter."""
    if not transcript:
        return []
    if len(transcript) <= window_size:
        return [transcript]
    if overlap >= window_size:
        overlap = window_size // 4  # safety
    step = window_size - overlap
    windows: list[str] = []
    pos = 0
    while pos < len(transcript):
        end = min(pos + window_size, len(transcript))
        windows.append(transcript[pos:end])
        if end == len(transcript):
            break
        pos += step
    return windows


async def generate_session_blueprint(
    session_id: str,
    user_id: str,
    *,
    char_cap: int = 0,
    window_size: Optional[int] = None,
    window_overlap: Optional[int] = None,
) -> Optional[dict]:
    """Sliding-window session blueprint with dynamic, segment-aware extraction.

    The transcript is built segment-by-segment so code, tables, mermaid, and
    inline markdown survive into the blueprint prompt. Window size + overlap
    default to `dynamic_sizing.compute_window_size`, which derives them from
    the live LLM context window rather than the legacy 8K hard-coded value.

    `char_cap` is a safety bound only (default = settings ceiling, typically
    millions of chars). Real sizing comes from `_extract_chunked`. Long
    sessions are NOT silently truncated — every chunk is extracted and merged.

    Returns the final merged blueprint dict or None on failure. Idempotent.
    """
    from apps.shail import pipeline_status as _ps

    messages = chat_store.get_messages(session_id, user_id, limit=10_000)
    if not messages:
        return None

    memory_id = _session_blueprint_memory_id(session_id)
    namespace = f"user_{user_id}"

    # Build full segment-aware transcript. `0` lets the settings ceiling apply
    # rather than the legacy 24K cap.
    segments, total_chars = _build_transcript_segments(messages)
    if total_chars < 40:
        return None
    transcript = _build_transcript(messages, char_cap=char_cap or 0)

    _ps.mark_stage(
        memory_id, "transcript_ready", "done",
        size_bytes=len(transcript),
        detail={
            "messages": len(messages),
            "segments": len(segments),
            "char_total": total_chars,
        },
    )

    # Persist the raw transcript so the queue worker can recover if anything
    # below this point fails (Ollama down, parse error, etc.).
    try:
        from apps.shail import raw_transcripts as _rt
        _rt.save(
            memory_id=memory_id,
            user_id=user_id,
            namespace=namespace,
            content_type="ai_conversation",
            content=transcript,
            metadata={
                "session_id": session_id,
                "message_count": len(messages),
                "segment_count": len(segments),
            },
            segments=segments,
        )
    except Exception as exc:
        logger.warning("session raw transcript save failed for %s: %s", session_id, exc)

    # If caller passed explicit window sizing, honor it; otherwise let
    # generate_blueprint pick chunk boundaries via dynamic_sizing.
    if window_size and window_overlap is not None:
        windows = _slice_transcript_windows(transcript, window_size, window_overlap)
        if len(windows) <= 1:
            bp = await generate_blueprint(
                memory_id, content=transcript,
                content_type="ai_conversation",
                user_id=user_id, namespace=namespace,
            )
        else:
            window_bps: list[dict] = []
            for idx, win in enumerate(windows):
                win_memory_id = f"{memory_id}_w{idx}"
                wbp = await generate_blueprint(
                    win_memory_id, content=win,
                    content_type="ai_conversation",
                    user_id=user_id, namespace=namespace,
                )
                if wbp:
                    window_bps.append(wbp)
            if not window_bps:
                return None
            merged = window_bps[0]
            for wbp in window_bps[1:]:
                merged = _merge_blueprints(merged, wbp)
            save_blueprint(
                memory_id, merged,
                user_id=user_id, namespace=namespace,
                content_type="ai_conversation",
            )
            bp = merged
    else:
        # Default: hand the full transcript to generate_blueprint which decides
        # single vs. chunked based on dynamic budget.
        bp = await generate_blueprint(
            memory_id, content=transcript,
            content_type="ai_conversation",
            user_id=user_id, namespace=namespace,
        )

    if bp:
        path = get_settings().sqlite_path
        with sqlite3.connect(path) as con:
            con.execute(
                "UPDATE chat_sessions SET blueprint_memory_id = ? WHERE id = ?",
                (memory_id, session_id),
            )
    return bp


# ---------------------------------------------------------------------------
# Per-turn re-indexing (idempotent)
# ---------------------------------------------------------------------------

# Per-turn vector content cap. Raised in Sprint 3 (12000 ← 6000) to avoid
# silently truncating long answers in vector store.
_VECTOR_CONTENT_CAP = 12_000


def _reindex_turn(
    *,
    user_id: str,
    session_id: str,
    session_title: str,
    user_msg: dict,
    asst_msg: dict,
) -> bool:
    """Index one Q+A pair into the past-chat namespace.

    Idempotent: re-running with the same assistant_message_id overwrites
    the existing record (same id key in the vector store).
    Kept for single-turn live indexing path; backfill uses _reindex_turns_batch.
    """
    # Lazy import — avoid circular deps
    from apps.shail.chat_api import _index_past_chat_turn

    try:
        _index_past_chat_turn(
            user_id=user_id,
            session_id=session_id,
            user_msg_id=user_msg["id"],
            assistant_msg_id=asst_msg["id"],
            user_text=user_msg.get("content", ""),
            assistant_text=asst_msg.get("content", ""),
            session_title=session_title,
        )
        return True
    except Exception as exc:
        logger.warning("reindex turn failed (%s): %s", asst_msg.get("id"), exc)
        return False


def _reindex_turns_batch(
    *,
    user_id: str,
    session_id: str,
    session_title: str,
    pairs: list[tuple[dict, dict]],
) -> tuple[int, bool, Optional[str]]:
    """Batch-index Q+A pairs in a single ingest() call.

    Returns (indexed_count, degraded_mode, degraded_reason).
    - indexed_count: how many records the vector store accepted (non-zero embeds)
    - degraded_mode: True if Ollama/embedder appears unavailable (all-zero result)
    - degraded_reason: human-readable cause, or None

    FTS5 rows are populated automatically by the chat_messages trigger when
    messages were originally inserted — no extra work needed here for keyword
    fallback.
    """
    if not pairs:
        return 0, False, None

    from shail.memory.rag import ingest

    records: list[dict] = []
    namespace = f"chat_{user_id}"
    for user_msg, asst_msg in pairs:
        u = user_msg.get("content", "")
        a = asst_msg.get("content", "")
        content = f"Q: {u}\n\nA: {a}"
        record_id = asst_msg["id"]
        records.append({
            "id": record_id,
            "content": content[:_VECTOR_CONTENT_CAP],
            "namespace": namespace,
            "metadata": {
                "id": record_id,
                "type": "chat_turn",
                "session_id": session_id,
                "session_title": session_title,
                "user_message_id": user_msg["id"],
                "assistant_message_id": asst_msg["id"],
                "title": session_title,
                "summary": u[:200],
                "namespace": namespace,
            },
        })

    try:
        # ingest() batches the embed_texts() call internally — one Ollama
        # round-trip per ingest() call, not per pair.
        indexed = ingest(records=records)
    except Exception as exc:
        logger.error("batch reindex ingest() raised: %s", exc)
        return 0, True, f"ingest_exception: {exc}"

    if indexed == 0 and len(records) > 0:
        # All embeddings came back zero — Ollama down or embedder misconfigured.
        # FTS rows already exist via chat_messages triggers; content remains
        # keyword-searchable. Mark degraded so caller surfaces the state.
        return 0, True, "embedder_unavailable_or_all_zero_vectors"
    if indexed < len(records):
        logger.warning(
            "batch reindex partial: %d/%d records embedded (some zero vectors dropped)",
            indexed, len(records),
        )
    return indexed, False, None


# ---------------------------------------------------------------------------
# Backfill driver
# ---------------------------------------------------------------------------

def _pair_user_assistant(messages: list[dict]) -> tuple[list[tuple[dict, dict]], int]:
    """Pair user msg → next assistant msg. Returns (pairs, trailing_unmatched)."""
    pairs: list[tuple[dict, dict]] = []
    skipped = 0
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") == "user":
            j = i + 1
            asst = None
            while j < len(messages):
                if messages[j].get("role") == "assistant":
                    asst = messages[j]
                    break
                j += 1
            if asst is not None:
                pairs.append((m, asst))
                i = j + 1
                continue
            skipped += 1
        i += 1
    return pairs, skipped


async def backfill_session(
    session_id: str,
    user_id: str,
    *,
    include_blueprint: bool = True,
    char_cap: int = 24_000,
    resume: bool = True,
) -> BackfillSummary:
    """Sprint 2: chunked, resumable backfill.

    Streams messages in pages of `_BACKFILL_BATCH_SIZE`, pairs each page locally,
    calls ingest() per page (one Ollama batch round-trip), commits cursor after
    each page. If `resume=True` and `backfill_cursor > 0`, continues from there.

    On crash mid-run: re-issuing while state='failed' resumes from cursor.
    Errors stamp state='failed' + backfill_error so client can inspect.
    """
    started = datetime.now(timezone.utc)
    summary = BackfillSummary(session_id=session_id)

    ensure_phase_c_schema()
    session = chat_store.get_session(session_id, user_id)
    if not session:
        summary.errors.append("session_not_found")
        return summary

    meta = get_session_meta(session_id, user_id)
    prior_state = (meta or {}).get("backfill_state") or "idle"
    # Resume only makes sense for an interrupted run (state='failed'). For
    # state in {'done','degraded','idle'} a re-issue is a full re-run from 0
    # so the operation is idempotent from the user's perspective.
    if resume and prior_state == "failed":
        cursor = int((meta or {}).get("backfill_cursor") or 0)
    else:
        cursor = 0
        _set_backfill_state(session_id, cursor=0, error="")

    _set_backfill_state(session_id, state="running", error="")

    total_msgs = chat_store.get_message_count(session_id)
    summary.turns_seen = total_msgs

    title = session.get("title", "Untitled chat")
    aggregate_degraded = False
    degraded_reason: Optional[str] = None

    try:
        # Stream pages of BATCH_SIZE messages. We need a small look-back so a
        # user message at the page boundary still pairs with its assistant
        # reply on the next page — use a 1-message overlap and skip already-
        # processed messages by tracking processed message ids.
        while cursor < total_msgs:
            page = chat_store.get_messages_paginated(
                session_id, user_id,
                offset=cursor, limit=_BACKFILL_BATCH_SIZE + 1,  # +1 for boundary pair
            )
            if not page:
                break

            pairs, skipped = _pair_user_assistant(page)
            summary.turns_skipped += skipped

            advance = min(len(page), _BACKFILL_BATCH_SIZE)

            # Trim pairs whose assistant message falls past advance boundary —
            # those will be picked up next iteration when the user message is
            # included in the next page.
            page_first_ids = {m["id"] for m in page[:advance]}
            pairs_in_page = [(u, a) for (u, a) in pairs if u["id"] in page_first_ids]

            if pairs_in_page:
                indexed, degraded, reason = _reindex_turns_batch(
                    user_id=user_id,
                    session_id=session_id,
                    session_title=title,
                    pairs=pairs_in_page,
                )
                summary.turns_indexed += indexed
                summary.raw_transcript_chars += sum(
                    len((u.get("content") or "")) + len((a.get("content") or ""))
                    for u, a in pairs_in_page
                )
                if degraded:
                    aggregate_degraded = True
                    degraded_reason = reason

            cursor += advance
            _set_backfill_state(session_id, cursor=cursor)
    except Exception as exc:
        _set_backfill_state(
            session_id, state="failed", error=f"{type(exc).__name__}: {exc}",
        )
        summary.errors.append(f"chunk_loop: {exc}")
        summary.duration_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
        return summary

    if aggregate_degraded:
        summary.degraded_mode = True
        summary.degraded_reason = degraded_reason
        summary.fts_fallback_used = chat_store.fts_available()
        summary.errors.append(f"degraded: {degraded_reason}")

    # Session-level blueprint:
    #   - If Ollama is up + vectors succeeded → generate inline (fast path).
    #   - If degraded (Ollama down) OR inline generation fails → enqueue a
    #     queued job (Plan B6) so the worker retries automatically once
    #     Ollama is back. Transcript is already safe in chat_messages.
    blueprint_inline_ok = False
    if include_blueprint and summary.turns_indexed > 0 and not aggregate_degraded:
        try:
            bp = await generate_session_blueprint(session_id, user_id, char_cap=char_cap)
            if bp:
                summary.blueprint_generated = True
                summary.blueprint_memory_id = _session_blueprint_memory_id(session_id)
                blueprint_inline_ok = True
                # Best-effort auto-redact for the inline-success path so users
                # don't have to wait for the queue worker on the happy path.
                try:
                    from apps.shail.blueprint_queue import compute_quality_score
                    score = compute_quality_score(bp)
                    if (
                        score >= get_settings().blueprint_quality_threshold
                        and _get_session_auto_redact_flag(session_id)
                    ):
                        redact_session_transcript(session_id, user_id)
                except Exception:
                    pass  # auto-redact failures are non-fatal
        except Exception as exc:
            summary.errors.append(f"blueprint: {exc}")
    if include_blueprint and not blueprint_inline_ok:
        # Either degraded OR inline failed — make sure a queue job exists
        # so the worker picks this up when Ollama recovers.
        try:
            from apps.shail.blueprint_queue import enqueue as _bq_enqueue
            _bq_enqueue(
                memory_id=_session_blueprint_memory_id(session_id),
                session_id=session_id,
                user_id=user_id,
                content_type="chat_session",
            )
        except Exception as exc:
            summary.errors.append(f"blueprint_enqueue: {exc}")

    # Stamp completion — backfilled_at only on a clean 'done' run.
    # Degraded runs (Ollama down, zero vectors) leave backfilled_at NULL
    # so callers can distinguish "fully indexed" from "keyword-only indexed".
    final_state = "degraded" if aggregate_degraded else "done"
    path = get_settings().sqlite_path
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as con:
        if final_state == "done":
            con.execute(
                "UPDATE chat_sessions SET backfilled_at = ?, backfill_state = ? WHERE id = ?",
                (now_iso, final_state, session_id),
            )
        else:
            # Degraded: update state only; preserve any prior backfilled_at
            con.execute(
                "UPDATE chat_sessions SET backfill_state = ? WHERE id = ?",
                (final_state, session_id),
            )

    summary.duration_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
    return summary


# ---------------------------------------------------------------------------
# Timeline reconstruction
# ---------------------------------------------------------------------------

def build_timeline(session_id: str, user_id: str) -> Optional[dict]:
    """Build a timeline view of the session: turns + blueprint atoms.

    Returns a dict with:
      - session: session metadata
      - turns: list of {user_msg, asst_msg, citations}
      - blueprint: session-level blueprint (or None)
      - retention: retention_policy + raw_available
    """
    session = get_session_meta(session_id, user_id)
    if not session:
        return None

    retention = session.get("retention_policy", "keep_raw")
    raw_available = retention != "transcript_deleted"

    turns: list[dict] = []
    if raw_available:
        messages = chat_store.get_messages(session_id, user_id, limit=10_000)
        i = 0
        while i < len(messages):
            m = messages[i]
            if m.get("role") == "user":
                turn: dict[str, Any] = {"user_msg": m, "asst_msg": None}
                j = i + 1
                while j < len(messages):
                    if messages[j].get("role") == "assistant":
                        turn["asst_msg"] = messages[j]
                        break
                    j += 1
                turns.append(turn)
                i = j + 1 if turn["asst_msg"] else i + 1
            else:
                i += 1

    bp_memory_id = session.get("blueprint_memory_id") or _session_blueprint_memory_id(session_id)
    blueprint = get_blueprint(bp_memory_id)

    return {
        "session": {
            "id": session["id"],
            "title": session["title"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "pinned": bool(session.get("pinned")),
            "retention_policy": retention,
            "capture_enabled": bool(session.get("capture_enabled", 1)),
            "blueprint_memory_id": session.get("blueprint_memory_id"),
            "backfilled_at": session.get("backfilled_at"),
        },
        "turns": turns,
        "blueprint": blueprint,
        "retention": {
            "policy": retention,
            "raw_available": raw_available,
        },
    }


# ---------------------------------------------------------------------------
# Raw transcript redaction (retention policy enforcement)
# ---------------------------------------------------------------------------

def redact_session_transcript(session_id: str, user_id: str) -> dict[str, Any]:
    """Delete raw chat_messages rows for a session. Blueprint is preserved.

    Hard guard: refuses to redact unless the session has a blueprint stored,
    so the user cannot accidentally destroy a session with no synthesized
    memory of it. Also flips retention_policy to 'transcript_deleted'.
    """
    ensure_phase_c_schema()
    meta = get_session_meta(session_id, user_id)
    if not meta:
        return {"ok": False, "reason": "session_not_found"}

    bp_id = meta.get("blueprint_memory_id") or _session_blueprint_memory_id(session_id)
    if not get_blueprint(bp_id):
        return {"ok": False, "reason": "no_blueprint_stored"}

    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        cur = con.execute(
            "DELETE FROM chat_messages WHERE session_id = ?",
            (session_id,),
        )
        deleted = cur.rowcount
        con.execute(
            "UPDATE chat_sessions SET retention_policy = 'transcript_deleted' "
            "WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
    return {"ok": True, "messages_deleted": deleted, "blueprint_kept": bp_id}
