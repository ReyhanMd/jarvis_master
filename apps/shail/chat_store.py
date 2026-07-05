"""
Chat session + message persistence layer.

Tables (created by `init_auth_db()` in auth_store.py):
    chat_sessions   — one row per conversation (user_id, title, pinned, timestamps)
    chat_messages   — one row per turn (session_id, role, content, citations JSON)

This module owns all reads/writes for those tables. The chat API and the
past-chat RAG indexer both go through here.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from apps.shail.auth_store import _conn

# ── Helpers ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Sessions ────────────────────────────────────────────────────────────────

def create_session(
    user_id: str, title: str = "New chat", *, source: Optional[str] = None,
) -> dict:
    """Create a chat session.

    `source` (Sprint 6): provenance for imported sessions ('chatgpt' | 'claude' |
    'cursor'). NULL for native SHAIL sessions. Requires Phase C schema applied.
    """
    sid = str(uuid.uuid4())
    now = _now()
    with _conn() as con:
        if source is not None:
            con.execute(
                "INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, user_id, title, now, now, source),
            )
        else:
            con.execute(
                "INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, user_id, title, now, now),
            )
    return {"id": sid, "user_id": user_id, "title": title,
            "created_at": now, "updated_at": now, "pinned": False, "source": source}


def get_session(session_id: str, user_id: str) -> Optional[dict]:
    """Returns the session dict if it belongs to user_id, else None."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
    return _row_to_session(row) if row else None


def list_sessions(user_id: str, limit: int = 100) -> list[dict]:
    """Newest first, with message_count + last_message_preview for sidebar."""
    with _conn() as con:
        rows = con.execute(
            """SELECT s.*,
                      (SELECT COUNT(*) FROM chat_messages WHERE session_id = s.id) AS msg_count,
                      (SELECT content FROM chat_messages
                       WHERE session_id = s.id AND role = 'user'
                       ORDER BY created_at DESC LIMIT 1) AS last_user_msg
               FROM chat_sessions s
               WHERE s.user_id = ?
               ORDER BY s.pinned DESC, s.updated_at DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = _row_to_session(r)
        d["message_count"] = int(r["msg_count"] or 0)
        d["preview"] = (r["last_user_msg"] or "")[:120]
        out.append(d)
    return out


def update_session(
    session_id: str, user_id: str,
    *, title: Optional[str] = None, pinned: Optional[bool] = None,
) -> Optional[dict]:
    fields: list[str] = []
    values: list[Any] = []
    if title is not None:
        fields.append("title = ?"); values.append(title)
    if pinned is not None:
        fields.append("pinned = ?"); values.append(1 if pinned else 0)
    if not fields:
        return get_session(session_id, user_id)
    fields.append("updated_at = ?"); values.append(_now())
    values.extend([session_id, user_id])
    with _conn() as con:
        cur = con.execute(
            f"UPDATE chat_sessions SET {', '.join(fields)} WHERE id = ? AND user_id = ?",
            values,
        )
        if cur.rowcount == 0:
            return None
    return get_session(session_id, user_id)


def delete_session(session_id: str, user_id: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
        # CASCADE deletes chat_messages automatically
    return cur.rowcount > 0


def touch_session(session_id: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )


def _row_to_session(row: sqlite3.Row) -> dict:
    # `source` (Sprint 6) may be absent on older DBs predating Phase C schema.
    source: Optional[str] = None
    try:
        source = row["source"]
    except (KeyError, IndexError):
        pass
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "pinned": bool(row["pinned"]),
        "source": source,
    }


# ── Messages ────────────────────────────────────────────────────────────────

def append_message(
    session_id: str,
    user_id: str,
    role: str,
    content: str,
    *,
    citations: Optional[list] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Append a single message. Bumps the session's updated_at as a side effect."""
    if role not in ("user", "assistant"):
        raise ValueError(f"invalid role: {role}")
    mid = str(uuid.uuid4())
    now = _now()
    cit_json = json.dumps(citations) if citations else None
    with _conn() as con:
        con.execute(
            "INSERT INTO chat_messages "
            "(id, session_id, user_id, role, content, citations, provider, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, session_id, user_id, role, content, cit_json, provider, model, now),
        )
        con.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
    return {
        "id": mid, "session_id": session_id, "user_id": user_id, "role": role,
        "content": content, "citations": citations or [],
        "provider": provider, "model": model, "created_at": now,
    }


def get_messages(session_id: str, user_id: str, limit: int = 500) -> list[dict]:
    """Full thread, oldest first. Returns empty list if session not owned by user."""
    with _conn() as con:
        owner = con.execute(
            "SELECT 1 FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        if not owner:
            return []
        rows = con.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? "
            "ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [_row_to_message(r) for r in rows]


def get_message_count(session_id: str) -> int:
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) AS c FROM chat_messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return int(row["c"]) if row else 0


def get_message(message_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM chat_messages WHERE id = ?", (message_id,),
        ).fetchone()
    return _row_to_message(row) if row else None


def get_messages_paginated(
    session_id: str, user_id: str, *, offset: int = 0, limit: int = 50,
) -> list[dict]:
    """Streaming-friendly page of messages, oldest first. Used by chunked backfill."""
    with _conn() as con:
        owner = con.execute(
            "SELECT 1 FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        if not owner:
            return []
        rows = con.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? "
            "ORDER BY created_at ASC LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        ).fetchall()
    return [_row_to_message(r) for r in rows]


# ── FTS5 fallback for chat content ──────────────────────────────────────────

def _fts5_available(con: sqlite3.Connection) -> bool:
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        con.execute("DROP TABLE IF EXISTS _fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def ensure_chat_fts_schema() -> None:
    """Idempotent: create chat_messages_fts virtual table + triggers.

    Provides keyword fallback when vector indexing is unavailable (Ollama down).
    Safe to call repeatedly. On first creation, backfills existing chat_messages
    rows into the FTS index.
    """
    with _conn() as con:
        if not _fts5_available(con):
            return  # FTS5 not compiled in this SQLite build — silent skip
        existing = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages_fts'"
        ).fetchone()
        first_time = existing is None
        # Standalone (non-content-table) FTS5 so we can store metadata columns
        # with names that differ from chat_messages. Triggers keep it synced.
        con.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chat_messages_fts USING fts5(
                content,
                session_id UNINDEXED,
                user_id UNINDEXED,
                message_id UNINDEXED,
                role UNINDEXED
            );
            CREATE TRIGGER IF NOT EXISTS chat_messages_ai
            AFTER INSERT ON chat_messages BEGIN
                INSERT INTO chat_messages_fts(rowid, content, session_id, user_id, message_id, role)
                VALUES (new.rowid, new.content, new.session_id, new.user_id, new.id, new.role);
            END;
            CREATE TRIGGER IF NOT EXISTS chat_messages_ad
            AFTER DELETE ON chat_messages BEGIN
                DELETE FROM chat_messages_fts WHERE rowid = old.rowid;
            END;
            CREATE TRIGGER IF NOT EXISTS chat_messages_au
            AFTER UPDATE ON chat_messages BEGIN
                DELETE FROM chat_messages_fts WHERE rowid = old.rowid;
                INSERT INTO chat_messages_fts(rowid, content, session_id, user_id, message_id, role)
                VALUES (new.rowid, new.content, new.session_id, new.user_id, new.id, new.role);
            END;
        """)
        if first_time:
            # Populate FTS with pre-existing chat_messages rows so historical
            # content becomes keyword-searchable immediately.
            con.execute(
                "INSERT INTO chat_messages_fts(rowid, content, session_id, user_id, message_id, role) "
                "SELECT rowid, content, session_id, user_id, id, role FROM chat_messages"
            )


def fts_available() -> bool:
    """True if chat_messages_fts virtual table exists and is queryable."""
    with _conn() as con:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages_fts'"
        ).fetchone()
    return row is not None


def search_chat_fts(
    user_id: str, query: str, *, limit: int = 20, session_id: Optional[str] = None,
) -> list[dict]:
    """Keyword search over chat content via FTS5. Returns hits with content + metadata.

    Used as fallback retrieval when vector search is unavailable. Returns empty
    list if FTS5 not compiled in or table missing.
    """
    if not fts_available() or not query.strip():
        return []
    # Sanitize: FTS5 query syntax — escape double quotes by doubling them
    safe_q = query.replace('"', '""')
    with _conn() as con:
        if session_id:
            rows = con.execute(
                "SELECT message_id, session_id, role, content, "
                "bm25(chat_messages_fts) AS rank "
                "FROM chat_messages_fts "
                "WHERE chat_messages_fts MATCH ? AND user_id = ? AND session_id = ? "
                "ORDER BY rank LIMIT ?",
                (f'"{safe_q}"', user_id, session_id, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT message_id, session_id, role, content, "
                "bm25(chat_messages_fts) AS rank "
                "FROM chat_messages_fts "
                "WHERE chat_messages_fts MATCH ? AND user_id = ? "
                "ORDER BY rank LIMIT ?",
                (f'"{safe_q}"', user_id, limit),
            ).fetchall()
    return [
        {
            "message_id": r["message_id"],
            "session_id": r["session_id"],
            "role": r["role"],
            "content": r["content"],
            "rank": float(r["rank"]) if r["rank"] is not None else 0.0,
        }
        for r in rows
    ]


def _row_to_message(row: sqlite3.Row) -> dict:
    citations: list = []
    if row["citations"]:
        try:
            citations = json.loads(row["citations"])
        except json.JSONDecodeError:
            citations = []
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "user_id": row["user_id"],
        "role": row["role"],
        "content": row["content"],
        "citations": citations,
        "provider": row["provider"],
        "model": row["model"],
        "created_at": row["created_at"],
    }
