"""Pointer-only local-file retrieval routing.

Given a user query, consult path_index (FTS5 over file_name/title/snippet),
read only the top matching local files at answer time, and return snippets
plus stable file citations. This deliberately does NOT write file content
into the SHAIL memory vector store.

Production hardening (Phase 2/4 of the local-file production push):
  - FTS query is built with stopword filtering and FTS5-safe escaping so
    queries like "what's in my resume?" don't degenerate to a token soup
    that matches everything (or nothing, when the special chars throw).
  - bm25() score from path_index is propagated end-to-end so the model can
    rank local-file hits against memories / past chats / web results.
  - Every retrieved row passes through a size guard before file read so a
    200MB log file can't block the chat thread.
  - Per-query trace + counters flow into apps.shail.retrieval.diagnostics
    so the dashboard can answer "why didn't my PDF match".
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import List, Optional

from apps.shail.settings import get_settings
from apps.shail.retrieval import diagnostics as _diag
from shail.memory import path_index

logger = logging.getLogger(__name__)


# Conservative English stopword list. Tuned to keep semantic tokens
# ("resume", "Q3", "report") while dropping question-shape words.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does",
    "for", "from", "have", "how", "i", "in", "is", "it", "its", "me",
    "my", "no", "not", "of", "on", "or", "our", "so", "that", "the",
    "their", "them", "there", "they", "this", "to", "us", "was", "we",
    "were", "what", "when", "where", "which", "who", "why", "will",
    "with", "you", "your", "can", "should", "would", "could", "any",
    "about", "into", "via",
})

# Hard cap on how much text we'll read from a single file at answer time.
# Without this a 200MB log file blocks the chat thread. Tunable per-call.
_DEFAULT_READ_CAP_BYTES = 25_000_000


def _tokenize_for_fts(query: str) -> list[str]:
    """Split query into FTS-safe tokens. Drops stopwords + special chars.

    FTS5 phrase syntax uses double quotes; bare special chars like `?`, `:`,
    `'`, `-` inside a query can raise OperationalError. We sanitise to
    `[a-z0-9_]+` tokens and drop short stopwords.
    """
    if not query:
        return []
    raw = re.findall(r"[A-Za-z0-9_]{2,}", query)
    out: list[str] = []
    for t in raw:
        low = t.lower()
        if low in _STOPWORDS:
            continue
        out.append(t)
    return out


def _build_fts_query(query: str) -> Optional[str]:
    """Build the FTS5 MATCH expression. Returns None when nothing useful left."""
    tokens = _tokenize_for_fts(query)
    if not tokens:
        return None
    # Prefix-match each token; OR them so any one match qualifies. bm25 ranks
    # the actual relevance. Tokens are alphanumeric so no escaping required.
    return " OR ".join(f'"{t}"*' for t in tokens)


@dataclass
class LocalFileHit:
    id: str
    path: str
    title: str
    snippet: str
    file_type: str
    score: float = 0.0  # normalised 0..1; higher = more relevant
    size_bytes: Optional[int] = None
    mtime: Optional[float] = None
    extractor_used: Optional[str] = None  # rag | snippet | none


def route_query_to_files(query: str, *, k: int = 5) -> List[dict]:
    """Match query against path_index. Returns top-k file row dicts.

    Pure read — no embedding. Caller decides what to do with the matches.
    Filters out folders (is_dir == 0).
    """
    if not query or not query.strip():
        _diag.record("route_query_empty")
        return []
    settings = get_settings()
    fts_q = _build_fts_query(query)
    try:
        # We bypass path_index.search() and run FTS5 directly so we can carry
        # the bm25 rank back out. Falls through to the legacy path_index.search
        # on any FTS-level error so deployments without FTS5 still work.
        return _search_with_score(settings.path_index_db, fts_q, query, limit=k)
    except Exception as exc:  # noqa: BLE001
        _diag.record("route_query_path_index_failed")
        logger.warning("route_query_to_files: search failed: %s", exc)
        return []


def _search_with_score(
    db_path: str, fts_q: Optional[str], original_query: str, *, limit: int,
) -> List[dict]:
    """Search path_index with FTS5 + bm25 ranking. Falls back to LIKE.

    Returns row dicts augmented with `_score_raw` (bm25, lower=better) and
    `_score_norm` (0..1, higher=better). When falling back to LIKE we hand
    out a neutral 0.5 so downstream ranking doesn't crash on missing scores.
    """
    import sqlite3
    from contextlib import closing
    if fts_q:
        try:
            with closing(sqlite3.connect(db_path)) as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT p.*, bm25(path_index_fts) AS _bm25 "
                    "FROM path_index p "
                    "JOIN path_index_fts f ON f.id = p.id "
                    "WHERE path_index_fts MATCH ? AND p.is_dir = 0 "
                    "ORDER BY _bm25 LIMIT ?",
                    (fts_q, limit),
                ).fetchall()
            if rows:
                # Normalise bm25 (lower=better, typical range 0..20) to 0..1
                # where higher=better. Clamp ceiling at 20 to avoid an
                # exceptionally good row warping the rest.
                scored = []
                for r in rows:
                    d = dict(r)
                    bm = float(d.pop("_bm25") or 0.0)
                    clamped = max(0.0, min(20.0, abs(bm)))
                    d["_score_raw"] = bm
                    d["_score_norm"] = max(0.0, 1.0 - (clamped / 20.0))
                    scored.append(d)
                _diag.record("route_query_fts_hit", value=len(scored))
                return scored
        except sqlite3.OperationalError as exc:
            _diag.record("route_query_fts_error")
            logger.debug("FTS path failed; falling back: %s", exc)
        except Exception as exc:  # noqa: BLE001
            _diag.record("route_query_fts_error")
            logger.warning("FTS search unexpected error: %s", exc)

    # LIKE fallback — also runs when FTS returned zero rows. Useful for
    # filename-only matches on freshly-indexed binaries whose extractor was
    # unavailable at index time.
    rows = path_index.search(db_path, original_query, limit=limit)
    out = []
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        if d.get("is_dir"):
            continue
        d["_score_raw"] = None
        d["_score_norm"] = 0.5  # neutral
        out.append(d)
    _diag.record("route_query_like_hit", value=len(out))
    return out[:limit]


def _best_snippet(text: str, query: str, *, max_chars: int = 1200) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= max_chars:
        return text
    terms = [t.lower() for t in re.findall(r"[\w.-]{3,}", query or "")]
    if not terms:
        return text[:max_chars].rstrip()
    lower = text.lower()
    positions = [lower.find(t) for t in terms if lower.find(t) >= 0]
    if not positions:
        return text[:max_chars].rstrip()
    center = min(positions)
    start = max(0, center - max_chars // 3)
    end = min(len(text), start + max_chars)
    return text[start:end].strip()


def retrieve_local_file_context(
    query: str,
    *,
    k: int = 3,
    max_snippet_chars: int = 1200,
    read_cap_bytes: int = _DEFAULT_READ_CAP_BYTES,
) -> List[LocalFileHit]:
    """Return local-file snippets for prompt context without vector persistence.

    Read flow per hit:
      1. path_index FTS5 candidate row (already in hand)
      2. size guard — skip if file > read_cap_bytes (default 25MB)
      3. content extractor (rag._extract_text_from_file) — handles
         pdf/docx/xlsx/csv/html and falls back to text read
      4. _best_snippet — windowed around query terms
      5. citation emitted with bm25-derived normalised score

    Failures at each stage are recorded in `diagnostics` so the UI can tell
    the user WHY a query didn't match (extractor missing, file too big,
    file moved on disk, snippet empty after extraction).
    """
    rows = route_query_to_files(query, k=k)
    trace = {"query": query[:120], "fts_hits": len(rows), "emitted": 0,
             "drops": {}}
    if not rows:
        _diag.push_trace(trace)
        return []

    try:
        from shail.memory.rag import _extract_text_from_file
    except Exception as exc:
        logger.warning("local file extractor unavailable: %s", exc)
        _diag.record("extractor_module_unavailable")
        trace["drops"]["extractor_unavailable"] = len(rows)
        _diag.push_trace(trace)
        return []

    hits: list[LocalFileHit] = []
    for row in rows:
        file_path = row.get("path") or ""
        if not file_path or not os.path.exists(file_path):
            trace["drops"]["missing_on_disk"] = trace["drops"].get("missing_on_disk", 0) + 1
            _diag.record("hit_missing_on_disk")
            continue

        # Size guard — protects chat latency against pathological files.
        try:
            size = os.path.getsize(file_path)
        except OSError:
            size = None
        if size is not None and size > read_cap_bytes:
            trace["drops"]["too_large"] = trace["drops"].get("too_large", 0) + 1
            _diag.record("hit_too_large")
            continue

        extractor_used: Optional[str] = None
        text: Optional[str] = None
        try:
            text = _extract_text_from_file(file_path)
            extractor_used = "rag" if text else None
        except Exception as exc:
            logger.debug("local file read failed for %s: %s", file_path, exc)
            _diag.record("hit_extractor_exception")
            text = None
        if not text:
            text = row.get("summary_snippet") or ""
            if text:
                extractor_used = "snippet"
        if not text:
            trace["drops"]["empty_extract"] = trace["drops"].get("empty_extract", 0) + 1
            _diag.record("hit_empty_extract")
            continue

        snippet = _best_snippet(text, query, max_chars=max_snippet_chars)
        if not snippet:
            trace["drops"]["empty_snippet"] = trace["drops"].get("empty_snippet", 0) + 1
            _diag.record("hit_empty_snippet")
            continue

        score_norm = float(row.get("_score_norm") or 0.5)
        hits.append(LocalFileHit(
            id=row.get("id") or file_path,
            path=file_path,
            title=row.get("title") or os.path.basename(file_path),
            snippet=snippet,
            file_type=row.get("file_type") or "",
            score=score_norm,
            size_bytes=row.get("size_bytes"),
            mtime=row.get("mtime"),
            extractor_used=extractor_used,
        ))

    trace["emitted"] = len(hits)
    _diag.push_trace(trace)
    _diag.record("hits_emitted", value=len(hits))
    return hits


async def lazy_embed_for_query(query: str, *, user_id: str, k: int = 3) -> int:
    """Compatibility shim for older callers.

    Local files are pointer-only now: this performs the lookup/read path and
    returns the number of usable local-file hits without embedding anything.
    """
    return len(retrieve_local_file_context(query, k=k))
