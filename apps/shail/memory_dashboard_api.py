"""
SHAIL Memory Dashboard API
──────────────────────────
Endpoints for the dashboard SPA (apps/shail-ui) to browse, search,
manage, and export memories for the authenticated user.

Mounted at /api/v2 in main.py.

All endpoints require Bearer auth via get_current_user.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from apps.shail.auth_api import get_current_user
from shail.memory.rag import _get_store

logger = logging.getLogger(__name__)

dashboard_router = APIRouter()


# ── Models ─────────────────────────────────────────────────────────────────────

class MemoryItem(BaseModel):
    id: str
    customId: str
    eventType: str
    sourceApp: str
    sourceUrl: str
    title: str
    summary: str
    timestamp: str
    tags: List[str] = Field(default_factory=list)
    pinned: bool = False
    score: Optional[float] = None
    content: Optional[str] = None
    # v2 manifesto fields — additive, defaulted for legacy records.
    confidence: Optional[float] = None
    state: Optional[str] = None              # captured | partial | replayable | failed | synced | local-only
    parentId: Optional[str] = None           # lineage: previous version
    version: int = 1
    fidelity: Optional[float] = None         # 0..1 — capture completeness heuristic


class MemoryPage(BaseModel):
    items: List[MemoryItem]
    total: int
    page: int
    limit: int
    pages: int


class PatchRequest(BaseModel):
    pinned: Optional[bool] = None
    tags: Optional[List[str]] = None


class BulkDeleteRequest(BaseModel):
    ids: List[str]


class BulkDeleteResponse(BaseModel):
    deleted: int


class DashboardStats(BaseModel):
    total: int
    this_week: int
    this_month: int
    by_source: Dict[str, int]
    by_day_last_30: List[Dict[str, Any]]
    pinned_count: int
    top_domains: List[Dict[str, Any]]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_tags(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(t) for t in parsed]
        except Exception:
            return [s.strip() for s in raw.split(",") if s.strip()]
    return []


def _namespace(user_id: str) -> str:
    return f"user_{user_id}"


def _get_all_user_records(user_id: str):
    """
    Return all records from ChromaDB visible to this user.
    Queries user-specific namespace + legacy anonymous namespaces so
    captures from the browser extension (browser_memory) and macOS
    watchdog (local) appear in the dashboard even before re-auth.
    Returns list of (id, document, metadata) tuples, deduplicated by id.
    """
    store = _get_store()
    if not hasattr(store, "collection"):
        return []

    # Always include user namespace; also pull anonymous captures
    namespaces = [_namespace(user_id), "browser_memory", "local"]
    all_records: list = []
    seen: set = set()

    for ns in namespaces:
        try:
            result = store.collection.get(
                where={"namespace": ns},
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            logger.warning("Failed to fetch records for namespace %s: %s", ns, exc)
            continue

        ids   = result.get("ids", [])
        docs  = result.get("documents", []) or [""] * len(ids)
        metas = result.get("metadatas", []) or [{}] * len(ids)
        for rid, doc, meta in zip(ids, docs, metas):
            if rid not in seen:
                seen.add(rid)
                all_records.append((rid, doc, meta))

    return all_records


def _record_to_item(rid: str, doc: str, meta: dict, include_content: bool = False) -> MemoryItem:
    title = meta.get("title", "")
    if not title:
        import re
        m = re.match(r"^\[(\w+)\]\s+([^\n]+)", doc or "")
        title = m.group(2).strip() if m else ""

    body_start = (doc or "").find("\n\n")
    body = doc[body_start + 2:] if body_start >= 0 else (doc or "")
    summary = meta.get("summary") or body[:400]

    # v2 fields: derive defaults so legacy records render without backfill.
    completeness_raw = meta.get("artifactCompleteness") or meta.get("completeness")
    state = meta.get("state")
    if not state:
        if completeness_raw == "partial":
            state = "partial"
        elif meta.get("synced") == "true":
            state = "synced"
        else:
            state = "captured"
    try:
        confidence = float(meta.get("importance_score", meta.get("confidence", 0.5)))
    except Exception:
        confidence = 0.5
    try:
        fidelity = float(meta.get("fidelity")) if meta.get("fidelity") is not None else None
    except Exception:
        fidelity = None
    try:
        version = int(meta.get("version", 1))
    except Exception:
        version = 1

    return MemoryItem(
        id=rid,
        customId=meta.get("customId", rid),
        eventType=meta.get("eventType", "page_visit"),
        sourceApp=meta.get("sourceApp", "web"),
        sourceUrl=meta.get("sourceUrl", ""),
        title=title,
        summary=summary,
        timestamp=meta.get("timestamp", datetime.now(timezone.utc).isoformat()),
        tags=_parse_tags(meta.get("tags")),
        pinned=meta.get("pinned", "false") == "true",
        content=doc if include_content else None,
        confidence=confidence,
        state=state,
        parentId=meta.get("parentId") or None,
        version=version,
        fidelity=fidelity,
    )


def _extract_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "") or url[:30]
    except Exception:
        return url[:30]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@dashboard_router.get("/memories", response_model=MemoryPage)
async def list_memories(
    page: int = 1,
    limit: int = 20,
    q: str = "",
    source: str = "",
    tier: str = "",
    pinned: Optional[bool] = None,
    user_id: str = Depends(get_current_user),
) -> MemoryPage:
    """Browse / search user memories with pagination.

    `source` matches both the new `source` metadata (e.g. `macos_fs`,
    `browser_chatgpt`) and the legacy `sourceApp` field.
    `tier` filters by ephemeral|important.
    """
    records = _get_all_user_records(user_id)

    # Apply tier + source filters at the metadata level before mapping.
    if tier:
        records = [(rid, doc, meta) for rid, doc, meta in records if (meta or {}).get("tier") == tier]
    if source:
        records = [
            (rid, doc, meta) for rid, doc, meta in records
            if (meta or {}).get("source") == source or (meta or {}).get("sourceApp") == source
        ]

    items = [_record_to_item(rid, doc, meta) for rid, doc, meta in records]

    # Filter
    if q:
        q_lower = q.lower()
        items = [
            it for it in items
            if q_lower in it.title.lower() or q_lower in it.summary.lower()
        ]
    if pinned is not None:
        items = [it for it in items if it.pinned == pinned]

    # Sort newest first
    items.sort(key=lambda x: x.timestamp, reverse=True)

    total = len(items)
    pages = max(1, (total + limit - 1) // limit)
    start = (page - 1) * limit
    page_items = items[start : start + limit]

    return MemoryPage(items=page_items, total=total, page=page, limit=limit, pages=pages)


@dashboard_router.get("/memories/{memory_id}", response_model=MemoryItem)
async def get_memory(
    memory_id: str,
    user_id: str = Depends(get_current_user),
) -> MemoryItem:
    """Fetch full content of a single memory."""
    store = _get_store()
    if not hasattr(store, "collection"):
        raise HTTPException(status_code=404, detail="Memory not found")

    namespace = _namespace(user_id)
    try:
        result = store.collection.get(
            ids=[memory_id],
            where={"namespace": namespace},
            include=["documents", "metadatas"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    ids  = result.get("ids", [])
    docs = result.get("documents", [])
    metas = result.get("metadatas", [])

    if not ids:
        raise HTTPException(status_code=404, detail="Memory not found")

    return _record_to_item(ids[0], docs[0] or "", metas[0] or {}, include_content=True)


@dashboard_router.get("/memories/{memory_id}/related", response_model=List[MemoryItem])
async def related_memories(
    memory_id: str,
    limit: int = 10,
    user_id: str = Depends(get_current_user),
) -> List[MemoryItem]:
    """Return memories related to a given memory.

    Cheap heuristic v1: same sourceUrl OR shared tag OR same conversationId.
    Falls back to same sourceApp + closest-by-time if nothing else hits.
    Excludes the source memory itself.
    """
    records = _get_all_user_records(user_id)
    target = next(((rid, doc, meta) for rid, doc, meta in records if rid == memory_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Memory not found")

    _, _, t_meta = target
    t_meta = t_meta or {}
    t_url = t_meta.get("sourceUrl", "")
    t_conv = t_meta.get("conversationId")
    t_tags = set(_parse_tags(t_meta.get("tags")))
    t_app = t_meta.get("sourceApp", "")
    t_ts = t_meta.get("timestamp", "")

    scored: list[tuple[float, str, str, dict]] = []
    for rid, doc, meta in records:
        if rid == memory_id:
            continue
        meta = meta or {}
        score = 0.0
        if t_conv and meta.get("conversationId") == t_conv:
            score += 4.0
        if t_url and meta.get("sourceUrl", "") == t_url:
            score += 2.0
        overlap = t_tags & set(_parse_tags(meta.get("tags")))
        if overlap:
            score += 1.0 + 0.25 * len(overlap)
        if t_app and meta.get("sourceApp") == t_app:
            score += 0.25
        if score > 0:
            scored.append((score, rid, doc, meta))

    if not scored:
        # Fallback: closest-by-time within same sourceApp.
        same_app = [(rid, doc, meta) for rid, doc, meta in records
                    if rid != memory_id and (meta or {}).get("sourceApp") == t_app]
        same_app.sort(key=lambda r: abs(((r[2] or {}).get("timestamp", "") > t_ts) - 0))
        scored = [(0.1, rid, doc, meta) for rid, doc, meta in same_app[:limit]]

    scored.sort(key=lambda x: x[0], reverse=True)
    return [_record_to_item(rid, doc, meta) for _, rid, doc, meta in scored[:limit]]


@dashboard_router.patch("/memories/{memory_id}", response_model=MemoryItem)
async def patch_memory(
    memory_id: str,
    req: PatchRequest,
    user_id: str = Depends(get_current_user),
) -> MemoryItem:
    """Update pinned state or tags for a memory."""
    store = _get_store()
    if not hasattr(store, "collection"):
        raise HTTPException(status_code=404, detail="Memory not found")

    namespace = _namespace(user_id)
    try:
        result = store.collection.get(
            ids=[memory_id],
            where={"namespace": namespace},
            include=["documents", "metadatas"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not result.get("ids"):
        raise HTTPException(status_code=404, detail="Memory not found")

    meta = dict(result["metadatas"][0] or {})
    doc  = result["documents"][0] or ""

    if req.pinned is not None:
        meta["pinned"] = "true" if req.pinned else "false"
    if req.tags is not None:
        meta["tags"] = json.dumps(req.tags)

    try:
        store.collection.update(ids=[memory_id], metadatas=[meta])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Update failed: {exc}")

    return _record_to_item(memory_id, doc, meta, include_content=False)


@dashboard_router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete a memory.

    SECURITY (Sprint 1): verify ownership via namespace BEFORE delete.
    Without this any authenticated user could delete any memory by id since
    memory_ids are not namespace-scoped at the storage layer.
    """
    store = _get_store()
    if not hasattr(store, "collection"):
        raise HTTPException(status_code=404, detail="Memory not found")

    namespace = _namespace(user_id)
    try:
        owner = store.collection.get(
            ids=[memory_id],
            where={"namespace": namespace},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not owner.get("ids"):
        raise HTTPException(status_code=404, detail="Memory not found")

    try:
        ok = store.delete(memory_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": ok, "id": memory_id}


@dashboard_router.post("/memories/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete(
    req: BulkDeleteRequest,
    user_id: str = Depends(get_current_user),
) -> BulkDeleteResponse:
    """Delete multiple memories at once.

    SECURITY (Sprint 1): scope delete to caller's namespace. Fetch all ids
    that belong to the user once, intersect with requested ids, delete only
    the intersection. IDs the user does not own are silently skipped.
    """
    store = _get_store()
    if not hasattr(store, "collection"):
        return BulkDeleteResponse(deleted=0)

    namespace = _namespace(user_id)
    try:
        owned = store.collection.get(
            ids=req.ids,
            where={"namespace": namespace},
        )
    except Exception:
        return BulkDeleteResponse(deleted=0)

    owned_ids = set(owned.get("ids", []))
    deleted = 0
    for memory_id in req.ids:
        if memory_id not in owned_ids:
            continue
        try:
            if store.delete(memory_id):
                deleted += 1
        except Exception:
            pass
    return BulkDeleteResponse(deleted=deleted)


@dashboard_router.get("/stats", response_model=DashboardStats)
async def get_stats(
    user_id: str = Depends(get_current_user),
) -> DashboardStats:
    """Compute aggregate stats for the dashboard overview."""
    records = _get_all_user_records(user_id)
    total = len(records)

    now = datetime.now(timezone.utc)
    week_ago  = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    this_week  = 0
    this_month = 0
    source_counts: Counter = Counter()
    domain_counts: Counter = Counter()
    pinned_count = 0
    day_counts: defaultdict = defaultdict(int)

    for _, _, meta in records:
        meta = meta or {}
        ts = meta.get("timestamp", "")
        if ts >= week_ago:
            this_week += 1
        if ts >= month_ago:
            this_month += 1
            # Bin by day for the 30-day chart
            try:
                day_key = ts[:10]  # "YYYY-MM-DD"
                day_counts[day_key] += 1
            except Exception:
                pass
        source_counts[meta.get("sourceApp", "web")] += 1
        domain_counts[_extract_domain(meta.get("sourceUrl", ""))] += 1
        if meta.get("pinned") == "true":
            pinned_count += 1

    # Build 30-day series (fill in zeros for missing days)
    day_series = []
    for i in range(30, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        day_series.append({"date": day, "count": day_counts.get(day, 0)})

    # Top 5 domains
    top_domains = [
        {"domain": d, "count": c}
        for d, c in domain_counts.most_common(5)
        if d
    ]

    return DashboardStats(
        total=total,
        this_week=this_week,
        this_month=this_month,
        by_source=dict(source_counts),
        by_day_last_30=day_series,
        pinned_count=pinned_count,
        top_domains=top_domains,
    )


@dashboard_router.get("/export")
async def export_memories(
    format: str = "json",
    user_id: str = Depends(get_current_user),
) -> Response:
    """Export all user memories as JSON or Markdown."""
    records = _get_all_user_records(user_id)
    items = [_record_to_item(rid, doc, meta, include_content=True) for rid, doc, meta in records]
    items.sort(key=lambda x: x.timestamp, reverse=True)

    if format == "markdown":
        buf = StringIO()
        buf.write("# SHAIL Memory Export\n\n")
        for it in items:
            buf.write(f"## {it.title or it.sourceApp}\n\n")
            buf.write(f"- **Source:** {it.sourceApp}  \n")
            buf.write(f"- **URL:** {it.sourceUrl}  \n")
            buf.write(f"- **Date:** {it.timestamp[:10]}  \n")
            if it.pinned:
                buf.write(f"- **Pinned:** yes  \n")
            buf.write("\n")
            buf.write(it.content or it.summary)
            buf.write("\n\n---\n\n")
        content = buf.getvalue()
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="shail_memories.md"'},
        )
    else:
        # JSON export
        export_data = [it.dict() for it in items]
        content = json.dumps(export_data, indent=2, ensure_ascii=False)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="shail_memories.json"'},
        )


# ── Memory Graph ───────────────────────────────────────────────────────────────

class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    sourceApp: str
    timestamp: str
    importance: float = 0.5


class GraphEdge(BaseModel):
    source: str
    target: str


class MemoryGraph(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]


@dashboard_router.get("/graph", response_model=MemoryGraph)
@dashboard_router.get("/memories/graph", response_model=MemoryGraph)
async def memory_graph(
    user_id: str = Depends(get_current_user),
) -> MemoryGraph:
    """Return a force-graph-compatible node/edge structure for all memories."""
    records = _get_all_user_records(user_id)

    nodes: List[GraphNode] = []
    edges: List[GraphEdge] = []

    # Group by sourceUrl (same URL → edge) and by date bucket (same day → edge)
    url_to_ids: dict[str, list[str]] = defaultdict(list)
    day_to_ids: dict[str, list[str]] = defaultdict(list)

    for rid, _doc, meta in records:
        meta = meta or {}
        ts    = meta.get("timestamp", datetime.now(timezone.utc).isoformat())
        label = meta.get("title") or meta.get("sourceUrl", rid)[:60]
        importance = float(meta.get("importance_score", 0.5))

        nodes.append(GraphNode(
            id=rid,
            label=label,
            type=meta.get("eventType", "page_visit"),
            sourceApp=meta.get("sourceApp", "web"),
            timestamp=ts,
            importance=importance,
        ))

        url = meta.get("sourceUrl", "")
        if url:
            url_to_ids[url].append(rid)

        day = ts[:10]
        day_to_ids[day].append(rid)

    # Edges: same URL
    for ids in url_to_ids.values():
        for i in range(len(ids) - 1):
            edges.append(GraphEdge(source=ids[i], target=ids[i + 1]))

    # Edges: same day (cap per day to avoid explosion)
    for ids in day_to_ids.values():
        bucket = ids[:8]
        for i in range(len(bucket) - 1):
            edges.append(GraphEdge(source=bucket[i], target=bucket[i + 1]))

    return MemoryGraph(nodes=nodes, edges=edges)


# ── Share tokens ───────────────────────────────────────────────────────────────

def _share_db_path() -> str:
    from apps.shail.settings import get_settings
    return get_settings().sqlite_path


def _ensure_share_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS share_tokens (
            token      TEXT PRIMARY KEY,
            memory_id  TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


class ShareResponse(BaseModel):
    url: str
    token: str


@dashboard_router.post("/memories/share/{memory_id}", response_model=ShareResponse)
async def create_share(
    memory_id: str,
    user_id: str = Depends(get_current_user),
) -> ShareResponse:
    """Generate a shareable link token for a memory."""
    token = secrets.token_urlsafe(16)
    created_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(_share_db_path()) as conn:
        _ensure_share_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO share_tokens (token, memory_id, created_at) VALUES (?,?,?)",
            (token, memory_id, created_at),
        )
        conn.commit()

    return ShareResponse(
        url=f"http://localhost:8000/api/v2/share/{token}",
        token=token,
    )


@dashboard_router.get("/share/{token}")
async def view_share(token: str) -> Dict[str, Any]:
    """Public (no auth) endpoint — resolve share token → memory item."""
    with sqlite3.connect(_share_db_path()) as conn:
        _ensure_share_table(conn)
        row = conn.execute(
            "SELECT memory_id FROM share_tokens WHERE token = ?", (token,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Share link not found or expired")

    memory_id = row[0]
    store = _get_store()
    if not hasattr(store, "collection"):
        raise HTTPException(status_code=404, detail="Memory not found")

    try:
        result = store.collection.get(
            ids=[memory_id],
            include=["documents", "metadatas"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not result.get("ids"):
        raise HTTPException(status_code=404, detail="Memory not found")

    item = _record_to_item(
        result["ids"][0],
        result["documents"][0] or "",
        result["metadatas"][0] or {},
        include_content=True,
    )
    return item.dict()


# ── Capacity ───────────────────────────────────────────────────────────────────

class CapacityInfo(BaseModel):
    used_bytes: int
    limit_bytes: int
    used_human: str
    percent: float
    plan: str


def _human(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b //= 1024
    return f"{b:.1f} TB"


@dashboard_router.get("/capacity", response_model=CapacityInfo)
async def capacity(
    user_id: str = Depends(get_current_user),
) -> CapacityInfo:
    """Report ChromaDB disk usage vs. free-tier limit (500 MB)."""
    from apps.shail.settings import get_settings
    chroma_path = Path(get_settings().rag_chroma_path)
    used = 0
    if chroma_path.exists():
        used = sum(f.stat().st_size for f in chroma_path.rglob("*") if f.is_file())

    limit = 500 * 1024 * 1024  # 500 MB
    return CapacityInfo(
        used_bytes=used,
        limit_bytes=limit,
        used_human=_human(used),
        percent=round(used / limit * 100, 1),
        plan="free",
    )
