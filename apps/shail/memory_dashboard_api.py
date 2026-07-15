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
from apps.shail.memory_delete import collect_memory_delete_ids, delete_memory_everywhere
from apps.shail.source_normalization import (
    is_browser_memory,
    normalize_browser_metadata,
)
from apps.shail.browser_memory_model import (
    list_records as list_browser_memory_records,
    search_records as search_browser_memory_records,
    visible_namespaces as browser_visible_namespaces,
)
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


# ── Graph helper utilities ───────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    """Return e.g. 'chatgpt.com' from any URL. Returns '' on parse failure."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # strip leading www.
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _parse_tags(raw) -> list:
    """
    Safely parse tags field which may be a JSON-encoded list, a comma-separated
    string, an actual Python list, or None.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw if t]
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("["):
            try:
                import json
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(t) for t in parsed if t]
            except Exception:
                pass
        # Fall back to comma-split
        return [t.strip() for t in stripped.split(",") if t.strip()]
    return []


def _visible_namespaces(user_id: str) -> list[str]:
    """Browser/dashboard surfaces include legacy anonymous captures."""
    return browser_visible_namespaces(_namespace(user_id))



def _get_all_user_records(user_id: str):
    """Return canonical browser-memory records as dashboard-compatible tuples."""
    out = []
    for record in list_browser_memory_records(_visible_namespaces(user_id), limit=5000):
        meta = dict(record.metadata or {})
        meta.update({
            "customId": record.customId,
            "eventType": record.eventType,
            "sourceApp": record.sourceApp,
            "sourceUrl": record.sourceUrl,
            "title": record.title,
            "summary": record.summary,
            "timestamp": record.timestamp,
            "tags": json.dumps(record.tags),
            "pinned": "true" if record.pinned else "false",
            "state": record.state,
            "fidelity": record.fidelity,
            "confidence": record.confidence,
            "parentId": record.parentId,
            "version": record.version,
            "conversationId": record.conversationId,
            "capture_source": record.captureSource,
            "capture_mode": record.captureMode,
            "namespace": record.namespace,
        })
        out.append((record.id, record.content, meta))
    return out


def _record_to_item(rid: str, doc: str, meta: dict, include_content: bool = False) -> MemoryItem:
    meta = normalize_browser_metadata(meta or {}, doc or "")
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
    try:
        score = float(meta.get("score")) if meta.get("score") is not None else None
    except Exception:
        score = None

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
        score=score,
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
    import asyncio
    if q:
        canonical = await asyncio.to_thread(
            search_browser_memory_records,
            _visible_namespaces(user_id),
            query=q,
            k=5000,
            source_app=source.lower() if source else None,
        )
        records = []
        for record in canonical:
            meta = dict(record.metadata or {})
            meta.update({
                "customId": record.customId,
                "eventType": record.eventType,
                "sourceApp": record.sourceApp,
                "sourceUrl": record.sourceUrl,
                "title": record.title,
                "summary": record.summary,
                "timestamp": record.timestamp,
                "tags": json.dumps(record.tags),
                "pinned": "true" if record.pinned else "false",
                "state": record.state,
                "fidelity": record.fidelity,
                "confidence": record.confidence,
                "parentId": record.parentId,
                "version": record.version,
                "score": record.score,
            })
            records.append((record.id, record.content, meta))
    else:
        import asyncio
        records = await asyncio.to_thread(_get_all_user_records, user_id)

    # Apply tier + source filters at the metadata level before mapping.
    if tier:
        records = [(rid, doc, meta) for rid, doc, meta in records if (meta or {}).get("tier") == tier]
    if source and not q:
        source_norm = source.lower()
        records = [
            (rid, doc, meta) for rid, doc, meta in records
            if (meta or {}).get("source") == source_norm
            or (meta or {}).get("sourceApp") == source_norm
            or (meta or {}).get("source") == source
            or (meta or {}).get("sourceApp") == source
        ]

    items = [_record_to_item(rid, doc, meta) for rid, doc, meta in records]

    if pinned is not None:
        items = [it for it in items if it.pinned == pinned]

    if q:
        items.sort(key=lambda x: x.score or 0.0, reverse=True)
    else:
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
    from apps.shail.browser_memory_model import get_record
    record = get_record(memory_id, _visible_namespaces(user_id))
    if not record:
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryItem(**record.to_dashboard_item(include_content=True))


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
    import asyncio
    records = await asyncio.to_thread(_get_all_user_records, user_id)
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
        try:
            from apps.shail import raw_transcripts as _rt
            raw = _rt.get(memory_id)
            if not raw or raw.get("namespace") != namespace:
                raise HTTPException(status_code=404, detail="Memory not found")
            meta = normalize_browser_metadata(raw.get("metadata") or {}, raw.get("content") or "")
            if req.pinned is not None:
                meta["pinned"] = "true" if req.pinned else "false"
            if req.tags is not None:
                meta["tags"] = json.dumps(req.tags)
            _rt.save(
                memory_id=memory_id,
                user_id=user_id,
                namespace=namespace,
                content_type=raw.get("content_type", meta.get("eventType", "page_visit")),
                content=raw.get("content") or "",
                metadata=meta,
                capture_mode=raw.get("capture_mode") or "active",
            )
            return _record_to_item(memory_id, raw.get("content") or "", meta, include_content=False)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Raw update failed: {exc}")

    meta = dict(result["metadatas"][0] or {})
    doc  = result["documents"][0] or ""
    if not is_browser_memory(meta, doc):
        raise HTTPException(status_code=404, detail="Memory not found")

    if req.pinned is not None:
        meta["pinned"] = "true" if req.pinned else "false"
    if req.tags is not None:
        meta["tags"] = json.dumps(req.tags)

    try:
        logical_id, update_ids = collect_memory_delete_ids(store, memory_id, _visible_namespaces(user_id))
        ids_to_update = sorted(update_ids or {memory_id})
        metas_to_update = []
        if len(ids_to_update) == 1:
            metas_to_update = [meta]
        else:
            chunk_result = store.collection.get(ids=ids_to_update, include=["metadatas"])
            for old_meta in chunk_result.get("metadatas", []) or []:
                updated = dict(old_meta or {})
                if req.pinned is not None:
                    updated["pinned"] = "true" if req.pinned else "false"
                if req.tags is not None:
                    updated["tags"] = json.dumps(req.tags)
                metas_to_update.append(updated)
        store.collection.update(ids=ids_to_update, metadatas=metas_to_update)
        try:
            from apps.shail import raw_transcripts as _rt
            raw = _rt.get(logical_id)
            if raw and raw.get("namespace") == namespace:
                raw_meta = normalize_browser_metadata(raw.get("metadata") or {}, raw.get("content") or "")
                if req.pinned is not None:
                    raw_meta["pinned"] = "true" if req.pinned else "false"
                if req.tags is not None:
                    raw_meta["tags"] = json.dumps(req.tags)
                _rt.save(
                    memory_id=logical_id,
                    user_id=user_id,
                    namespace=namespace,
                    content_type=raw.get("content_type", meta.get("eventType", "page_visit")),
                    content=raw.get("content") or "",
                    metadata=raw_meta,
                    capture_mode=raw.get("capture_mode") or "active",
                )
        except Exception as raw_exc:
            logger.warning("Raw transcript metadata update failed for %s: %s", memory_id, raw_exc)
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

    try:
        logical_id, deleted_ids = delete_memory_everywhere(store, memory_id, _visible_namespaces(user_id))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not deleted_ids:
        try:
            from apps.shail import raw_transcripts as _rt
            raw = _rt.get(memory_id)
            if not raw or raw.get("namespace") not in _visible_namespaces(user_id):
                raise HTTPException(status_code=404, detail="Memory not found")
            _rt.delete(memory_id)
            try:
                from apps.shail.blueprints import delete_blueprint
                from apps.shail.pipeline_status import delete_status
                from apps.shail.blueprint_queue import delete_jobs_for_memory
                from apps.shail.capture_store import delete_memory_state
                delete_blueprint(memory_id)
                delete_status(memory_id)
                delete_jobs_for_memory(memory_id)
                delete_memory_state(memory_id)
            except Exception as cleanup_exc:
                logger.warning("raw-only dashboard delete cleanup failed for %s: %s", memory_id, cleanup_exc)
            logical_id = memory_id
            deleted_ids = [memory_id]
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    from apps.shail.websocket_server import websocket_manager
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(websocket_manager.broadcast_event("INVALIDATE_CACHE", {
            "keys": ["memories", "stats"],
            "action": "delete",
            "id": memory_id
        }))
    except RuntimeError:
        pass

    return {"ok": True, "id": logical_id, "deleted": len(deleted_ids)}


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

    deleted = 0
    for memory_id in req.ids:
        try:
            _, deleted_ids = delete_memory_everywhere(store, memory_id, _visible_namespaces(user_id))
            if deleted_ids:
                deleted += 1
                continue
            from apps.shail import raw_transcripts as _rt
            raw = _rt.get(memory_id)
            if raw and raw.get("namespace") in _visible_namespaces(user_id):
                _rt.delete(memory_id)
                try:
                    from apps.shail.blueprints import delete_blueprint
                    from apps.shail.pipeline_status import delete_status
                    from apps.shail.blueprint_queue import delete_jobs_for_memory
                    from apps.shail.capture_store import delete_memory_state
                    delete_blueprint(memory_id)
                    delete_status(memory_id)
                    delete_jobs_for_memory(memory_id)
                    delete_memory_state(memory_id)
                except Exception:
                    pass
                deleted += 1
        except Exception:
            pass

    from apps.shail.websocket_server import websocket_manager
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(websocket_manager.broadcast_event("INVALIDATE_CACHE", {
            "keys": ["memories", "stats"],
            "action": "clear"
        }))
    except RuntimeError:
        pass

    return BulkDeleteResponse(deleted=deleted)


@dashboard_router.get("/stats", response_model=DashboardStats)
async def get_stats(
    user_id: str = Depends(get_current_user),
) -> DashboardStats:
    """Compute aggregate stats for the dashboard overview."""
    import asyncio
    records = await asyncio.to_thread(_get_all_user_records, user_id)
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
    import asyncio
    records = await asyncio.to_thread(_get_all_user_records, user_id)
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

class GraphApiMemory(BaseModel):
    id: str
    memory: str
    content: Optional[str] = None
    isStatic: bool = False
    spaceId: str = ""
    isLatest: bool = True
    isForgotten: bool = False
    forgetAfter: Optional[str] = None
    forgetReason: Optional[str] = None
    version: int = 1
    parentMemoryId: Optional[str] = None
    rootMemoryId: Optional[str] = None
    createdAt: str
    updatedAt: str
    relation: Optional[Dict[str, str]] = None
    updatesMemoryId: Optional[str] = None
    nextVersionId: Optional[str] = None
    memoryRelations: Optional[Dict[str, str]] = None
    spaceContainerTag: Optional[str] = None

class GraphApiDocument(BaseModel):
    id: str
    title: Optional[str] = None
    summary: Optional[str] = None
    documentType: str
    createdAt: str
    updatedAt: str
    memories: List[GraphApiMemory]

class MemoryGraph(BaseModel):
    documents: List[GraphApiDocument]


@dashboard_router.get("/graph", response_model=MemoryGraph)
@dashboard_router.get("/memories/graph", response_model=MemoryGraph)
async def memory_graph(
    user_id: str = Depends(get_current_user),
) -> MemoryGraph:
    """
    Build a semantic knowledge graph from the user's memories.

    Edge types (in priority order):
      1. conversation  — same conversationId / chat session
      2. same_url      — identical sourceUrl (strong signal)
      3. shared_domain — same domain but different pages
      4. shared_tags   — overlapping metadata tags
      5. same_app_day  — same sourceApp on the same UTC day
      6. token_overlap — significant word overlap in title+summary (TF-IDF-like)

    Each edge has a `type` and `weight` field so the dashboard can style edges
    differently. Multiple edge types between the same pair are collapsed into
    one edge (highest weight wins).
    """
    import asyncio
    records = await asyncio.to_thread(_get_all_user_records, user_id)

    nodes: List[GraphNode] = []
    edges: List[GraphEdge] = []

    docs_by_id: Dict[str, GraphApiDocument] = {}

    for rid, doc, meta in records:
        meta = meta or {}
        ts = meta.get("timestamp", datetime.now(timezone.utc).isoformat())
        url = meta.get("sourceUrl", "")
        conv = meta.get("conversationId") or meta.get("sessionId") or ""

        doc_id = url if url else (conv if conv else f"doc_{rid}")
        if doc_id not in docs_by_id:
            docs_by_id[doc_id] = GraphApiDocument(
                id=doc_id,
                title=meta.get("title") or url or "Untitled",
                summary=None,
                documentType=meta.get("sourceApp", "web"),
                createdAt=ts,
                updatedAt=ts,
                memories=[]
            )

        mem = GraphApiMemory(
            id=rid,
            memory=meta.get("summary") or doc or "",
            content=doc,
            isStatic=False,
            spaceId="",
            isLatest=True,
            isForgotten=bool(meta.get("isForgotten")),
            forgetAfter=meta.get("forgetAfter"),
            forgetReason=None,
            version=int(meta.get("version", 1) or 1),
            parentMemoryId=meta.get("parentId") or meta.get("parent_memory_id"),
            rootMemoryId=None,
            createdAt=ts,
            updatedAt=ts,
            relation=None,
            updatesMemoryId=None,
            nextVersionId=None,
            memoryRelations=meta.get("memoryRelations") or {},
            spaceContainerTag=None
        )
        docs_by_id[doc_id].memories.append(mem)

    return MemoryGraph(documents=list(docs_by_id.values()))



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
