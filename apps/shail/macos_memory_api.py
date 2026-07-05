"""
SHAIL macOS Memory API
─────────────────────
Four-tier memory system:
  POST /memory/ephemeral   → Tier 1: perishable (TTL 24h, max 5000 records)
  POST /memory/important   → Tier 2: persistent (user-approved)
  GET  /memory/search      → Unified search across all tiers
  GET  /path-index/search  → Tier 3: local file pointer lookup
  POST /path-index/sync    → Trigger filesystem re-scan
  GET  /path-index/stats   → Index stats
  GET  /path-index/{id}/content → Read actual file content for a pointer

All routes are prefixed when mounted:
  /memory/*       (ephemeral + important + search)
  /path-index/*   (path index)
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from apps.shail.settings import get_settings
from apps.shail.auth_api import get_current_user
from shail.memory.rag import (
    COLLECTION_EPHEMERAL,
    COLLECTION_IMPORTANT,
    _get_store,
    get_tier_store,
    ingest,
    search as rag_search,
)
from shail.memory.path_index import (
    get_by_id as path_get_by_id,
    get_by_path as path_get_by_path,
    scan as path_scan,
    search as path_search,
    stats as path_stats,
    tree as path_tree,
    mark_embedded as path_mark_embedded,
    upsert_file as path_upsert_file,
    add_root as path_add_root,
    remove_root as path_remove_root,
    list_roots as path_list_roots,
    _default_roots,
)
from shail.memory.embeddings import embed_texts, embed_query

logger = logging.getLogger(__name__)

memory_router    = APIRouter()
path_idx_router  = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class EphemeralCaptureRequest(BaseModel):
    source: str = Field(..., description="accessibility | screen_capture | manual")
    content: str = Field(..., description="Text content (OCR output, UI text, etc.)")
    app_name: Optional[str] = None
    window_title: Optional[str] = None
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)


class EphemeralCaptureResponse(BaseModel):
    id: str
    status: str


class ImportantCaptureRequest(BaseModel):
    content: str
    title: Optional[str] = None
    source: str = Field(default="manual", description="manual | promoted | browser")
    source_url: Optional[str] = None
    promote_from_id: Optional[str] = Field(None, description="Ephemeral record id to promote")


class ImportantCaptureResponse(BaseModel):
    id: str
    status: str


class UnifiedSearchResult(BaseModel):
    id: str
    tier: str          # "important" | "ephemeral" | "path_index"
    content: str
    title: Optional[str] = None
    score: Optional[float] = None
    source: Optional[str] = None
    timestamp: Optional[str] = None
    path: Optional[str] = None    # only for path_index tier


class UnifiedSearchResponse(BaseModel):
    items: List[UnifiedSearchResult]
    total: int


class PathSearchResult(BaseModel):
    id: str
    path: str
    file_type: str
    size_bytes: Optional[int]
    mtime: Optional[float]
    title: Optional[str]
    indexed_at: float


class PathSearchResponse(BaseModel):
    items: List[PathSearchResult]
    total: int


class SyncResponse(BaseModel):
    status: str
    files_indexed: Optional[int] = None


class PathContentResponse(BaseModel):
    id: str
    path: str
    content: str
    file_type: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_namespace(user_id: str) -> str:
    # Always scope to the authenticated user — no anonymous fallback
    return f"user_{user_id}"


def _cleanup_ephemeral() -> int:
    """
    1. Promote any ephemeral records older than 24 h (importance_score >= 0.6) to important.
    2. Delete ephemeral records older than TTL that were NOT promoted.
    Returns count deleted.
    """
    settings = get_settings()
    ttl_cutoff       = time.time() - settings.ephemeral_ttl_hours * 3600   # default 24 h
    promote_cutoff   = time.time() - 86400  # always 24 h
    store = _get_store()
    if not hasattr(store, "collection"):
        return 0

    try:
        raw = store.collection.get(
            where={"tier": "ephemeral"},
            include=["documents", "metadatas", "embeddings"],
        )
        ids       = raw.get("ids", [])
        docs      = raw.get("documents") or []
        metas     = raw.get("metadatas") or []
        embeddings = raw.get("embeddings") or [[] for _ in ids]

        to_delete: list[str] = []
        promoted = 0
        deleted  = 0

        for rid, doc, meta, emb in zip(ids, docs, metas, embeddings):
            meta = meta or {}
            captured_ts = float(meta.get("captured_ts", 0))
            score = float(meta.get("importance_score", 0.5))

            if captured_ts < promote_cutoff and score >= 0.6:
                # Promote: update tier in metadata, keep embedding
                new_meta = dict(meta)
                new_meta["tier"] = "important"
                new_meta["promoted_at"] = str(time.time())
                try:
                    store.collection.update(ids=[rid], metadatas=[new_meta])
                    promoted += 1
                except Exception:
                    pass
            elif captured_ts < ttl_cutoff:
                to_delete.append(rid)

        if to_delete:
            try:
                store.collection.delete(ids=to_delete)
                deleted = len(to_delete)
            except Exception as e:
                logger.warning("Ephemeral bulk delete failed: %s", e)

        if promoted or deleted:
            logger.info("Ephemeral GC: promoted=%d deleted=%d", promoted, deleted)
    except Exception as e:
        logger.warning("Ephemeral cleanup failed: %s", e)

    return 0


def _ingest_unified(content: str, metadata: Dict[str, Any]) -> str:
    """
    Embed and upsert one record into the single base ChromaDB collection.
    Caller must include `namespace`, `tier`, and `source` in metadata.
    """
    store = _get_store()
    import uuid as _uuid
    record_id = metadata.pop("id", str(_uuid.uuid4()))
    namespace = metadata.get("namespace") or _namespace(user_id)
    try:
        embeddings = embed_texts([content])
        embedding = embeddings[0] if embeddings else []
    except Exception as e:
        logger.warning("Embedding failed, storing without vector: %s", e)
        embedding = []

    from shail.memory.vector_store import EmbeddingRecord
    store.upsert([EmbeddingRecord(
        id=record_id,
        namespace=namespace,
        content=content,
        metadata=metadata,
        embedding=embedding,
    )])
    return record_id


# ── Ephemeral endpoints ───────────────────────────────────────────────────────

@memory_router.post("/ephemeral", response_model=EphemeralCaptureResponse, status_code=201)
async def capture_ephemeral(
    req: EphemeralCaptureRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
) -> EphemeralCaptureResponse:
    """Write a perishable memory from macOS native services (screen capture / accessibility)."""
    if len(req.content.strip()) < 30:
        raise HTTPException(status_code=422, detail="Content too short")

    metadata = {
        "namespace": _user_namespace(user_id),
        "tier": "ephemeral",
        "source": req.source,
        "sourceApp": req.app_name or req.source,
        "app_name": req.app_name or "",
        "window_title": req.window_title or "",
        "title": req.window_title or req.app_name or "Capture",
        "importance_score": str(req.importance_score),
        "captured_ts": str(time.time()),
        "timestamp": _now_iso(),
    }
    record_id = _ingest_unified(req.content, metadata)
    background_tasks.add_task(_cleanup_ephemeral)
    return EphemeralCaptureResponse(id=record_id, status="created")


# ── Important endpoints ───────────────────────────────────────────────────────

@memory_router.post("/important", response_model=ImportantCaptureResponse, status_code=201)
async def capture_important(
    req: ImportantCaptureRequest,
    user_id: str = Depends(get_current_user),
) -> ImportantCaptureResponse:
    """Write or promote a memory to the persistent Important tier."""
    if len(req.content.strip()) < 30:
        raise HTTPException(status_code=422, detail="Content too short")

    metadata = {
        "namespace": _user_namespace(user_id),
        "tier": "important",
        "title": req.title or "",
        "source": req.source,
        "sourceApp": req.source,
        "source_url": req.source_url or "",
        "timestamp": _now_iso(),
        "captured_ts": str(time.time()),
    }
    if req.promote_from_id:
        metadata["promoted_from"] = req.promote_from_id

    record_id = _ingest_unified(req.content, metadata)
    return ImportantCaptureResponse(id=record_id, status="created")


# ── Unified search ────────────────────────────────────────────────────────────

@memory_router.get("/search", response_model=UnifiedSearchResponse)
async def unified_search(
    q: str = "",
    k: int = 20,
    tiers: str = "important,ephemeral,path_index",
    user_id: str = Depends(get_current_user),
) -> UnifiedSearchResponse:
    """
    Search across all memory tiers in the user's namespace.
    `tiers` is a comma-separated list: important, ephemeral, path_index
    """
    settings = get_settings()
    requested_tiers = {t.strip() for t in tiers.split(",")}
    items: List[UnifiedSearchResult] = []
    ns = _user_namespace(user_id)

    store = _get_store()
    vector_tiers = [t for t in ("important", "ephemeral") if t in requested_tiers]

    if q.strip() and vector_tiers:
        try:
            query_embedding = embed_query(q)
        except Exception:
            query_embedding = []

        if query_embedding:
            for tier_name in vector_tiers:
                try:
                    results = store.query(
                        query_embedding=query_embedding,
                        namespace=ns,
                        filters={"tier": tier_name},
                        k=k,
                    )
                    for r in results:
                        meta = r.get("metadata", {}) or {}
                        items.append(UnifiedSearchResult(
                            id=r["id"],
                            tier=tier_name,
                            content=r.get("content", "")[:500],
                            title=meta.get("title") or meta.get("window_title"),
                            score=round(r.get("score", 0.0), 4),
                            source=meta.get("source"),
                            timestamp=meta.get("timestamp"),
                        ))
                except Exception as e:
                    logger.warning("Search failed for tier %s: %s", tier_name, e)

        if "path_index" in requested_tiers:
            path_results = path_search(settings.path_index_db, q, limit=k)
            for r in path_results:
                items.append(UnifiedSearchResult(
                    id=r["id"],
                    tier="path_index",
                    content=r.get("summary_snippet") or r.get("title") or r["path"],
                    title=r.get("title"),
                    path=r["path"],
                    source="local_file",
                ))
    else:
        # Empty query: browse recent across requested tiers in this namespace
        try:
            if hasattr(store, "collection"):
                raw = store.collection.get(
                    where={"namespace": ns},
                    include=["documents", "metadatas"],
                )
                docs = raw.get("documents") or []
                metas = raw.get("metadatas") or []
                ids = raw.get("ids") or []
                combined = [
                    (rid, doc, meta or {})
                    for rid, doc, meta in zip(ids, docs, metas)
                    if (meta or {}).get("tier") in requested_tiers
                ]
                combined.sort(
                    key=lambda x: x[2].get("timestamp", ""),
                    reverse=True,
                )
                for rid, doc, meta in combined[:k]:
                    items.append(UnifiedSearchResult(
                        id=rid,
                        tier=meta.get("tier", "important"),
                        content=(doc or "")[:500],
                        title=meta.get("title") or meta.get("window_title"),
                        source=meta.get("source"),
                        timestamp=meta.get("timestamp"),
                    ))
        except Exception as e:
            logger.warning("Browse failed: %s", e)

    items.sort(key=lambda x: x.score or 0.0)
    return UnifiedSearchResponse(items=items[:k], total=len(items))


# ── Path Index endpoints ──────────────────────────────────────────────────────

def _run_scan(db_path: str) -> None:
    try:
        count = path_scan(db_path)
        logger.info("Path index scan complete: %d files indexed", count)
    except Exception as e:
        logger.error("Path index scan error: %s", e)


@path_idx_router.get("/search", response_model=PathSearchResponse)
async def search_path_index(q: str = "", limit: int = 20) -> PathSearchResponse:
    settings = get_settings()
    results = path_search(settings.path_index_db, q, limit=limit)
    items = [
        PathSearchResult(
            id=r["id"],
            path=r["path"],
            file_type=r["file_type"],
            size_bytes=r.get("size_bytes"),
            mtime=r.get("mtime"),
            title=r.get("title"),
            indexed_at=r["indexed_at"],
        )
        for r in results
    ]
    return PathSearchResponse(items=items, total=len(items))


@path_idx_router.post("/sync", response_model=SyncResponse)
async def sync_path_index(background_tasks: BackgroundTasks) -> SyncResponse:
    """Trigger async filesystem scan. Returns immediately."""
    settings = get_settings()
    background_tasks.add_task(_run_scan, settings.path_index_db)
    return SyncResponse(status="scanning")


@path_idx_router.get("/stats")
async def path_index_stats() -> Dict[str, Any]:
    settings = get_settings()
    return path_stats(settings.path_index_db)


@path_idx_router.get("/tree")
async def get_path_tree(
    root: Optional[str] = None,
    depth: int = Query(default=2, le=10),
    max_nodes: int = Query(default=500, le=5000),
) -> Dict[str, Any]:
    """Hierarchical folder/file map for Graphify.tsx + map-driven retrieval.

    - `root` omitted → returns the top-level content roots auto-discovered at
      startup (typically Documents / Desktop / Downloads / ~/Code).
    - `depth` controls how many BFS levels under each root are expanded.
    - Hard cap at `max_nodes` (default 500) to prevent OOM on giant subtrees.
    """
    settings = get_settings()
    return path_tree(settings.path_index_db, root, depth=int(depth), max_nodes=int(max_nodes))


@path_idx_router.post("/embed")
async def embed_path_lazy(path: str) -> Dict[str, Any]:
    """Refresh a single file in the path index.

    Kept at /embed for backward compatibility with older Graphify builds. It no
    longer writes local file content into the SHAIL vector memory store.
    """
    settings = get_settings()
    record = path_get_by_path(settings.path_index_db, path)
    if not record:
        raise HTTPException(status_code=404, detail="path not in index")
    if record.get("is_dir"):
        raise HTTPException(status_code=400, detail="refresh targets files only")
    refreshed = bool(path_upsert_file(settings.path_index_db, path))
    return {"path": path, "chunks_ingested": 0, "embedded": False, "refreshed": refreshed, "user_id": "local"}


@path_idx_router.post("/open")
async def open_path(
    path: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Reveal a path-indexed local file in Finder/file manager."""
    settings = get_settings()
    record = path_get_by_path(settings.path_index_db, path)
    if not record:
        raise HTTPException(status_code=404, detail="path not in index")

    # Security: Verify the path is within the allowed active scan roots
    from pathlib import Path as _Path
    from shail.memory.path_index import _default_roots, list_roots as path_list_roots
    
    persisted = path_list_roots(settings.path_index_db)
    env_roots = [r for r in settings.scan_roots if r.strip()]
    defaults = _default_roots()
    active_roots = [
        _Path(r).resolve() 
        for r in list(dict.fromkeys(env_roots + [r["path"] for r in persisted] + defaults))
    ]
    
    try:
        resolved_file = _Path(path).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
        
    is_safe = any(resolved_file.is_relative_to(root) for root in active_roots)
    if not is_safe:
        raise HTTPException(status_code=403, detail="Access denied: File is outside indexed directories")

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file no longer exists")
    try:
        if os.uname().sysname == "Darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"could not open file: {exc}")
    return {"ok": True, "path": path}


class RootRequest(BaseModel):
    path: str


@path_idx_router.get("/roots")
async def list_scan_roots() -> Dict[str, Any]:
    """List all scan roots: env-configured, persisted, and auto-discovered defaults."""
    settings = get_settings()
    persisted = path_list_roots(settings.path_index_db)
    persisted_paths = {r["path"] for r in persisted}
    env_roots = [r for r in settings.scan_roots if r.strip()]
    defaults = _default_roots()
    return {
        "env_roots": env_roots,
        "persisted_roots": persisted,
        "default_roots": defaults,
        "active_roots": list(dict.fromkeys(env_roots + [r["path"] for r in persisted] + defaults)),
    }


@path_idx_router.post("/roots")
async def add_scan_root(
    req: RootRequest,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """Add a new custom scan root. Persists across restarts. Triggers a background scan."""
    settings = get_settings()
    added = path_add_root(settings.path_index_db, req.path)
    if not added:
        # Either already exists or path isn't a directory.
        import os as _os
        if not _os.path.isdir(req.path):
            raise HTTPException(status_code=400, detail=f"Not a directory: {req.path}")
        return {"ok": True, "added": False, "message": "root already exists"}

    def _scan_new_root():
        try:
            count = path_scan(settings.path_index_db, roots=[req.path])
            logger.info("Scanned new root %s: %d files", req.path, count)
        except Exception as e:
            logger.error("Scan of new root %s failed: %s", req.path, e)

    background_tasks.add_task(_scan_new_root)
    return {"ok": True, "added": True, "path": req.path, "message": "root added and scan queued"}


@path_idx_router.delete("/roots")
async def remove_scan_root(req: RootRequest) -> Dict[str, Any]:
    """Remove a persisted scan root (does NOT delete already-indexed files)."""
    settings = get_settings()
    removed = path_remove_root(settings.path_index_db, req.path)
    return {"ok": True, "removed": removed, "path": req.path}


@path_idx_router.get("/diagnostics")
async def path_index_diagnostics() -> Dict[str, Any]:
    """Local-file retrieval health.

    Surfaces:
      - extractor_deps  — which optional libraries (pypdf/docx/openpyxl/pptx)
                          are installed; missing entries explain why content
                          search misses PDF/Word/Excel content
      - extractor_failures — per-extension failure counts seen this process
      - retrieval_stats — per-stage counters from local-file retrieval
      - recent_traces   — last N query traces (which hits dropped and why)
    """
    from apps.shail.retrieval.diagnostics import health_summary
    return health_summary()


@path_idx_router.get("/{record_id}/content", response_model=PathContentResponse)
async def get_path_content(
    record_id: str,
    user_id: str = Depends(get_current_user),
) -> PathContentResponse:
    """Read the actual file content for a path index pointer."""
    settings = get_settings()
    record = path_get_by_id(settings.path_index_db, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Path index record not found")

    file_path = os.path.abspath(record["path"])
    
    # Security: Verify the path is within the allowed active scan roots
    from pathlib import Path as _Path
    from shail.memory.path_index import _default_roots, list_roots as path_list_roots
    
    persisted = path_list_roots(settings.path_index_db)
    env_roots = [r for r in settings.scan_roots if r.strip()]
    defaults = _default_roots()
    active_roots = [
        _Path(r).resolve() 
        for r in list(dict.fromkeys(env_roots + [r["path"] for r in persisted] + defaults))
    ]
    
    try:
        resolved_file = _Path(file_path).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
        
    is_safe = any(resolved_file.is_relative_to(root) for root in active_roots)
    if not is_safe:
        raise HTTPException(status_code=403, detail="Access denied: File is outside indexed directories")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File no longer exists: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(50_000)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read file: {e}")

    return PathContentResponse(
        id=record_id,
        path=file_path,
        content=content,
        file_type=record["file_type"],
    )
