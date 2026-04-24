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
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from io import StringIO
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
    Return all records from ChromaDB for a given user namespace.
    Returns list of (id, document, metadata) tuples.
    """
    store = _get_store()
    if not hasattr(store, "collection"):
        return []

    namespace = _namespace(user_id)
    try:
        result = store.collection.get(
            where={"namespace": namespace},
            include=["documents", "metadatas"],
        )
    except Exception as exc:
        logger.error("Failed to fetch all user records: %s", exc)
        return []

    ids   = result.get("ids", [])
    docs  = result.get("documents", []) or [""] * len(ids)
    metas = result.get("metadatas", []) or [{}] * len(ids)
    return list(zip(ids, docs, metas))


def _record_to_item(rid: str, doc: str, meta: dict, include_content: bool = False) -> MemoryItem:
    title = meta.get("title", "")
    if not title:
        import re
        m = re.match(r"^\[(\w+)\]\s+([^\n]+)", doc or "")
        title = m.group(2).strip() if m else ""

    body_start = (doc or "").find("\n\n")
    body = doc[body_start + 2:] if body_start >= 0 else (doc or "")
    summary = meta.get("summary") or body[:400]

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
    pinned: Optional[bool] = None,
    user_id: str = Depends(get_current_user),
) -> MemoryPage:
    """Browse / search user memories with pagination."""
    records = _get_all_user_records(user_id)

    items = [_record_to_item(rid, doc, meta) for rid, doc, meta in records]

    # Filter
    if q:
        q_lower = q.lower()
        items = [
            it for it in items
            if q_lower in it.title.lower() or q_lower in it.summary.lower()
        ]
    if source:
        items = [it for it in items if it.sourceApp == source]
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
    """Delete a memory."""
    store = _get_store()
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
    """Delete multiple memories at once."""
    store = _get_store()
    deleted = 0
    for memory_id in req.ids:
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
