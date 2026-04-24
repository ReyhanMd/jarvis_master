"""
SHAIL Browser Extension API
────────────────────────────
Provides memory capture, search, retrieval, delete, and stats endpoints
consumed exclusively by the SHAIL Chrome extension.

All captures are stored in the "browser_memory" namespace of the local
vector store (ChromaDB by default). No auth required — local-only, CORS
is covered by the wildcard middleware in main.py.

Endpoints (all prefixed with /browser when mounted):
  GET  /me                  → Backend health + info for Options page
  POST /capture             → Ingest a page visit or AI conversation
  POST /search              → Semantic search + empty-query browse
  GET  /memories/{id}       → Full content fetch for detail view
  DELETE /memories/{id}     → Delete a memory
  GET  /stats               → Stats for popup cards
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from shail.memory.rag import _get_store, ingest, search as rag_search
from apps.shail.settings import get_settings
from apps.shail.auth_store import get_user_by_api_key, touch_api_key_last_used, touch_user_last_seen

logger = logging.getLogger(__name__)

browser_router = APIRouter()

# ── Namespace for all browser extension captures ───────────────────────────
NS_BROWSER = "browser_memory"  # legacy / anonymous namespace

_bearer = HTTPBearer(auto_error=False)


def _get_namespace(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> str:
    """
    Return the ChromaDB namespace for this request.
    - Authenticated (valid API key) → "user_{user_id}"
    - Anonymous / no key → "browser_memory" (backward-compatible)
    """
    if credentials:
        key = credentials.credentials
        user_id = get_user_by_api_key(key)
        if user_id:
            touch_api_key_last_used(key)
            touch_user_last_seen(user_id)
            return f"user_{user_id}"
    return NS_BROWSER


# ── Pydantic request / response models ─────────────────────────────────────

class CaptureRequest(BaseModel):
    """Mirrors CaptureCandidate from contracts.ts."""
    customId: str = Field(..., description="SHA-256 fingerprint — used as vector store record ID")
    eventType: str = Field(..., description="ai_conversation | page_visit | manual")
    sourceApp: str = Field(..., description="chatgpt | claude | gemini | perplexity | web")
    sourceUrl: str
    timestamp: str = Field(..., description="ISO 8601 UTC")
    title: Optional[str] = None
    userText: Optional[str] = None        # ai_conversation only
    assistantText: Optional[str] = None   # ai_conversation only
    pageContent: Optional[str] = None     # page_visit only


class CaptureResponse(BaseModel):
    memoryId: str
    status: str   # "created" | "duplicate"
    summary: Optional[str] = None


class SearchRequest(BaseModel):
    query: str = Field(default="")
    k: int = Field(default=20, ge=1, le=100)
    sourceApp: Optional[str] = None


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
    content: Optional[str] = None   # full content — only populated in GET /memories/{id}


class SearchResponse(BaseModel):
    items: List[MemoryItem]
    total: int


class DeleteResponse(BaseModel):
    ok: bool
    id: str


class MeResponse(BaseModel):
    status: str = "ok"
    backend: str = "jarvis_master"
    version: str = "1.0.0"
    vectorStore: str
    embeddingModel: str
    memoriesCount: int


class StatsResponse(BaseModel):
    totalMemories: int
    memoriesThisWeek: int
    topSource: Optional[str]
    lastCapturedAt: Optional[str]
    backendVersion: str = "1.0.0"


# ── Helpers ─────────────────────────────────────────────────────────────────

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


def _meta_to_item(
    record_id: str,
    content: str,
    score: float,
    meta: Dict[str, Any],
    include_content: bool = False,
) -> MemoryItem:
    """Convert raw vector store record into a MemoryItem."""
    # Pull title from metadata; fall back to parsing the content header
    title = meta.get("title", "")
    if not title:
        m = re.match(r"^\[(\w+)\]\s+([^\n]+)", content or "")
        title = m.group(2).strip() if m else ""

    # Strip the "[sourceApp] Title\n\n" capture header for the summary
    body_start = (content or "").find("\n\n")
    body = content[body_start + 2:] if body_start >= 0 else (content or "")
    summary = meta.get("summary") or body[:400]

    return MemoryItem(
        id=record_id,
        customId=meta.get("customId", record_id),
        eventType=meta.get("eventType", "page_visit"),
        sourceApp=meta.get("sourceApp", "web"),
        sourceUrl=meta.get("sourceUrl", ""),
        title=title,
        summary=summary,
        timestamp=meta.get("timestamp", datetime.now(timezone.utc).isoformat()),
        tags=_parse_tags(meta.get("tags")),
        pinned=meta.get("pinned", "false") == "true",
        score=round(score, 4) if score else None,
        content=content if include_content else None,
    )


def _count_memories(store, namespace: str) -> int:
    """Best-effort count of records in a given namespace."""
    try:
        if hasattr(store, "collection"):  # Chroma
            result = store.collection.get(
                where={"namespace": namespace},
                include=[],  # fastest — IDs only
            )
            return len(result.get("ids", []))
    except Exception:
        pass
    return 0


# ── Endpoints ────────────────────────────────────────────────────────────────

@browser_router.get("/me", response_model=MeResponse)
async def get_me(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> MeResponse:
    """Health check + backend info for the Options page."""
    settings = get_settings()
    store = _get_store()
    namespace = _get_namespace(credentials)
    count = _count_memories(store, namespace)
    return MeResponse(
        vectorStore=settings.rag_vector_store,
        embeddingModel=settings.rag_embedding_model,
        memoriesCount=count,
    )


@browser_router.post("/capture", response_model=CaptureResponse, status_code=201)
async def capture_memory(
    req: CaptureRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CaptureResponse:
    """
    Ingest a browser capture (page visit or AI conversation) into local memory.

    Uses `customId` as the vector store record ID so upsert is naturally
    idempotent — re-capturing the same page on the same day is a no-op.
    The extension's local dedup (shail_doc_index) prevents most redundant
    calls, but the backend handles any that slip through gracefully.
    """
    namespace = _get_namespace(credentials)

    # Build the content string in the canonical format the extension expects on readback
    if req.eventType == "ai_conversation":
        content = (
            f"[{req.sourceApp}] {req.title or 'AI Conversation'}\n\n"
            f"User: {req.userText or ''}\n\n"
            f"Assistant: {req.assistantText or ''}"
        )
    else:
        content = f"[web] {req.title or req.sourceUrl}\n\n{req.pageContent or ''}"

    content = content[:10_000]  # hard cap
    summary = content[:400]

    chunk_count = ingest(
        records=[
            {
                "id": req.customId,
                "content": content,
                "namespace": namespace,
                "metadata": {
                    "id": req.customId,
                    "customId": req.customId,
                    "eventType": req.eventType,
                    "sourceApp": req.sourceApp,
                    "sourceUrl": req.sourceUrl,
                    "title": req.title or "",
                    "summary": summary,
                    "timestamp": req.timestamp,
                    "pinned": "false",
                    "tags": "[]",
                    "namespace": namespace,
                },
            }
        ]
    )

    if chunk_count == 0:
        raise HTTPException(
            status_code=500,
            detail="Embedding failed — check GEMINI_API_KEY in .env",
        )

    return CaptureResponse(
        memoryId=req.customId,
        status="created",
        summary=summary,
    )


@browser_router.post("/search", response_model=SearchResponse)
async def search_memories(
    req: SearchRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> SearchResponse:
    """
    Search browser memories.

    Empty query → browse mode: returns all records sorted by timestamp (newest first).
    Non-empty query → semantic search via Gemini embeddings + ChromaDB KNN.
    """
    store = _get_store()
    namespace = _get_namespace(credentials)

    if not req.query.strip():
        # ── Browse mode: list all records in this namespace ───────────────
        # Semantic search with an empty string is meaningless; go direct to Chroma.
        try:
            if hasattr(store, "collection"):  # ChromaVectorStore
                result = store.collection.get(
                    where={"namespace": namespace},
                    limit=req.k,
                    include=["documents", "metadatas"],
                )
                items = []
                for rid, doc, meta in zip(
                    result.get("ids", []),
                    result.get("documents", []),
                    result.get("metadatas", []),
                ):
                    items.append(_meta_to_item(rid, doc or "", 0.0, meta or {}))
                # Sort newest first by timestamp string (ISO 8601 sorts lexicographically)
                items.sort(key=lambda x: x.timestamp, reverse=True)
                return SearchResponse(items=items, total=len(items))
            else:
                # PgVector: return empty for now (browse not yet implemented for PG)
                return SearchResponse(items=[], total=0)
        except Exception as exc:
            logger.error("Browse failed: %s", exc)
            return SearchResponse(items=[], total=0)

    # ── Semantic search ────────────────────────────────────────────────────
    try:
        results = rag_search(query=req.query, k=req.k, namespace=namespace)
    except Exception as exc:
        logger.error("Search failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    items = []
    for content, dist_score, metadata in results:
        # Chroma returns cosine distance (0 = identical, 2 = opposite).
        # Convert to similarity (1 = perfect match, 0 = no match).
        similarity = max(0.0, 1.0 - dist_score / 2.0)
        record_id = metadata.get("customId") or metadata.get("id") or str(uuid.uuid4())
        items.append(_meta_to_item(record_id, content, similarity, metadata))

    return SearchResponse(items=items, total=len(items))


@browser_router.get("/memories/{memory_id}", response_model=MemoryItem)
async def get_memory(memory_id: str) -> MemoryItem:
    """Fetch full content of a single memory (for the detail view)."""
    store = _get_store()
    if hasattr(store, "collection"):
        try:
            result = store.collection.get(
                ids=[memory_id],
                include=["documents", "metadatas"],
            )
            ids = result.get("ids", [])
            if ids:
                doc = (result.get("documents") or [""])[0] or ""
                meta = (result.get("metadatas") or [{}])[0] or {}
                return _meta_to_item(ids[0], doc, 0.0, meta, include_content=True)
        except Exception as exc:
            logger.error("get_memory failed for %s: %s", memory_id, exc)
    raise HTTPException(status_code=404, detail="Memory not found")


@browser_router.delete("/memories/{memory_id}", response_model=DeleteResponse)
async def delete_memory(memory_id: str) -> DeleteResponse:
    """Delete a memory by ID."""
    store = _get_store()
    if hasattr(store, "collection"):
        try:
            store.collection.delete(ids=[memory_id])
            return DeleteResponse(ok=True, id=memory_id)
        except Exception as exc:
            logger.error("Delete failed for %s: %s", memory_id, exc)
            raise HTTPException(status_code=500, detail=str(exc))
    raise HTTPException(status_code=501, detail="Delete not supported for this store")


@browser_router.get("/stats", response_model=StatsResponse)
async def get_stats(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> StatsResponse:
    """Compute stats for popup cards from local browser_memory records."""
    store = _get_store()
    namespace = _get_namespace(credentials)
    try:
        if hasattr(store, "collection"):  # ChromaVectorStore
            result = store.collection.get(
                where={"namespace": namespace},
                include=["metadatas"],
            )
            metadatas: List[Dict[str, Any]] = [m or {} for m in result.get("metadatas", [])]
            total = len(metadatas)

            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            this_week = sum(
                1 for m in metadatas if m.get("timestamp", "") >= week_ago
            )

            source_counts: Dict[str, int] = {}
            latest_ts: Optional[str] = None
            for m in metadatas:
                src = m.get("sourceApp", "web")
                source_counts[src] = source_counts.get(src, 0) + 1
                ts = m.get("timestamp")
                if ts and (latest_ts is None or ts > latest_ts):
                    latest_ts = ts

            top_source = (
                max(source_counts, key=lambda k: source_counts[k])
                if source_counts
                else None
            )

            return StatsResponse(
                totalMemories=total,
                memoriesThisWeek=this_week,
                topSource=top_source,
                lastCapturedAt=latest_ts,
            )
    except Exception as exc:
        logger.error("Stats failed: %s", exc)

    return StatsResponse(
        totalMemories=0,
        memoriesThisWeek=0,
        topSource=None,
        lastCapturedAt=None,
    )
