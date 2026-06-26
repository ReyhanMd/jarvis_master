"""
Path Index — Tier 3 memory.

Stores lightweight metadata pointers to local files AND folders. No content
chunks are stored here — on query the file is read at retrieval time.

Schema extended (Part A): adds folder rows, parent/depth hierarchy, kind
classification, embedded flag, and an FTS5 mirror for fast name/title search.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional

logger = logging.getLogger(__name__)


# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS path_index (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    file_type   TEXT NOT NULL,
    size_bytes  INTEGER,
    mtime       REAL,
    title       TEXT,
    summary_snippet TEXT,
    indexed_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_path_index_path  ON path_index(path);
CREATE INDEX IF NOT EXISTS idx_path_index_type  ON path_index(file_type);
CREATE INDEX IF NOT EXISTS idx_path_index_mtime ON path_index(mtime DESC);
"""

# Forward-compat ALTERs. SQLite has no IF NOT EXISTS for ADD COLUMN, so we
# try each one and ignore the "duplicate column" error. Same pattern as
# session_backfill.PHASE_C_COLUMNS.
_PHASE2_ALTERS = (
    "ALTER TABLE path_index ADD COLUMN parent_path TEXT",
    "ALTER TABLE path_index ADD COLUMN depth INTEGER DEFAULT 0",
    "ALTER TABLE path_index ADD COLUMN is_dir INTEGER DEFAULT 0",
    "ALTER TABLE path_index ADD COLUMN child_count INTEGER DEFAULT 0",
    "ALTER TABLE path_index ADD COLUMN kind TEXT",
    "ALTER TABLE path_index ADD COLUMN embedded INTEGER DEFAULT 0",
    # file_name is materialized at write-time because SQLite has no reverse()
    # so we can't compute basename inside an AFTER INSERT trigger.
    "ALTER TABLE path_index ADD COLUMN file_name TEXT",
)

_PHASE2_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_path_index_parent ON path_index(parent_path)",
    "CREATE INDEX IF NOT EXISTS idx_path_index_kind   ON path_index(kind)",
    "CREATE INDEX IF NOT EXISTS idx_path_index_is_dir ON path_index(is_dir)",
    "CREATE INDEX IF NOT EXISTS idx_path_index_emb    ON path_index(embedded)",
)

# Persisted custom scan roots — survive restarts, merged with env + defaults.
_SCAN_ROOTS_DDL = """
CREATE TABLE IF NOT EXISTS scan_roots (
    path       TEXT PRIMARY KEY,
    added_at   REAL NOT NULL,
    file_count INTEGER DEFAULT 0,
    last_scan  REAL
);
"""


def _default_roots() -> List[str]:
    """User content folders we auto-scan on backend startup.

    Selection criteria: standard macOS / Linux content folders + common dev
    locations. Excludes ~/Library, ~/.config, ~/.ssh, browser caches, password
    manager dirs (handled by the per-dir junk filter in walk()).
    """
    home = Path.home()
    candidates = [
        home / "Documents", home / "Desktop", home / "Downloads",
        home / "Projects", home / "Code", home / "dev", home / "work",
        home / "src", home / "repos",
    ]
    return [str(p) for p in candidates if p.exists() and p.is_dir()]


# Module-level for backward compat (used by tests + old callers).
_SCAN_ROOTS = [Path(p) for p in _default_roots()] or [
    Path.home() / "Documents", Path.home() / "Desktop", Path.home() / "Downloads",
]

_INCLUDE_EXTS = {
    ".pdf", ".docx", ".doc", ".txt", ".md", ".pages",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
    ".csv", ".json", ".yaml", ".yml",
    ".xls", ".xlsx", ".pptx",
    ".html", ".htm", ".rst", ".log",
    ".java", ".cs", ".cpp", ".h", ".hpp", ".rb", ".swift", ".kt", ".sh", ".toml",
}

_SKIP_DIRS = {
    ".git", ".svn", "node_modules", "__pycache__", ".DS_Store",
    "venv", "env", ".venv", ".mypy_cache", ".pytest_cache", ".cache",
    "dist", "build", ".next", ".nuxt", "target", ".idea", ".vscode",
    "Library",  # ~/Library — caches, app support, mail, cookies, keychains
}


# Coarse content-kind classification used by Graphify + retrieval routing.
_KIND_MAP = {
    "code": {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs",
             ".cpp", ".h", ".hpp", ".rb", ".swift", ".kt", ".sh"},
    "doc":  {".pdf", ".docx", ".doc", ".txt", ".md", ".pages", ".rst", ".html",
             ".htm"},
    "data": {".csv", ".json", ".yaml", ".yml", ".xls", ".xlsx", ".toml"},
    "media": {".pptx"},
    "log":  {".log"},
}


def _classify_kind(ext: str) -> str:
    e = ext.lower()
    for k, exts in _KIND_MAP.items():
        if e in exts:
            return k
    return "other"


@contextmanager
def _conn(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_DDL)
        # Phase 2 schema extensions — idempotent.
        for ddl in _PHASE2_ALTERS:
            try:
                con.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists
        for idx in _PHASE2_INDEXES:
            try:
                con.execute(idx)
            except sqlite3.OperationalError:
                pass
        # FTS5 mirror for fast name/title search (A6).
        _ensure_fts(con)
        # Persisted scan roots table.
        con.executescript(_SCAN_ROOTS_DDL)
        con.commit()
        yield con
    finally:
        con.close()


def _ensure_fts(con: sqlite3.Connection) -> None:
    """Standalone FTS5 over path_index. Standalone (not external-content) so
    we can mirror plain columns via triggers and avoid rowid coupling issues.
    No-op if FTS5 isn't compiled in.
    """
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS path_index_fts USING fts5("
                    "id UNINDEXED, path, file_name, title, summary_snippet, kind UNINDEXED, "
                    "is_dir UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
    except sqlite3.OperationalError as exc:
        logger.warning("path_index FTS5 unavailable: %s — falling back to LIKE", exc)
        return
    # Triggers keep FTS in sync. file_name is a stored column populated by
    # Python at write-time (SQLite has no reverse() to compute basename).
    try:
        con.executescript("""
            DROP TRIGGER IF EXISTS path_index_ai;
            DROP TRIGGER IF EXISTS path_index_ad;
            DROP TRIGGER IF EXISTS path_index_au;
            CREATE TRIGGER path_index_ai AFTER INSERT ON path_index BEGIN
                INSERT INTO path_index_fts (id, path, file_name, title, summary_snippet, kind, is_dir)
                VALUES (new.id, new.path,
                        COALESCE(new.file_name, ''),
                        COALESCE(new.title, ''), COALESCE(new.summary_snippet, ''),
                        COALESCE(new.kind, ''), COALESCE(new.is_dir, 0));
            END;
            CREATE TRIGGER path_index_ad AFTER DELETE ON path_index BEGIN
                DELETE FROM path_index_fts WHERE id = old.id;
            END;
            CREATE TRIGGER path_index_au AFTER UPDATE ON path_index BEGIN
                DELETE FROM path_index_fts WHERE id = old.id;
                INSERT INTO path_index_fts (id, path, file_name, title, summary_snippet, kind, is_dir)
                VALUES (new.id, new.path,
                        COALESCE(new.file_name, ''),
                        COALESCE(new.title, ''), COALESCE(new.summary_snippet, ''),
                        COALESCE(new.kind, ''), COALESCE(new.is_dir, 0));
            END;
        """)
    except sqlite3.OperationalError:
        pass
    # First-time seed: if FTS empty but base table populated, backfill.
    try:
        c = con.execute("SELECT COUNT(*) FROM path_index_fts").fetchone()[0]
        n = con.execute("SELECT COUNT(*) FROM path_index").fetchone()[0]
        if c == 0 and n > 0:
            con.execute(
                "INSERT INTO path_index_fts (id, path, file_name, title, summary_snippet, kind, is_dir) "
                "SELECT id, path, COALESCE(file_name, ''), "
                "COALESCE(title, ''), COALESCE(summary_snippet, ''), "
                "COALESCE(kind, ''), COALESCE(is_dir, 0) FROM path_index"
            )
    except sqlite3.OperationalError:
        pass


def fts_available(db_path: str) -> bool:
    with _conn(db_path) as con:
        try:
            con.execute("SELECT 1 FROM path_index_fts LIMIT 0")
            return True
        except sqlite3.OperationalError:
            return False


# ── Write ─────────────────────────────────────────────────────────────────────

def _parent_path(p: Path) -> Optional[str]:
    parent = str(p.parent)
    return parent if parent and parent != str(p) else None


_SNIPPET_MAX_BYTES        = 100_000     # plain-text size cap for snippet read
_BINARY_SNIPPET_MAX_BYTES = 25_000_000  # 25MB cap for PDF/Word/Excel extraction
_SNIPPET_CHARS            = 1200        # bumped from 600 — FTS5 indexes more text
_BINARY_EXTS = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".pages",
                ".csv", ".html", ".htm")


# Cached missing-dep detection per process. Surfaced via the retrieval
# diagnostics endpoint so the UI can tell the user "pypdf not installed → N
# files unsearchable".
_EXTRACTOR_FAILURES: Dict[str, int] = {}


def _record_extractor_failure(reason: str) -> None:
    _EXTRACTOR_FAILURES[reason] = _EXTRACTOR_FAILURES.get(reason, 0) + 1


def extractor_failure_summary() -> Dict[str, int]:
    """Read-only view of extractor failures seen this process. Surfaced by
    /path-index/diagnostics for the dashboard. Resets on process restart."""
    return dict(_EXTRACTOR_FAILURES)


def _extract_snippet(p: Path, kind: str) -> Optional[str]:
    """Read the first ~SNIPPET_CHARS of content. Now content-aware for binary
    document types (PDF / DOCX / XLSX / HTML / CSV) — without this, FTS5 has
    no content to match against and questions about binary documents silently
    miss. Plain text/code/markdown still take the fast UTF-8 path.

    Returns None on error / unsupported kind. The full file is still read
    only at retrieval time by `rag._extract_text_from_file` — what we cache
    here is just enough text for FTS5 to surface the file as a candidate.
    """
    try:
        size = p.stat().st_size
    except OSError:
        return None

    ext = p.suffix.lower()

    # Plain text — fast path.
    if ext not in _BINARY_EXTS:
        if kind not in ("code", "doc", "data", "log"):
            return None
        if size > _SNIPPET_MAX_BYTES:
            return None
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                return f.read(_SNIPPET_CHARS).strip() or None
        except (OSError, UnicodeError):
            return None

    # Binary path — lean on the rag extractor. Capped at 25MB so we don't
    # block the indexer on a 500MB PDF.
    if size > _BINARY_SNIPPET_MAX_BYTES:
        return None
    try:
        from shail.memory.rag import _extract_text_from_file
    except Exception as exc:  # noqa: BLE001
        _record_extractor_failure(f"rag_extractor_unavailable:{exc}")
        return None
    try:
        text = _extract_text_from_file(str(p))
    except Exception as exc:  # noqa: BLE001
        _record_extractor_failure(f"{ext}:{type(exc).__name__}")
        logger.debug("snippet extract failed for %s: %s", p, exc)
        return None
    if not text:
        # Extractor returned None — usually means the format-specific lib is
        # missing (pypdf, python-docx, openpyxl). _extract_text_from_file
        # already logs the missing dep; track aggregate count here.
        _record_extractor_failure(f"missing_dep_or_empty:{ext}")
        return None
    snippet = text.strip()
    if not snippet:
        return None
    return snippet[:_SNIPPET_CHARS]


def upsert_file(db_path: str, file_path: str, *, extract_snippet: bool = True) -> Optional[str]:
    """Add or refresh a single file's metadata in the index. Returns record id.

    When extract_snippet=True (default), reads the first ~600 chars of plain-
    text content into summary_snippet so FTS5 can match queries against file
    content as well as filename/title. Skipped for binary formats — those get
    full extraction on demand by local-file retrieval.
    """
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return None
    ext = p.suffix.lower()
    if ext not in _INCLUDE_EXTS:
        return None
    try:
        stat = p.stat()
    except OSError:
        return None

    parent = _parent_path(p)
    depth = len(p.parts) - 1
    kind = _classify_kind(ext)
    snippet = _extract_snippet(p, kind) if extract_snippet else None

    with _conn(db_path) as con:
        existing = con.execute("SELECT id FROM path_index WHERE path = ?", (str(p),)).fetchone()
        record_id = existing["id"] if existing else str(uuid.uuid4())
        con.execute(
            """
            INSERT INTO path_index (id, path, file_type, size_bytes, mtime, title,
                                    summary_snippet, indexed_at, parent_path, depth,
                                    is_dir, kind, file_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                file_type       = excluded.file_type,
                size_bytes      = excluded.size_bytes,
                mtime           = excluded.mtime,
                title           = excluded.title,
                summary_snippet = excluded.summary_snippet,
                indexed_at      = excluded.indexed_at,
                parent_path     = excluded.parent_path,
                depth           = excluded.depth,
                kind            = excluded.kind,
                file_name       = excluded.file_name
            """,
            (record_id, str(p), ext.lstrip("."), stat.st_size, stat.st_mtime,
             p.stem, snippet, time.time(), parent, depth, kind, p.name),
        )
        con.commit()
    return record_id


def upsert_folder(db_path: str, folder_path: str, *, child_count: int = 0) -> Optional[str]:
    """Add or refresh a folder row. Folders aren't filtered by extension."""
    p = Path(folder_path)
    if not p.exists() or not p.is_dir():
        return None
    parent = _parent_path(p)
    depth = len(p.parts) - 1
    with _conn(db_path) as con:
        existing = con.execute("SELECT id FROM path_index WHERE path = ?", (str(p),)).fetchone()
        record_id = existing["id"] if existing else str(uuid.uuid4())
        con.execute(
            """
            INSERT INTO path_index (id, path, file_type, size_bytes, mtime, title,
                                    indexed_at, parent_path, depth, is_dir, kind,
                                    child_count, file_name)
            VALUES (?, ?, 'dir', NULL, NULL, ?, ?, ?, ?, 1, NULL, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                title       = excluded.title,
                indexed_at  = excluded.indexed_at,
                parent_path = excluded.parent_path,
                depth       = excluded.depth,
                child_count = excluded.child_count,
                file_name   = excluded.file_name
            """,
            (record_id, str(p), p.name or str(p), time.time(), parent, depth,
             child_count, p.name or str(p)),
        )
        con.commit()
    return record_id


def mark_embedded(db_path: str, path: str, embedded: bool = True) -> None:
    """Flag a file as content-vectorized so retrieval can skip re-embedding."""
    with _conn(db_path) as con:
        con.execute(
            "UPDATE path_index SET embedded = ? WHERE path = ?",
            (1 if embedded else 0, path),
        )
        con.commit()


def remove_file(db_path: str, file_path: str) -> None:
    with _conn(db_path) as con:
        con.execute("DELETE FROM path_index WHERE path = ?", (file_path,))
        con.commit()


# ── Persisted scan roots ──────────────────────────────────────────────────────

def add_root(db_path: str, path: str) -> bool:
    """Persist a custom scan root. Returns True if newly added."""
    path = str(Path(path).expanduser().resolve())
    if not Path(path).is_dir():
        return False
    with _conn(db_path) as con:
        existing = con.execute("SELECT path FROM scan_roots WHERE path = ?", (path,)).fetchone()
        if existing:
            return False
        con.execute(
            "INSERT INTO scan_roots (path, added_at) VALUES (?, ?)",
            (path, time.time()),
        )
        con.commit()
    return True


def remove_root(db_path: str, path: str) -> bool:
    """Remove a persisted scan root. Returns True if it existed."""
    path = str(Path(path).expanduser().resolve())
    with _conn(db_path) as con:
        rows = con.execute("DELETE FROM scan_roots WHERE path = ? RETURNING path", (path,)).fetchall()
        con.commit()
    return len(rows) > 0


def list_roots(db_path: str) -> List[Dict[str, Any]]:
    """Return all persisted scan roots with stats."""
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT path, added_at, file_count, last_scan FROM scan_roots ORDER BY added_at"
        ).fetchall()
    return [dict(r) for r in rows]


def get_persisted_roots(db_path: str) -> List[str]:
    """Return just the path strings of all persisted scan roots."""
    with _conn(db_path) as con:
        rows = con.execute("SELECT path FROM scan_roots ORDER BY added_at").fetchall()
    return [r["path"] for r in rows]


def _update_root_stats(db_path: str, path: str, file_count: int) -> None:
    with _conn(db_path) as con:
        con.execute(
            "UPDATE scan_roots SET file_count = ?, last_scan = ? WHERE path = ?",
            (file_count, time.time(), path),
        )
        con.commit()


# ── Scan ─────────────────────────────────────────────────────────────────────

def scan(db_path: str, roots: Optional[List[str]] = None) -> int:
    """
    Walk configured roots, upsert every matching file + folder. Returns count
    of files indexed. Skips files that haven't changed (mtime unchanged).
    Folders are always upserted (cheap; needed for tree view).
    """
    scan_roots = [Path(r) for r in roots] if roots else [Path(r) for r in _default_roots()]
    if not scan_roots:
        scan_roots = list(_SCAN_ROOTS)
    count = 0

    with _conn(db_path) as con:
        existing: Dict[str, float] = {
            row["path"]: row["mtime"]
            for row in con.execute("SELECT path, mtime FROM path_index WHERE is_dir = 0")
        }

    for root in scan_roots:
        if not root.exists() or not root.is_dir():
            continue
        # Register root folder so tree queries have a starting node.
        upsert_folder(db_path, str(root))
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # Prune junk dirs + hidden dirs.
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d not in _SKIP_DIRS]
            # Folder rows for every visited dir.
            try:
                child_count = len(dirnames) + sum(
                    1 for f in filenames if Path(f).suffix.lower() in _INCLUDE_EXTS
                )
                upsert_folder(db_path, dirpath, child_count=child_count)
            except OSError:
                pass

            for fname in filenames:
                if fname.startswith("."):
                    continue
                fpath = Path(dirpath) / fname
                if fpath.suffix.lower() not in _INCLUDE_EXTS:
                    continue
                try:
                    mtime = fpath.stat().st_mtime
                except OSError:
                    continue
                if str(fpath) in existing and existing[str(fpath)] == mtime:
                    continue
                if upsert_file(db_path, str(fpath)):
                    count += 1

    return count


def backfill_snippets(db_path: str, *, max_files: int = 2000,
                       include_binaries: bool = True) -> int:
    """Re-process rows whose summary_snippet is NULL or empty.

    Now covers binary types too (PDF/Word/Excel) — without this, existing
    indexes built before the content-aware extractor landed will continue to
    have empty FTS5 entries for every PDF/Word file, and chat will keep
    missing content-based questions.

    Bounded so we don't block startup on 20K-row repos.
    """
    init = 0
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT id, path, kind FROM path_index "
            "WHERE is_dir = 0 AND (summary_snippet IS NULL OR summary_snippet = '') "
            "ORDER BY indexed_at DESC LIMIT ?",
            (max_files,),
        ).fetchall()
    for row in rows:
        p = Path(row["path"])
        if not p.exists() or not p.is_file():
            continue
        ext = p.suffix.lower()
        if not include_binaries and ext in _BINARY_EXTS:
            continue
        snippet = _extract_snippet(p, row["kind"] or _classify_kind(ext))
        if not snippet:
            continue
        with _conn(db_path) as con:
            con.execute(
                "UPDATE path_index SET summary_snippet = ? WHERE id = ?",
                (snippet, row["id"]),
            )
        init += 1
    return init


def spotlight_recent_files(days: int = 30, *, max_files: int = 1000) -> List[str]:
    """macOS-only Spotlight query for recently-modified content files.

    Returns absolute paths matching _INCLUDE_EXTS. No-ops gracefully on
    non-macOS or when `mdfind` is unavailable / errors.
    """
    if not Path("/usr/bin/mdfind").exists():
        return []
    # mdfind expression: any kind of document/text content modified in the
    # last N days. We over-fetch and post-filter by extension to keep the
    # mdfind query simple + portable across macOS versions.
    query = f"kMDItemFSContentChangeDate >= $time.today(-{int(days)})"
    try:
        out = subprocess.run(
            ["/usr/bin/mdfind", "-onlyin", str(Path.home()), query],
            capture_output=True, text=True, timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("spotlight query failed: %s", exc)
        return []
    if out.returncode != 0:
        return []
    paths: List[str] = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # Drop junk dirs + hidden + Library
        if any(part.startswith(".") or part in _SKIP_DIRS for part in Path(line).parts):
            continue
        if Path(line).suffix.lower() not in _INCLUDE_EXTS:
            continue
        paths.append(line)
        if len(paths) >= max_files:
            break
    return paths


def ingest_spotlight_recent(db_path: str, days: int = 30, *, max_files: int = 1000) -> int:
    """Upsert every recently-modified file Spotlight returns. Returns count."""
    n = 0
    for fp in spotlight_recent_files(days, max_files=max_files):
        if upsert_file(db_path, fp):
            n += 1
    return n


# ── Read / search ────────────────────────────────────────────────────────────

def search(db_path: str, query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Keyword search over filename/title/snippet. Uses FTS5 when available,
    falls back to LIKE. Files only — set `include_dirs` via tree() for folders.
    """
    terms = [t for t in query.split() if t]
    if not terms:
        with _conn(db_path) as con:
            rows = con.execute(
                "SELECT * FROM path_index WHERE is_dir = 0 ORDER BY mtime DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    with _conn(db_path) as con:
        # FTS5 path — try first
        try:
            sanitized = [t.replace('"', '') for t in terms if t.strip()]
            fts_q = " OR ".join(f'"{t}"*' for t in sanitized)
            rows = con.execute(
                "SELECT p.* FROM path_index p "
                "JOIN path_index_fts f ON f.id = p.id "
                "WHERE path_index_fts MATCH ? AND p.is_dir = 0 "
                "ORDER BY bm25(path_index_fts) LIMIT ?",
                (fts_q, limit),
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            pass
        # LIKE fallback
        like_clauses = " OR ".join(
            ["(LOWER(path) LIKE ? OR LOWER(title) LIKE ? OR LOWER(COALESCE(summary_snippet,'')) LIKE ?)"]
            * len(terms)
        )
        params: list = []
        for t in terms:
            params.extend([f"%{t.lower()}%"] * 3)
        params.append(limit)
        rows = con.execute(
            f"SELECT * FROM path_index WHERE is_dir = 0 AND ({like_clauses}) "
            f"ORDER BY mtime DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def tree(
    db_path: str,
    root: Optional[str] = None,
    *,
    depth: int = 2,
    max_nodes: int = 500,
) -> Dict[str, Any]:
    """Return a hierarchical slice rooted at `root` (or top-level roots).

    Output shape consumed by Graphify.tsx + map-driven retrieval. Hard cap
    `max_nodes` so a giant subtree request can't OOM the dashboard.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []
    seen: set = set()
    with _conn(db_path) as con:
        if root:
            base = con.execute(
                "SELECT * FROM path_index WHERE path = ?", (root,)
            ).fetchone()
            base_paths = [root] if base else []
            if base:
                nodes.append(_node_dict(base))
                seen.add(base["path"])
        else:
            base_rows = con.execute(
                "SELECT * FROM path_index WHERE depth = "
                "  (SELECT MIN(depth) FROM path_index WHERE is_dir = 1) "
                "AND is_dir = 1 ORDER BY path LIMIT 50"
            ).fetchall()
            base_paths = [r["path"] for r in base_rows]
            for r in base_rows:
                if r["path"] not in seen:
                    nodes.append(_node_dict(r))
                    seen.add(r["path"])

        # BFS expansion to `depth` levels under each base path.
        frontier = list(base_paths)
        for _ in range(max(0, int(depth))):
            if not frontier or len(nodes) >= max_nodes:
                break
            placeholders = ",".join("?" * len(frontier))
            rows = con.execute(
                f"SELECT * FROM path_index WHERE parent_path IN ({placeholders}) "
                f"ORDER BY is_dir DESC, path LIMIT ?",
                (*frontier, max_nodes - len(nodes)),
            ).fetchall()
            next_frontier: List[str] = []
            for r in rows:
                if r["path"] in seen:
                    continue
                nodes.append(_node_dict(r))
                seen.add(r["path"])
                edges.append({"source": r["parent_path"], "target": r["path"]})
                if r["is_dir"]:
                    next_frontier.append(r["path"])
                if len(nodes) >= max_nodes:
                    break
            frontier = next_frontier
    return {"root": root, "nodes": nodes, "edges": edges, "truncated": len(nodes) >= max_nodes}


def _node_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id":          row["path"],
        "name":        Path(row["path"]).name or row["path"],
        "is_dir":      bool(row["is_dir"] or 0),
        "kind":        row["kind"],
        "size":        row["size_bytes"],
        "mtime":       row["mtime"],
        "child_count": int(row["child_count"] or 0),
        "embedded":    bool(row["embedded"] or 0),
    }


def get_by_id(db_path: str, record_id: str) -> Optional[Dict[str, Any]]:
    with _conn(db_path) as con:
        row = con.execute("SELECT * FROM path_index WHERE id = ?", (record_id,)).fetchone()
    return dict(row) if row else None


def get_by_path(db_path: str, path: str) -> Optional[Dict[str, Any]]:
    with _conn(db_path) as con:
        row = con.execute("SELECT * FROM path_index WHERE path = ?", (path,)).fetchone()
    return dict(row) if row else None


def stats(db_path: str) -> Dict[str, Any]:
    with _conn(db_path) as con:
        total_files = con.execute(
            "SELECT COUNT(*) FROM path_index WHERE is_dir = 0").fetchone()[0]
        total_dirs = con.execute(
            "SELECT COUNT(*) FROM path_index WHERE is_dir = 1").fetchone()[0]
        by_type = {
            row[0]: row[1]
            for row in con.execute(
                "SELECT file_type, COUNT(*) FROM path_index WHERE is_dir = 0 "
                "GROUP BY file_type ORDER BY 2 DESC"
            )
        }
        by_kind = {
            row[0] or "other": row[1]
            for row in con.execute(
                "SELECT kind, COUNT(*) FROM path_index WHERE is_dir = 0 "
                "GROUP BY kind ORDER BY 2 DESC"
            )
        }
        embedded_count = con.execute(
            "SELECT COUNT(*) FROM path_index WHERE embedded = 1").fetchone()[0]
        last_indexed = con.execute(
            "SELECT MAX(indexed_at) FROM path_index").fetchone()[0]
    return {
        "total": total_files,
        "total_files": total_files,
        "total_dirs": total_dirs,
        "by_type": by_type,
        "by_kind": by_kind,
        "embedded": embedded_count,
        "last_indexed_at": last_indexed,
    }
