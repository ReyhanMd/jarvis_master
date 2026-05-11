"""
SHAIL Auth Store
─────────────────
SQLite-backed user accounts and API keys.
Tables are co-located in the existing shail_memory.sqlite3 database.

Tables
------
users     — registered accounts (email, bcrypt password hash)
api_keys  — per-device bearer tokens (prefix "shail_")

All functions are synchronous and thread-safe (SQLite WAL mode).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import bcrypt as _bcrypt

from apps.shail.settings import get_settings

# ── Password hashing ──────────────────────────────────────────────────────────


def _hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── DB connection ─────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    path = get_settings().sqlite_path
    con = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


# ── Schema init ───────────────────────────────────────────────────────────────

def init_auth_db() -> None:
    """Create users, api_keys, user_settings, and ascent tables if they don't already exist."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                email         TEXT UNIQUE NOT NULL,
                name          TEXT,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                last_seen     TEXT
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                key        TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL REFERENCES users(id),
                label      TEXT,
                created_at TEXT NOT NULL,
                last_used  TEXT,
                revoked    INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id           TEXT PRIMARY KEY REFERENCES users(id),
                capture_enabled   INTEGER DEFAULT 1,
                blocked_domains   TEXT DEFAULT '[]',
                ollama_model      TEXT DEFAULT '',
                external_api_key  TEXT DEFAULT '',
                tier              TEXT DEFAULT 'free',
                openai_api_key    TEXT DEFAULT '',
                anthropic_api_key TEXT DEFAULT '',
                active_provider   TEXT DEFAULT 'ollama',
                active_model      TEXT DEFAULT '',
                updated_at        TEXT
            );

            -- Ascents: top-level user goals (e.g. "Build auth subsystem")
            CREATE TABLE IF NOT EXISTS ascents (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users(id),
                name        TEXT NOT NULL,
                description TEXT,
                status      TEXT DEFAULT 'active',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            -- Deliverables: outcome-level chunks within an ascent
            CREATE TABLE IF NOT EXISTS deliverables (
                id          TEXT PRIMARY KEY,
                ascent_id   TEXT NOT NULL REFERENCES ascents(id) ON DELETE CASCADE,
                text        TEXT NOT NULL,
                description TEXT,
                order_index INTEGER NOT NULL,
                completed   INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            );

            -- Todos: atomic actionable items inside a deliverable
            CREATE TABLE IF NOT EXISTS todos (
                id             TEXT PRIMARY KEY,
                deliverable_id TEXT NOT NULL REFERENCES deliverables(id) ON DELETE CASCADE,
                text           TEXT NOT NULL,
                order_index    INTEGER NOT NULL,
                completed      INTEGER DEFAULT 0,
                completed_at   TEXT,
                created_at     TEXT NOT NULL
            );

            -- Memory <-> ascent/deliverable/todo links (foundation for the
            -- post-v1 inject-suggestion widget). Nullable refs allow linking
            -- a memory at any granularity.
            CREATE TABLE IF NOT EXISTS ascent_memory_links (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ascent_id      TEXT REFERENCES ascents(id) ON DELETE CASCADE,
                deliverable_id TEXT REFERENCES deliverables(id) ON DELETE CASCADE,
                todo_id        TEXT REFERENCES todos(id) ON DELETE CASCADE,
                memory_id      TEXT NOT NULL,
                created_at     TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ascents_user ON ascents(user_id);
            CREATE INDEX IF NOT EXISTS idx_deliverables_ascent ON deliverables(ascent_id);
            CREATE INDEX IF NOT EXISTS idx_todos_deliverable ON todos(deliverable_id);
            CREATE INDEX IF NOT EXISTS idx_links_ascent ON ascent_memory_links(ascent_id);
            CREATE INDEX IF NOT EXISTS idx_links_deliverable ON ascent_memory_links(deliverable_id);

            -- Persistent chat sessions for the dashboard /chat page.
            -- Multi-session per user; each session keeps its own message thread.
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users(id),
                title       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                pinned      INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                user_id     TEXT NOT NULL,
                role        TEXT NOT NULL,         -- "user" | "assistant"
                content     TEXT NOT NULL,
                citations   TEXT,                  -- JSON: [{type,id,title,url}]
                provider    TEXT,
                model       TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at);

            -- MCP connections — one row per (user, provider) pair.
            -- access_token is stored in plaintext for v1; encryption-at-rest
            -- is tracked under Block 10 (TODO in llm.py).
            CREATE TABLE IF NOT EXISTS mcp_connections (
                user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                provider       TEXT NOT NULL,           -- "drive" | "notion" | "github" | "gmail"
                access_token   TEXT NOT NULL,
                refresh_token  TEXT,
                expires_at     TEXT,
                scope          TEXT,
                metadata       TEXT,                    -- JSON; account email, etc.
                connected_at   TEXT NOT NULL,
                last_synced    TEXT,
                indexed_count  INTEGER DEFAULT 0,
                index_status   TEXT DEFAULT 'idle',     -- idle | indexing | error
                index_error    TEXT,
                PRIMARY KEY (user_id, provider)
            );

            -- Per-user, per-provider preferences (e.g. Gmail label selection).
            CREATE TABLE IF NOT EXISTS mcp_settings (
                user_id     TEXT NOT NULL,
                provider    TEXT NOT NULL,
                settings    TEXT NOT NULL,              -- JSON
                updated_at  TEXT NOT NULL,
                PRIMARY KEY (user_id, provider)
            );
        """)
        # Forward-compat ALTERs — safe no-op if column already exists.
        # Each ALTER is its own try because SQLite has no IF NOT EXISTS for ADD COLUMN.
        for ddl in (
            "ALTER TABLE user_settings ADD COLUMN tier TEXT DEFAULT 'free'",
            "ALTER TABLE user_settings ADD COLUMN openai_api_key TEXT DEFAULT ''",
            "ALTER TABLE user_settings ADD COLUMN anthropic_api_key TEXT DEFAULT ''",
            "ALTER TABLE user_settings ADD COLUMN active_provider TEXT DEFAULT 'ollama'",
            "ALTER TABLE user_settings ADD COLUMN active_model TEXT DEFAULT ''",
        ):
            try:
                con.execute(ddl)
            except Exception:
                pass


# ── User CRUD ─────────────────────────────────────────────────────────────────

def create_user(email: str, password: str, name: str = "") -> dict:
    """Create a new user. Returns user dict. Raises ValueError if email taken."""
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    hashed = _hash_password(password)
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO users (id, email, name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email.lower().strip(), name, hashed, now),
            )
    except sqlite3.IntegrityError:
        raise ValueError(f"Email already registered: {email}")
    return {"id": user_id, "email": email, "name": name, "created_at": now}


def get_user_by_email(email: str) -> Optional[dict]:
    """Return user row or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()
    return dict(row) if row else None


def verify_password(email: str, password: str) -> Optional[dict]:
    """Verify credentials. Returns user dict or None."""
    user = get_user_by_email(email)
    if not user:
        return None
    if not _verify_password(password, user["password_hash"]):
        return None
    return user


def get_user_by_id(user_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def touch_user_last_seen(user_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now, user_id))


# ── API key CRUD ──────────────────────────────────────────────────────────────

def create_api_key(user_id: str, label: str = "") -> str:
    """Generate a new API key for user. Returns the raw key string."""
    key = "shail_" + secrets.token_hex(24)
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT INTO api_keys (key, user_id, label, created_at) VALUES (?, ?, ?, ?)",
            (key, user_id, label, now),
        )
    return key


try:
    from cachetools import TTLCache
    _api_key_cache: "TTLCache[str, Optional[str]]" = TTLCache(maxsize=512, ttl=60)
except Exception:
    _api_key_cache = {}  # type: ignore[assignment]


def get_user_by_api_key(key: str) -> Optional[str]:
    """Return user_id for a valid (non-revoked) API key, or None.

    Cached for 60s to avoid hitting SQLite on every browser-extension capture.
    Cache is invalidated by revoke_api_key.
    """
    if key in _api_key_cache:
        return _api_key_cache[key]
    with _conn() as con:
        row = con.execute(
            "SELECT user_id FROM api_keys WHERE key = ? AND revoked = 0",
            (key,),
        ).fetchone()
    user_id = row["user_id"] if row else None
    try:
        _api_key_cache[key] = user_id
    except Exception:
        pass
    return user_id


def _invalidate_api_key_cache(key: str) -> None:
    try:
        if key in _api_key_cache:
            del _api_key_cache[key]
    except Exception:
        pass


def list_api_keys(user_id: str) -> List[dict]:
    """List all non-revoked keys for a user (key prefix only, not full key)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT key, label, created_at, last_used FROM api_keys WHERE user_id = ? AND revoked = 0 ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [
        {
            "key_prefix": row["key"][:14] + "…",  # "shail_xxxxxxxx…"
            "label": row["label"] or "",
            "created_at": row["created_at"],
            "last_used": row["last_used"],
        }
        for row in rows
    ]


def revoke_api_key(key: str, user_id: str) -> bool:
    """Revoke a key only if it belongs to user_id. Returns True if revoked."""
    with _conn() as con:
        cur = con.execute(
            "UPDATE api_keys SET revoked = 1 WHERE key = ? AND user_id = ?",
            (key, user_id),
        )
    _invalidate_api_key_cache(key)
    return cur.rowcount > 0


def touch_api_key_last_used(key: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute("UPDATE api_keys SET last_used = ? WHERE key = ?", (now, key))


# ── User settings CRUD ────────────────────────────────────────────────────────

def get_user_settings(user_id: str) -> dict:
    """Return settings for user_id, inserting defaults if the row doesn't exist."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            now = datetime.now(timezone.utc).isoformat()
            con.execute(
                "INSERT OR IGNORE INTO user_settings (user_id, updated_at) VALUES (?, ?)",
                (user_id, now),
            )
            row = con.execute(
                "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
            ).fetchone()
    # Sentinel-safe column reads — newer columns may be NULL even though
    # they were ALTER-added with a default, because old rows pre-date the
    # ALTER. Coalesce here rather than trusting SQLite's DEFAULT.
    keys = row.keys() if hasattr(row, "keys") else []
    def col(name: str, default=""):
        return (row[name] if name in keys and row[name] is not None else default)

    return {
        "capture_enabled":  bool(row["capture_enabled"]),
        "blocked_domains":  json.loads(row["blocked_domains"] or "[]"),
        "ollama_model":     row["ollama_model"] or "",
        "external_api_key": row["external_api_key"] or "",
        "tier":             col("tier", "free"),
        "openai_api_key":   col("openai_api_key", ""),
        "anthropic_api_key": col("anthropic_api_key", ""),
        "active_provider":  col("active_provider", "ollama"),
        "active_model":     col("active_model", ""),
    }


def get_user_tier(user_id: str) -> str:
    """Return 'free' or 'pro' for the given user."""
    with _conn() as con:
        row = con.execute(
            "SELECT tier FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    return (row["tier"] if row and row["tier"] else "free")


def update_user_settings(user_id: str, **kwargs) -> dict:
    """Update one or more settings fields for user_id. Returns updated dict."""
    allowed = {
        "capture_enabled", "blocked_domains", "ollama_model", "external_api_key",
        "tier", "openai_api_key", "anthropic_api_key", "active_provider", "active_model",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_user_settings(user_id)
    now = datetime.now(timezone.utc).isoformat()
    # Ensure row exists
    get_user_settings(user_id)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    # Serialize lists to JSON
    for i, k in enumerate(updates):
        if isinstance(values[i], list):
            values[i] = json.dumps(values[i])
        elif k == "capture_enabled":
            values[i] = int(bool(values[i]))
    with _conn() as con:
        con.execute(
            f"UPDATE user_settings SET {set_clause}, updated_at = ? WHERE user_id = ?",
            (*values, now, user_id),
        )
    return get_user_settings(user_id)
