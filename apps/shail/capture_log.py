"""
SHAIL Capture Log — in-memory event stream of backend activity.

A small ring buffer of the last N events keyed by user_id, exposed via
/browser/capture-log so the dashboard's Capture Log panel can show what
SHAIL is doing in near-real-time. State is intentionally non-persistent;
restart drops history. This is a live monitor, not an audit trail.

Event types:
    CAPTURE  — a new memory was ingested
    INDEX    — embedding stored to Chroma
    LINK     — a memory was linked to an ascent / deliverable / todo
    RECALL   — a memory was used as context for an LLM call
    PRUNE    — a memory was deleted (manual delete or auto-eviction)

Auth: every event carries a user_id. The endpoint filters by the
caller's user_id so users only see their own events.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

# Per-user ring buffer. Each user gets a deque capped at MAX_PER_USER.
MAX_PER_USER = 200

# Anonymous events (no user_id) live under this synthetic key. The
# /browser/capture-log endpoint never returns these to authenticated
# callers — they're only used so background tasks that don't have a
# user_id at hand still write somewhere.
ANON_KEY = "__anonymous__"

EVENT_TYPES = {"CAPTURE", "SESSION_UPDATE", "INDEX", "LINK", "RECALL", "PRUNE", "BLUEPRINT", "MCP_FETCH"}


class _Store:
    """Thread-safe per-user ring buffer of capture events."""

    def __init__(self) -> None:
        self._buckets: Dict[str, Deque[dict]] = {}
        self._lock = threading.Lock()

    def write(
        self,
        event_type: str,
        description: str,
        user_id: Optional[str] = None,
        ref_id: Optional[str] = None,
    ) -> dict:
        if event_type not in EVENT_TYPES:
            # Don't crash callers — just normalize and log.
            event_type = "CAPTURE"
        evt = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "description": description[:300] if description else "",
            "ref_id": ref_id or "",
        }
        key = user_id or ANON_KEY
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque(maxlen=MAX_PER_USER)
                self._buckets[key] = bucket
            bucket.appendleft(evt)
        return evt

    def read(self, user_id: str, limit: int = 200) -> List[dict]:
        if not user_id:
            return []
        with self._lock:
            bucket = self._buckets.get(user_id)
            if not bucket:
                return []
            return list(bucket)[: max(1, min(limit, MAX_PER_USER))]

    def clear(self, user_id: Optional[str] = None) -> None:
        with self._lock:
            if user_id:
                self._buckets.pop(user_id, None)
            else:
                self._buckets.clear()


_store = _Store()


def write_event(
    event_type: str,
    description: str,
    user_id: Optional[str] = None,
    ref_id: Optional[str] = None,
) -> dict:
    """Public helper. Safe to call from anywhere — never raises."""
    try:
        return _store.write(event_type, description, user_id=user_id, ref_id=ref_id)
    except Exception:
        return {}


def read_events(user_id: str, limit: int = 200) -> List[dict]:
    """Read most-recent-first events for a user. Empty list if none."""
    return _store.read(user_id, limit=limit)


def clear_events(user_id: Optional[str] = None) -> None:
    """Test helper — wipe one user's buffer or the whole store."""
    _store.clear(user_id=user_id)
