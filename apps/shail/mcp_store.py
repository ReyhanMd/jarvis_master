"""
MCP connection storage layer.

Owns the `mcp_connections` and `mcp_settings` tables. The MCP router
(mcp_api.py) and the per-provider modules (mcp/drive.py, github.py,
notion.py, gmail.py) all go through here for state.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from apps.shail.auth_store import _conn
from apps.shail.crypto import encrypt as _enc, decrypt as _dec

VALID_PROVIDERS = ("drive", "notion", "github", "gmail")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Connection CRUD ────────────────────────────────────────────────────────

def save_connection(
    user_id: str,
    provider: str,
    *,
    access_token: str,
    refresh_token: Optional[str] = None,
    expires_at: Optional[str] = None,
    scope: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    now = _now()
    meta_json = json.dumps(metadata or {})
    # Encrypt-at-rest. encrypt() is idempotent + None-safe + plaintext-safe,
    # so re-saving an already-encrypted token doesn't re-wrap or break it.
    enc_access  = _enc(access_token)
    enc_refresh = _enc(refresh_token)
    with _conn() as con:
        con.execute(
            """INSERT INTO mcp_connections
               (user_id, provider, access_token, refresh_token, expires_at, scope,
                metadata, connected_at, last_synced, indexed_count, index_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, 'idle')
               ON CONFLICT(user_id, provider) DO UPDATE SET
                   access_token = excluded.access_token,
                   refresh_token = COALESCE(excluded.refresh_token, mcp_connections.refresh_token),
                   expires_at = excluded.expires_at,
                   scope = excluded.scope,
                   metadata = excluded.metadata,
                   connected_at = excluded.connected_at""",
            (user_id, provider, enc_access, enc_refresh, expires_at, scope, meta_json, now),
        )
    return get_connection(user_id, provider) or {}


def get_connection(user_id: str, provider: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM mcp_connections WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        ).fetchone()
    return _row_to_conn(row) if row else None


def list_connections(user_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM mcp_connections WHERE user_id = ? ORDER BY connected_at DESC",
            (user_id,),
        ).fetchall()
    return [_row_to_conn(r) for r in rows]


def delete_connection(user_id: str, provider: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM mcp_connections WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        )
    return cur.rowcount > 0


def update_index_status(
    user_id: str, provider: str,
    *, status: str,
    indexed_count: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    fields: list[str] = ["index_status = ?"]
    values: list = [status]
    if indexed_count is not None:
        fields.append("indexed_count = ?"); values.append(indexed_count)
    if error is not None:
        fields.append("index_error = ?"); values.append(error)
    if status == "idle" and error is None:
        fields.append("index_error = NULL")
        fields.append("last_synced = ?"); values.append(_now())
    values.extend([user_id, provider])
    with _conn() as con:
        con.execute(
            f"UPDATE mcp_connections SET {', '.join(fields)} WHERE user_id = ? AND provider = ?",
            values,
        )


def _row_to_conn(row: sqlite3.Row) -> dict:
    md = {}
    if row["metadata"]:
        try:
            md = json.loads(row["metadata"])
        except json.JSONDecodeError:
            md = {}
    # Decrypt-on-read. decrypt() handles plaintext rows (pre-encryption
    # legacy) transparently and returns "" on key-loss so callers can detect
    # broken tokens and prompt the user to reconnect.
    return {
        "user_id": row["user_id"],
        "provider": row["provider"],
        "access_token": _dec(row["access_token"]),
        "refresh_token": _dec(row["refresh_token"]),
        "expires_at": row["expires_at"],
        "scope": row["scope"],
        "metadata": md,
        "connected_at": row["connected_at"],
        "last_synced": row["last_synced"],
        "indexed_count": int(row["indexed_count"] or 0),
        "index_status": row["index_status"] or "idle",
        "index_error": row["index_error"],
        # Incremental sync: opaque per-provider cursor (ISO timestamp or page token)
        "sync_cursor": row["sync_cursor"] if "sync_cursor" in row.keys() else None,
    }


def update_sync_cursor(user_id: str, provider: str, cursor: Optional[str]) -> None:
    """Persist an opaque sync cursor so the next incremental index starts
    where the last one left off. `cursor=None` resets to full re-index."""
    with _conn() as con:
        con.execute(
            "UPDATE mcp_connections SET sync_cursor = ? WHERE user_id = ? AND provider = ?",
            (cursor, user_id, provider),
        )


# ── Per-provider settings ──────────────────────────────────────────────────

def get_settings(user_id: str, provider: str) -> dict:
    with _conn() as con:
        row = con.execute(
            "SELECT settings FROM mcp_settings WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        ).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row["settings"])
    except json.JSONDecodeError:
        return {}


def save_settings(user_id: str, provider: str, settings: dict) -> dict:
    now = _now()
    payload = json.dumps(settings)
    with _conn() as con:
        con.execute(
            """INSERT INTO mcp_settings (user_id, provider, settings, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, provider) DO UPDATE SET
                   settings = excluded.settings,
                   updated_at = excluded.updated_at""",
            (user_id, provider, payload, now),
        )
    return settings
