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
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


# ── Schema init ───────────────────────────────────────────────────────────────

def init_auth_db() -> None:
    """Create users and api_keys tables if they don't already exist."""
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
        """)


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


def get_user_by_api_key(key: str) -> Optional[str]:
    """Return user_id for a valid (non-revoked) API key, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT user_id FROM api_keys WHERE key = ? AND revoked = 0",
            (key,),
        ).fetchone()
    return row["user_id"] if row else None


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
    return cur.rowcount > 0


def touch_api_key_last_used(key: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute("UPDATE api_keys SET last_used = ? WHERE key = ?", (now, key))
