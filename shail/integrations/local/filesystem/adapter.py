"""Local filesystem adapter — watch + reindex on change.

Uses `watchdog` (FSEvents on macOS, inotify on Linux) to observe folders the
user has explicitly authorized. On every CREATE/MODIFY of a supported file
type, debounce-batches paths and refreshes the local path_index. File content
is not embedded into SHAIL memory.

Lifecycle:
  start_watch(user_id, path)  -> registers an Observer + handler
  stop_watch(user_id, path)   -> unregisters
  list_watches(user_id)       -> active watches for a user

Persistence: active watches are stored in `watched_folders` table so they
auto-restart on backend restart. Each row: (user_id, path, created_at).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


# ── Storage ─────────────────────────────────────────────────────────────────

def _conn():
    from apps.shail.auth_store import _conn as auth_conn
    return auth_conn()


def init_watcher_schema() -> None:
    """Create watched_folders table. Idempotent."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS watched_folders (
                user_id    TEXT NOT NULL,
                path       TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_event_at TEXT,
                event_count   INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, path)
            );
        """)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_watch_row(user_id: str, path: str) -> None:
    init_watcher_schema()
    with _conn() as con:
        con.execute(
            """INSERT INTO watched_folders (user_id, path, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, path) DO NOTHING""",
            (user_id, path, _now()),
        )


def remove_watch_row(user_id: str, path: str) -> int:
    init_watcher_schema()
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM watched_folders WHERE user_id = ? AND path = ?",
            (user_id, path),
        )
        return cur.rowcount


def list_watch_rows(user_id: Optional[str] = None) -> List[dict]:
    init_watcher_schema()
    with _conn() as con:
        if user_id is None:
            rows = con.execute(
                "SELECT user_id, path, created_at, last_event_at, event_count "
                "FROM watched_folders ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT user_id, path, created_at, last_event_at, event_count "
                "FROM watched_folders WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def bump_event_count(user_id: str, path: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE watched_folders SET last_event_at = ?, event_count = event_count + 1 "
            "WHERE user_id = ? AND path = ?",
            (_now(), user_id, path),
        )


# ── Debounced ingest scheduler ───────────────────────────────────────────────

# After an event fires, wait this long for additional events to coalesce before
# refreshing the path map. Saves churn when many files change at once (e.g. git
# checkout, IDE save-all).
_DEBOUNCE_SECONDS = 3.0

# Supported file extensions — must match what rag._extract_text_from_file handles
_SUPPORTED_EXTS = {
    ".md", ".txt", ".rst", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".cpp", ".h", ".hpp",
    ".rs", ".go", ".rb", ".swift", ".kt", ".sh", ".yaml", ".yml", ".toml", ".json",
    ".pdf", ".docx", ".doc", ".csv", ".xlsx", ".xls", ".html", ".htm", ".xhtml",
}

# Junk dirs that should never trigger reindex events
_SKIP_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".cache", "dist", "build", ".next", ".nuxt", "target",
    ".idea", ".vscode",
}


def _is_supported(path: str) -> bool:
    if not path:
        return False
    p = Path(path)
    if any(part.startswith(".") or part in _SKIP_DIRS for part in p.parts):
        return False
    return p.suffix.lower() in _SUPPORTED_EXTS


class _DebouncedIngest:
    """Coalesces filesystem events into batched path_index refresh calls.

    Thread-safe: events arrive on watchdog's observer thread; ingest fires on
    a background asyncio task. Each (user_id, root_path) gets its own pending
    set + timer.
    """

    def __init__(self) -> None:
        self._pending: Dict[str, Set[str]] = {}  # key = f"{user_id}::{root_path}"
        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def schedule(self, user_id: str, root_path: str, file_path: str) -> None:
        if not _is_supported(file_path):
            return
        key = f"{user_id}::{root_path}"
        with self._lock:
            self._pending.setdefault(key, set()).add(file_path)
            t = self._timers.get(key)
            if t is not None:
                t.cancel()
            new_t = threading.Timer(_DEBOUNCE_SECONDS, self._flush, args=(key,))
            new_t.daemon = True
            self._timers[key] = new_t
            new_t.start()

    def _flush(self, key: str) -> None:
        with self._lock:
            paths = list(self._pending.pop(key, set()))
            self._timers.pop(key, None)
        if not paths:
            return
        user_id, root_path = key.split("::", 1)
        bump_event_count(user_id, root_path)
        # Schedule path_index refresh on the main asyncio loop if present, else fall back
        # to a fresh loop in this thread.
        try:
            from apps.shail.chat_api import _ingest_paths_for_user
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        _ingest_paths_for_user(user_id, paths), loop
                    )
                else:
                    asyncio.run(_ingest_paths_for_user(user_id, paths))
            except RuntimeError:
                asyncio.run(_ingest_paths_for_user(user_id, paths))
        except Exception as exc:
            logger.error("debounced ingest flush failed for %s: %s", key, exc)


_DEBOUNCER = _DebouncedIngest()


# ── Watchdog handler + Observer registry ─────────────────────────────────────

class _ShailEventHandler(FileSystemEventHandler):
    def __init__(self, user_id: str, root_path: str) -> None:
        super().__init__()
        self.user_id = user_id
        self.root_path = root_path

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        _DEBOUNCER.schedule(self.user_id, self.root_path, event.src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        _DEBOUNCER.schedule(self.user_id, self.root_path, event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        try:
            from apps.shail.settings import get_settings
            from shail.memory import path_index
            path_index.remove_file(get_settings().path_index_db, event.src_path)
        except Exception:
            pass
        _DEBOUNCER.schedule(self.user_id, self.root_path, event.dest_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        try:
            from apps.shail.settings import get_settings
            from shail.memory import path_index
            path_index.remove_file(get_settings().path_index_db, event.src_path)
        except Exception as exc:
            logger.debug("path_index delete failed for %s: %s", event.src_path, exc)


@dataclass
class _ActiveWatch:
    observer: Observer
    handler: _ShailEventHandler


class FileSystemAdapter:
    """User-scoped filesystem watcher. One adapter per process; tracks all
    active watches across users via an in-process registry."""

    def __init__(self) -> None:
        self.name = "filesystem"
        self.category = "local"
        self._watches: Dict[str, _ActiveWatch] = {}  # key = f"{user_id}::{path}"
        self._lock = threading.Lock()

    # ── Read-only helpers (kept from original stub) ──
    def list_directory(self, directory: str) -> List[Dict[str, object]]:
        p = Path(directory)
        if not p.exists():
            return [{"error": f"Directory not found: {directory}"}]
        out: List[Dict[str, object]] = []
        for item in p.iterdir():
            try:
                size = item.stat().st_size if item.is_file() else None
            except OSError:
                size = None
            out.append({
                "name": item.name,
                "path": str(item),
                "type": "directory" if item.is_dir() else "file",
                "size": size,
            })
        return out

    # ── Watch lifecycle ──
    def start_watch(self, user_id: str, path: str) -> Dict[str, object]:
        """Start watching `path` (recursive). Idempotent — re-watching the
        same path is a no-op. Persists the watch row for restart recovery.
        """
        abs_path = str(Path(path).expanduser().resolve())
        if not os.path.isdir(abs_path):
            return {"ok": False, "error": f"not a directory: {abs_path}"}
        key = f"{user_id}::{abs_path}"
        with self._lock:
            if key in self._watches:
                return {"ok": True, "path": abs_path, "status": "already_watching"}
            handler = _ShailEventHandler(user_id, abs_path)
            observer = Observer()
            observer.schedule(handler, abs_path, recursive=True)
            observer.start()
            self._watches[key] = _ActiveWatch(observer=observer, handler=handler)
        add_watch_row(user_id, abs_path)
        logger.info("filesystem watch started: user=%s path=%s", user_id, abs_path)
        return {"ok": True, "path": abs_path, "status": "watching"}

    def stop_watch(self, user_id: str, path: str) -> Dict[str, object]:
        abs_path = str(Path(path).expanduser().resolve())
        key = f"{user_id}::{abs_path}"
        with self._lock:
            active = self._watches.pop(key, None)
        if active is not None:
            try:
                active.observer.stop()
                active.observer.join(timeout=2.0)
            except Exception as exc:
                logger.warning("observer stop error: %s", exc)
        remove_watch_row(user_id, abs_path)
        return {"ok": True, "path": abs_path, "status": "stopped"}

    def list_watches(self, user_id: str) -> List[Dict[str, object]]:
        return list_watch_rows(user_id)

    def restart_persisted_watches(self) -> int:
        """Re-attach observers for every persisted row. Called on backend
        startup. Returns the number of watches restarted."""
        count = 0
        for row in list_watch_rows(None):
            res = self.start_watch(row["user_id"], row["path"])
            if res.get("ok") and res.get("status") == "watching":
                count += 1
        return count

    def stop_all(self) -> None:
        with self._lock:
            keys = list(self._watches.keys())
        for k in keys:
            active = self._watches.get(k)
            if active is not None:
                try:
                    active.observer.stop()
                    active.observer.join(timeout=2.0)
                except Exception:
                    pass
        with self._lock:
            self._watches.clear()

    def get_capabilities(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "category": self.category,
            "capabilities": ["list_directory", "start_watch", "stop_watch", "list_watches"],
            "status": "active",
        }


# Module-level singleton — single observer registry per process.
_adapter: Optional[FileSystemAdapter] = None


def get_adapter() -> FileSystemAdapter:
    global _adapter
    if _adapter is None:
        _adapter = FileSystemAdapter()
    return _adapter


# Backwards-compat: legacy MCP registration entrypoint (no-op now since the
# adapter is reached via the REST endpoints in chat_api.py).
def register_filesystem_tools(provider):
    adapter = get_adapter()
    try:
        provider.register_provider("filesystem", adapter, category="local")
    except Exception:
        pass
    logger.info("Registered FileSystem adapter")
