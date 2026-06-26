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

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from shail.memory.rag import _get_store, ingest, search as rag_search
from apps.shail.settings import get_settings
from apps.shail.auth_store import (
    get_user_by_api_key, touch_api_key_last_used, touch_user_last_seen,
    get_user_settings, update_user_settings,
)
from apps.shail.capture_log import write_event
from apps.shail.blueprints import (
    generate_blueprint, get_blueprint as bp_get,
    get_blueprint_ids,
)
from apps.shail.memory_delete import delete_memory_everywhere
from apps.shail.source_normalization import (
    is_browser_memory,
    normalize_browser_metadata,
)

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
    Authentication is always required — raises HTTP 401 if no valid key.
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Sign in at http://localhost:8000/dashboard",
        )
    key = credentials.credentials
    user_id = get_user_by_api_key(key)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    touch_api_key_last_used(key)
    touch_user_last_seen(user_id)
    return f"user_{user_id}"


# ── Pydantic request / response models ─────────────────────────────────────

class CaptureSegment(BaseModel):
    """Typed segment from the capture source. Preserves code/tables/mermaid/etc.

    The extension may send a `segments` array alongside (or instead of)
    `userText`/`assistantText`/`pageContent`. When present, segments override
    the flat-text fields for blueprint extraction and survive intact through
    the pipeline.
    """
    kind: str = Field(..., description="text|markdown|code|table|mermaid|math|html|json|image_ref|tool_call|tool_result")
    content: str
    language: Optional[str] = None
    role: Optional[str] = None
    metadata: Optional[dict] = None


class CaptureRequest(BaseModel):
    """Mirrors CaptureCandidate from contracts.ts."""
    customId: str = Field(..., description="SHA-256 fingerprint — used as vector store record ID")
    conversationId: Optional[str] = None  # provider UUID; present when stable customId scheme is active
    conversationIdTemporary: Optional[bool] = None
    previousConversationId: Optional[str] = None
    eventType: str = Field(..., description="ai_conversation | page_visit | manual")
    sourceApp: str = Field(..., description="chatgpt | claude | gemini | perplexity | web")
    sourceUrl: str
    timestamp: str = Field(..., description="ISO 8601 UTC")
    title: Optional[str] = None
    userText: Optional[str] = None        # ai_conversation only
    assistantText: Optional[str] = None   # ai_conversation only
    pageContent: Optional[str] = None     # page_visit only
    segments: Optional[list[CaptureSegment]] = Field(
        default=None,
        description="Optional typed segments preserving code/tables/mermaid/markdown. "
                    "When present, takes precedence over flat text fields for blueprint extraction.",
    )
    turnCount: Optional[int] = None
    captureMode: Optional[str] = None
    captureSource: Optional[str] = None
    captureInitiator: Optional[str] = None


class CaptureResponse(BaseModel):
    memoryId: str
    status: str   # "saved" | "created" | "queued" | "duplicate" | "denied"
    summary: Optional[str] = None
    reason: Optional[str] = None


class RetentionRequest(BaseModel):
    policy: str = Field(..., description="keep_raw | blueprint_only | decide_later")


def _session_memory_id(conversation_id: str) -> str:
    return hashlib.sha256(f"shail_session_{conversation_id}".encode("utf-8")).hexdigest()


def _merge_previous_conversation_content(req: CaptureRequest, content: str, namespace: str) -> str:
    """Fold temporary pre-provider-ID chat content into the permanent capture.

    New chats often start on a URL with no stable provider conversation ID. The
    extension uses a temporary UUID in that window, then sends
    previousConversationId once the real provider ID appears. Preserve the
    early transcript instead of leaving an orphan memory.
    """
    previous = (req.previousConversationId or "").strip()
    if not previous or previous == (req.conversationId or ""):
        return content
    previous_id = _session_memory_id(previous)
    try:
        from apps.shail import raw_transcripts as _rt
        old = _rt.get(previous_id)
    except Exception:
        old = None
    if not old or old.get("namespace") != namespace:
        return content
    old_content = (old.get("content") or "").strip()
    if not old_content or old_content in content:
        return content
    return f"{old_content}\n\n---\n\n{content}"


def _cleanup_previous_conversation(req: CaptureRequest, namespace: str) -> None:
    previous = (req.previousConversationId or "").strip()
    if not previous or previous == (req.conversationId or ""):
        return
    previous_id = _session_memory_id(previous)
    try:
        store = _get_store()
        delete_memory_everywhere(store, previous_id, [namespace])
    except Exception as exc:
        logger.debug("temporary conversation vector cleanup skipped for %s: %s", previous_id, exc)
    try:
        from apps.shail import raw_transcripts as _rt
        old = _rt.get(previous_id)
        if old and old.get("namespace") == namespace:
            _rt.delete(previous_id)
    except Exception as exc:
        logger.debug("temporary conversation raw cleanup skipped for %s: %s", previous_id, exc)


def _canonicalize_conversation_memory_id(req: CaptureRequest, namespace: str) -> None:
    """Reuse the existing memory for the same source app conversation."""
    conversation_id = (req.conversationId or "").strip()
    if not conversation_id or bool(req.conversationIdTemporary):
        return
    try:
        from apps.shail import raw_transcripts as _rt
        existing = _rt.find_latest(conversation_id=conversation_id, namespace=namespace)
    except Exception as exc:
        logger.debug("conversation canonicalization lookup skipped: %s", exc)
        return
    if not existing:
        return
    meta = existing.get("metadata") or {}
    if meta.get("sourceApp") != req.sourceApp:
        return
    existing_id = existing.get("memory_id")
    if existing_id:
        req.customId = existing_id


class SearchRequest(BaseModel):
    query: str = Field(default="")
    k: int = Field(default=20, ge=1, le=100)
    sourceApp: Optional[str] = None
    after: Optional[str] = None   # ISO 8601 — return only memories with timestamp >= after


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


class AltitudePoint(BaseModel):
    date: str
    bytes: int
    captures: int
    deletes: int = 0


class AltitudeResponse(BaseModel):
    points: List[AltitudePoint]
    totalBytes: int
    totalCaptures: int
    weekOverWeekPct: int


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
    meta = normalize_browser_metadata(meta, content)
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


def _raw_transcript_to_item(row: Dict[str, Any], include_content: bool = False) -> MemoryItem:
    """Convert a raw_transcripts row into the same shape as vector-backed memories."""
    meta = normalize_browser_metadata(row.get("metadata") or {}, row.get("content") or "")
    memory_id = row.get("memory_id") or meta.get("customId") or meta.get("id") or str(uuid.uuid4())
    content = row.get("content") or ""
    if row.get("transcript_deleted_at"):
        content = ""
    title = meta.get("title") or ""
    if not title:
        m = re.match(r"^\[(\w+)\]\s+([^\n]+)", content or "")
        title = m.group(2).strip() if m else ""
    body_start = (content or "").find("\n\n")
    body = content[body_start + 2:] if body_start >= 0 else (content or "")
    summary = meta.get("summary") or body[:400] or "Pending memory indexing"
    timestamp = meta.get("timestamp") or row.get("captured_at") or datetime.now(timezone.utc).isoformat()
    return MemoryItem(
        id=memory_id,
        customId=meta.get("customId", memory_id),
        eventType=meta.get("eventType", row.get("content_type", "page_visit")),
        sourceApp=meta.get("sourceApp", "web"),
        sourceUrl=meta.get("sourceUrl", ""),
        title=title,
        summary=summary,
        timestamp=timestamp,
        tags=_parse_tags(meta.get("tags")),
        pinned=meta.get("pinned", "false") == "true",
        score=None,
        content=content if include_content else None,
    )


async def _broadcast_memory_invalidation(action: str, memory_id: Optional[str] = None) -> None:
    try:
        from apps.shail.websocket_server import websocket_manager
        await websocket_manager.broadcast_event("INVALIDATE_CACHE", {
            "keys": ["memories", "stats"],
            "action": action,
            **({"id": memory_id} if memory_id else {}),
        })
    except Exception as exc:
        logger.debug("memory invalidation broadcast failed: %s", exc)


def _logical_record_id(record_id: str, meta: Dict[str, Any]) -> str:
    return meta.get("customId") or meta.get("parent_memory_id") or meta.get("id") or record_id


def _parse_capture_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _collect_user_capture_records(namespace: str) -> Dict[str, Dict[str, Any]]:
    """Return one full-fidelity row per logical capture for dashboard metrics.

    Raw transcript rows are preferred over vector chunks because they preserve
    the full transcript text. Vector rows remain the fallback for older records
    that do not have raw transcript materialization.
    """
    records: Dict[str, Dict[str, Any]] = {}
    store = _get_store()

    if hasattr(store, "collection"):
        try:
            result = store.collection.get(
                where={"namespace": namespace},
                include=["documents", "metadatas"],
                limit=5000,
            )
            for rid, doc, meta in zip(
                result.get("ids", []),
                result.get("documents", []) or [],
                result.get("metadatas", []) or [],
            ):
                meta = meta or {}
                if not is_browser_memory(meta, doc or ""):
                    continue
                meta = normalize_browser_metadata(meta, doc or "")
                logical_id = _logical_record_id(rid, meta)
                current = records.get(logical_id)
                chunk_index = int(meta.get("chunk_index", 0) or 0)
                if current is None or chunk_index == 0:
                    records[logical_id] = {"content": doc or "", "metadata": meta}
        except Exception as exc:
            logger.warning("Altitude vector fetch failed for %s: %s", namespace, exc)

    try:
        from apps.shail import raw_transcripts as _rt
        for raw in _rt.list_recent(namespace=namespace, limit=5000):
            raw_id = raw.get("memory_id")
            if not raw_id:
                continue
            content = raw.get("content") or ""
            meta = raw.get("metadata") or {}
            if not is_browser_memory(meta, content):
                continue
            meta = normalize_browser_metadata(meta, content)
            meta.setdefault("timestamp", raw.get("captured_at"))
            records[raw_id] = {"content": content, "metadata": meta}
    except Exception as exc:
        logger.warning("Altitude raw transcript merge failed for %s: %s", namespace, exc)

    return records


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


# ── Chunked capture helpers ───────────────────────────────────────────────────

_CHUNK_SIZE    = 800   # chars per chunk (tunable)
_CHUNK_OVERLAP = 120   # overlap between consecutive chunks


def _chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping fixed-size chunks. Returns [] when text is empty."""
    if not text or not text.strip():
        return []
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def _build_capture_records(
    *,
    req: Any,
    content: str,
    summary: str,
    namespace: str,
    chunked: bool,
) -> List[Dict]:
    """Build the list of ingest records for a single capture.

    When `chunked=False` (or content is empty/short): returns a single record
    keyed by `req.customId`, matching the legacy single-record shape.

    When `chunked=True` and content is long enough to split: returns one record
    per chunk, keyed `req.customId#{index:03d}`, with parent_memory_id,
    chunk_index, chunk_total, and chunk_hash (first 16 hex chars of sha256).

    Emits `telemetry.INGEST_CHUNKS_PER_CAPTURE` histogram regardless of path.
    Pure: no Ollama, no Chroma, no I/O.
    """
    from apps.shail import telemetry

    base_meta = {
        "id": req.customId,
        "customId": req.customId,
        "conversationId": getattr(req, "conversationId", "") or "",
        "eventType": req.eventType,
        "sourceApp": req.sourceApp,
        "source": f"browser_{req.sourceApp}",
        "tier": "important",
        "sourceUrl": req.sourceUrl,
        "title": getattr(req, "title", "") or "",
        "summary": summary,
        "timestamp": req.timestamp,
        "captured_ts": str(time.time()),
        "pinned": "false",
        "tags": "[]",
        "namespace": namespace,
    }

    chunks: List[str] = _chunk_text(content) if chunked else []

    if not chunks:
        # Single-record (legacy) path — also covers empty content + chunked=True
        telemetry.observe(telemetry.INGEST_CHUNKS_PER_CAPTURE, 1)
        return [{"id": req.customId, "content": content, "namespace": namespace, "metadata": base_meta}]

    records: List[Dict] = []
    total = len(chunks)
    for idx, chunk_text in enumerate(chunks):
        chunk_id = f"{req.customId}#{idx:03d}"
        chunk_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:16]
        meta = dict(base_meta)
        meta["parent_memory_id"] = req.customId
        meta["chunk_index"] = idx
        meta["chunk_total"] = total
        meta["chunk_hash"] = chunk_hash
        meta["id"] = chunk_id
        meta["customId"] = req.customId  # still the original for dedup
        records.append({"id": chunk_id, "content": chunk_text, "namespace": namespace, "metadata": meta})

    telemetry.observe(telemetry.INGEST_CHUNKS_PER_CAPTURE, total)
    return records


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
        embeddingModel=settings.ollama_embed_model,
        memoriesCount=count,
    )


def _bg_ingest_and_index(
    memory_id: str,
    content: str,
    namespace: str,
    metadata: dict,
    log_user_id: Optional[str],
    eventType: str,
    sourceApp: str,
):
    """Run heavy vector embeddings creation and queuing tasks in the background."""
    try:
        chunk_count = ingest(records=[{
            "id": memory_id,
            "content": content,
            "namespace": namespace,
            "metadata": metadata,
        }])
    except Exception as exc:
        logger.error("Background ingest failed for %s: %s", memory_id, exc)
        chunk_count = 0

    if chunk_count == 0:
        logger.warning(
            "embed failed for %s — raw transcript persisted, queued for retry",
            memory_id,
        )
        write_event("CAPTURE", f"{sourceApp}: {metadata.get('title')[:80]} (degraded)",
                    user_id=log_user_id, ref_id=memory_id)
        try:
            from apps.shail.blueprint_queue import enqueue as _bq_enqueue
            _bq_enqueue(
                memory_id=memory_id,
                session_id=None,
                user_id=log_user_id or "local",
                content_type=eventType,
            )
        except Exception as exc:
            logger.warning("blueprint enqueue failed for %s: %s", memory_id, exc)
        return

    try:
        from apps.shail import raw_transcripts as _rt
        _rt.mark_embedded(memory_id, True)
    except Exception:
        pass

    write_event("CAPTURE", f"{sourceApp}: {metadata.get('title')[:80]}",
                user_id=log_user_id, ref_id=memory_id)
    write_event("INDEX", f"embedded {chunk_count} chunk(s) for {sourceApp}",
                user_id=log_user_id, ref_id=memory_id)

    try:
        from apps.shail.blueprint_queue import enqueue as _bq_enqueue
        from apps.shail import pipeline_status as _ps
        _bq_enqueue(
            memory_id=memory_id,
            session_id=None,
            user_id=log_user_id or "local",
            content_type=eventType,
        )
        _ps.mark_stage(memory_id, "blueprint_queued", "active",
                       detail={"content_type": eventType})
    except Exception as exc:
        logger.warning("blueprint enqueue failed for %s: %s", memory_id, exc)

    from apps.shail.websocket_server import websocket_manager
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(websocket_manager.broadcast_event("INVALIDATE_CACHE", {
            "keys": ["memories", "stats"],
            "action": "create",
            "id": memory_id
        }))
    except RuntimeError:
        pass


@browser_router.post("/capture", response_model=CaptureResponse, status_code=201)
async def capture_memory(
    req: CaptureRequest,
    background_tasks: BackgroundTasks,
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
    _canonicalize_conversation_memory_id(req, namespace)

    # Segment-aware capture: if the extension sent typed segments, render them
    # to markdown for storage AND keep the typed list for downstream
    # consumers. Flat-text fields are still respected for back-compat.
    from apps.shail import segments as _segs
    typed_segments: list[_segs.Segment] = []
    if req.segments:
        for s in req.segments:
            typed_segments.append(_segs.Segment(
                kind=s.kind,
                content=s.content,
                language=s.language,
                role=s.role,
                metadata=s.metadata or {},
            ))

    if typed_segments:
        body = _segs.render_for_llm(typed_segments)
        if req.eventType == "ai_conversation":
            content = f"[{req.sourceApp}] {req.title or 'AI Conversation'}\n\n{body}"
        else:
            content = f"[web] {req.title or req.sourceUrl}\n\n{body}"
    elif req.eventType == "ai_conversation":
        content = (
            f"[{req.sourceApp}] {req.title or 'AI Conversation'}\n\n"
            f"User: {req.userText or ''}\n\n"
            f"Assistant: {req.assistantText or ''}"
        )
        # Parse the flat text into segments so the rest of the pipeline still
        # has a typed projection (useful for the status page and exporters).
        typed_segments = _segs.parse_segments(content)
    else:
        content = f"[web] {req.title or req.sourceUrl}\n\n{req.pageContent or ''}"
        typed_segments = _segs.parse_segments(content)

    # Dynamic ingest cap: raised from 50K to settings-configurable (default 2M)
    # so a full chat session — including code, tables, mermaid — fits without
    # the legacy truncation. Blueprint sizing is now handled downstream by
    # `dynamic_sizing.compute_budget`, not by truncating here.
    ingest_cap = get_settings().capture_ingest_max_chars
    if ingest_cap and len(content) > ingest_cap:
        content = content[:ingest_cap]
    content = _merge_previous_conversation_content(req, content, namespace)
    summary = content[:400]
    log_user_id = namespace.removeprefix("user_") if namespace.startswith("user_") else None

    # Plan B5: persist raw transcript BEFORE embed. If Ollama is down, the
    # capture is still safe in raw_transcripts; the blueprint queue worker
    # picks it up later. Without this, an Ollama outage discards the capture.
    metadata = {
        "id": req.customId,
        "customId": req.customId,
        "conversationId": req.conversationId or "",
        "conversationIdTemporary": bool(req.conversationIdTemporary),
        "previousConversationId": req.previousConversationId or "",
        "capture_source": req.captureSource or "",
        "eventType": req.eventType,
        "sourceApp": req.sourceApp,
        "source": f"browser_{req.sourceApp}",
        "tier": "important",
        "sourceUrl": req.sourceUrl,
        "title": req.title or "",
        "summary": summary,
        "timestamp": req.timestamp,
        "captured_ts": str(time.time()),
        "pinned": "false",
        "tags": "[]",
        "namespace": namespace,
    }
    try:
        from apps.shail import raw_transcripts as _rt
        _rt.save(
            memory_id=req.customId,
            user_id=log_user_id or "local",
            namespace=namespace,
            content_type=req.eventType,
            content=content,
            metadata=metadata,
            segments=typed_segments,
        )
    except Exception as exc:
        logger.warning("raw_transcripts.save failed for %s: %s — continuing", req.customId, exc)
    _cleanup_previous_conversation(req, namespace)

    # Schedule the heavy vector ingestion as a background task to prevent blocking the event loop
    background_tasks.add_task(_broadcast_memory_invalidation, "save", req.customId)
    background_tasks.add_task(
        _bg_ingest_and_index,
        req.customId,
        content,
        namespace,
        metadata,
        log_user_id,
        req.eventType,
        req.sourceApp,
    )

    return CaptureResponse(
        memoryId=req.customId,
        status="queued",
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
        # ── Browse mode: list all records visible to this user ────────────
        # Signed-in users see their namespace AND the anonymous namespace
        # (pre-login captures) until they claim them via /claim-anonymous.
        # Anonymous users see only browser_memory.
        try:
            if hasattr(store, "collection"):  # ChromaVectorStore
                # Single-namespace browse: only the authenticated user's namespace
                items: list[MemoryItem] = []
                seen_ids: set = set()
                try:
                    result = store.collection.get(
                        where={"namespace": namespace},
                        include=["documents", "metadatas"],
                        limit=5000,
                    )
                except Exception as ns_exc:
                    logger.warning("Browse namespace %s failed: %s", namespace, ns_exc)
                    result = {"ids": [], "documents": [], "metadatas": []}

                for rid, doc, meta in zip(
                    result.get("ids", []),
                    result.get("documents", []),
                    result.get("metadatas", []),
                ):
                    meta = meta or {}
                    if not is_browser_memory(meta, doc or ""):
                        continue
                    meta = normalize_browser_metadata(meta, doc or "")
                    logical_id = _logical_record_id(rid, meta)
                    if logical_id not in seen_ids:
                        seen_ids.add(logical_id)
                        items.append(_meta_to_item(logical_id, doc or "", 0.0, meta))

                try:
                    from apps.shail import raw_transcripts as _rt
                    for raw in _rt.list_recent(namespace=namespace, limit=5000, after=req.after):
                        raw_id = raw.get("memory_id")
                        if not raw_id or raw_id in seen_ids:
                            continue
                        if not is_browser_memory(raw.get("metadata") or {}, raw.get("content") or ""):
                            continue
                        seen_ids.add(raw_id)
                        items.append(_raw_transcript_to_item(raw))
                except Exception as raw_exc:
                    logger.warning("Raw transcript browse fallback failed: %s", raw_exc)

                if req.after:
                    items = [i for i in items if i.timestamp >= req.after]
                items.sort(key=lambda x: x.timestamp, reverse=True)
                return SearchResponse(items=items[: req.k], total=len(items))
            else:
                try:
                    from apps.shail import raw_transcripts as _rt
                    raw_items = [
                        _raw_transcript_to_item(raw)
                        for raw in _rt.list_recent(namespace=namespace, limit=req.k, after=req.after)
                        if is_browser_memory(raw.get("metadata") or {}, raw.get("content") or "")
                    ]
                    return SearchResponse(items=raw_items, total=len(raw_items))
                except Exception as raw_exc:
                    logger.warning("Raw transcript browse fallback failed: %s", raw_exc)
                    return SearchResponse(items=[], total=0)
        except Exception as exc:
            logger.error("Browse failed: %s", exc)
            return SearchResponse(items=[], total=0)

    # ── Semantic search ────────────────────────────────────────────────────
    try:
        results = rag_search(query=req.query, k=req.k, namespace=namespace)
        # Signed-in users: also search anonymous namespace and merge
        if namespace != NS_BROWSER:
            try:
                anon_results = rag_search(query=req.query, k=req.k, namespace=NS_BROWSER)
                results = list(results) + list(anon_results)
            except Exception:
                pass
    except Exception as exc:
        logger.error("Search failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    seen_ids: set = set()
    items = []
    for content, dist_score, metadata in results:
        if not is_browser_memory(metadata or {}, content):
            continue
        metadata = normalize_browser_metadata(metadata or {}, content)
        record_id = metadata.get("customId") or metadata.get("id") or str(uuid.uuid4())
        if record_id in seen_ids:
            continue
        seen_ids.add(record_id)
        similarity = max(0.0, 1.0 - dist_score / 2.0)
        items.append(_meta_to_item(record_id, content, similarity, metadata))

    # Sort by relevance then date-filter
    items.sort(key=lambda x: x.score or 0.0, reverse=True)
    if req.after:
        items = [i for i in items if i.timestamp >= req.after]

    return SearchResponse(items=items[: req.k], total=len(items))


@browser_router.get("/memories/{memory_id:path}", response_model=MemoryItem)
async def get_memory(
    memory_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> MemoryItem:
    """Fetch full content of a single memory (for the detail view).

    SECURITY: namespace-scoped — only returns a record if it belongs to the
    caller's namespace (user_{user_id} for authenticated, browser_memory for
    anonymous). Prevents cross-user false-positive dedup in the popup.
    """
    store = _get_store()
    primary_ns = _get_namespace(credentials)
    # Allow authenticated users to also see memories captured before they
    # signed in (anonymous browser_memory namespace).
    allowed_ns: set[str] = {primary_ns}
    if primary_ns != NS_BROWSER:
        allowed_ns.add(NS_BROWSER)

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
                if meta.get("namespace", NS_BROWSER) not in allowed_ns:
                    raise HTTPException(status_code=404, detail="Memory not found")
                if not is_browser_memory(meta, doc):
                    raise HTTPException(status_code=404, detail="Memory not found")
                return _meta_to_item(ids[0], doc, 0.0, meta, include_content=True)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("get_memory failed for %s: %s", memory_id, exc)
        try:
            result = store.collection.get(
                where={"customId": memory_id},
                include=["documents", "metadatas"],
            )
            ids = result.get("ids", []) or []
            if ids:
                rows = list(zip(
                    ids,
                    result.get("documents", []) or [],
                    result.get("metadatas", []) or [],
                ))
                # Namespace check — any chunk's namespace must be in allowed_ns
                first_meta = (rows[0][2] or {}) if rows else {}
                if first_meta.get("namespace", NS_BROWSER) not in allowed_ns:
                    raise HTTPException(status_code=404, detail="Memory not found")
                if not is_browser_memory(first_meta, rows[0][1] if rows else ""):
                    raise HTTPException(status_code=404, detail="Memory not found")
                rows.sort(key=lambda row: int((row[2] or {}).get("chunk_index", 0)))
                content = "\n\n".join((doc or "") for _, doc, _ in rows)
                meta = rows[0][2] or {}
                return _meta_to_item(memory_id, content, 0.0, meta, include_content=True)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("get_memory chunk fallback failed for %s: %s", memory_id, exc)
    try:
        from apps.shail import raw_transcripts as _rt
        raw = _rt.get(memory_id)
        if raw and raw.get("namespace") in allowed_ns:
            if not is_browser_memory(raw.get("metadata") or {}, raw.get("content") or ""):
                raise HTTPException(status_code=404, detail="Memory not found")
            return _raw_transcript_to_item(raw, include_content=True)
    except Exception as exc:
        logger.error("get_memory raw transcript fallback failed for %s: %s", memory_id, exc)
    raise HTTPException(status_code=404, detail="Memory not found")


@browser_router.delete("/memories/{memory_id:path}", response_model=DeleteResponse)
async def delete_memory(
    memory_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> DeleteResponse:
    """Delete a memory by ID.

    SECURITY (Sprint 1 fix): verify ownership via namespace before delete.
    Anonymous callers can delete only memories in NS_BROWSER namespace.
    """
    store = _get_store()
    if not hasattr(store, "collection"):
        raise HTTPException(status_code=501, detail="Delete not supported for this store")

    primary_ns = _get_namespace(credentials)
    # Try primary namespace first, then fall back to anonymous namespace so that
    # memories captured before the user signed in can still be deleted.
    namespaces = [primary_ns]
    if primary_ns != NS_BROWSER:
        namespaces.append(NS_BROWSER)

    try:
        logical_id, deleted_ids = delete_memory_everywhere(store, memory_id, namespaces)
        if not deleted_ids:
            from apps.shail import raw_transcripts as _rt
            raw = _rt.get(memory_id)
            if not raw or raw.get("namespace") not in namespaces:
                raise HTTPException(status_code=404, detail="Memory not found")
            _rt.delete(memory_id)
            logical_id = memory_id
        log_user_id = primary_ns.removeprefix("user_") if primary_ns.startswith("user_") else None
        write_event("PRUNE", f"memory deleted: {logical_id[:12]}",
                    user_id=log_user_id, ref_id=logical_id)
        await _broadcast_memory_invalidation("delete", logical_id)
        return DeleteResponse(ok=True, id=logical_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Delete failed for %s: %s", memory_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@browser_router.get("/blueprint/{memory_id}")
async def get_memory_blueprint(
    memory_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Fetch the structured blueprint for a memory.

    Returns 404 if no blueprint exists yet (extraction pending or failed).
    The dashboard MemDetail view polls this endpoint after a capture to
    surface decisions / open_questions / next_actions.
    """
    bp = bp_get(memory_id)
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not yet generated")
    return bp


@browser_router.get("/pipeline-status/{memory_id}")
async def get_pipeline_status(
    memory_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Return every pipeline stage for a memory_id.

    Answers: is the capture still being segmented? Is the transcript built?
    Has the blueprint extraction kicked off, and at what size? Which stage
    failed and why? The UI uses this to render a live progress timeline.
    """
    from apps.shail import pipeline_status as _ps
    from apps.shail import raw_transcripts as _rt
    status = _ps.get_status(memory_id)
    rt = _rt.get(memory_id)
    if rt:
        status["raw_transcript"] = {
            "content_chars": rt.get("content_chars"),
            "segment_count": rt.get("segment_count"),
            "embedded": bool(rt.get("embedded")),
            "blueprinted": bool(rt.get("blueprinted")),
            "captured_at": rt.get("captured_at"),
        }
    bp = bp_get(memory_id)
    if bp:
        import json as _json
        status["blueprint"] = {
            "present": True,
            "bytes": len(_json.dumps(bp, ensure_ascii=False)),
            "field_counts": {
                "decisions": len(bp.get("decisions") or []),
                "questions_answered": len(bp.get("questions_answered") or []),
                "open_questions": len(bp.get("open_questions") or []),
                "next_actions": len(bp.get("next_actions") or []),
                "key_entities": len(bp.get("key_entities") or []),
                "facts": len(bp.get("facts") or []),
                "metrics": len(bp.get("metrics") or []),
                "tables": len(bp.get("tables") or []),
                "reasoning_chains": len(bp.get("reasoning_chains") or []),
                "failed_attempts": len(bp.get("failed_attempts") or []),
            },
        }
    else:
        status["blueprint"] = {"present": False}
    return status


@browser_router.get("/pipeline-status")
async def list_pipeline_active(
    limit: int = 50,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Captures currently mid-pipeline (any stage in 'active' state)."""
    from apps.shail import pipeline_status as _ps
    return {"active": _ps.list_active(limit=limit)}


@browser_router.post("/memories/{memory_id:path}/retention")
async def set_memory_retention(
    memory_id: str,
    req: RetentionRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Set safe raw-transcript retention for a browser capture.

    Blueprint-only never deletes vector memory or blueprint rows. If the
    blueprint is not ready yet, the policy is persisted and redaction runs when
    `raw_transcripts.mark_blueprinted()` fires.
    """
    namespace = _get_namespace(credentials)
    from apps.shail import raw_transcripts as _rt
    rt = _rt.get(memory_id)
    if not rt or rt.get("namespace") != namespace:
        raise HTTPException(status_code=404, detail="Memory not found")
    try:
        result = _rt.set_retention_policy(memory_id, req.policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "no_blueprint_stored":
            raise HTTPException(status_code=409, detail="Blueprint not yet generated")
        raise HTTPException(status_code=404, detail=reason or "Memory not found")
    return result


@browser_router.get("/captures/state")
async def get_capture_state(
    memory_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    source_url: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Single source of truth for extension/dashboard capture surfaces."""
    namespace = _get_namespace(credentials)
    from apps.shail import raw_transcripts as _rt
    from apps.shail import pipeline_status as _ps
    from apps.shail.blueprint_queue import job_for_memory

    rt = _rt.find_latest(
        memory_id=memory_id,
        conversation_id=conversation_id,
        source_url=source_url,
        namespace=namespace,
    )
    if not rt:
        raise HTTPException(status_code=404, detail="Capture not found")

    mid = rt["memory_id"]
    metadata = rt.get("metadata") or {}
    pipeline = _ps.get_status(mid)
    bp = bp_get(mid)
    job = job_for_memory(mid)
    retention_policy = rt.get("retention_policy") or "keep_raw"
    if rt.get("transcript_deleted_at"):
        retention_policy = "transcript_deleted"
    return {
        "memory_id": mid,
        "conversation_id": metadata.get("conversationId") or conversation_id,
        "source_app": metadata.get("sourceApp") or rt.get("content_type") or "web",
        "source_url": metadata.get("sourceUrl") or source_url or "",
        "title": metadata.get("title") or "",
        "capture_mode": rt.get("capture_mode") or metadata.get("capture_mode") or "active",
        "capture_source": metadata.get("capture_source") or "",
        "capture_policy": "capturing",
        "retention_policy": retention_policy,
        "pipeline": {
            "current_stage": pipeline.get("current_stage"),
            "current_state": pipeline.get("current_state"),
            "stages": pipeline.get("stages") or {},
        },
        "blueprint": {
            "present": bool(bp),
            "job_state": job.get("state") if job else None,
            "last_error": job.get("last_error") if job else None,
        },
        "raw_transcript": {
            "content_chars": rt.get("content_chars"),
            "segment_count": rt.get("segment_count"),
            "embedded": bool(rt.get("embedded")),
            "blueprinted": bool(rt.get("blueprinted")),
            "transcript_deleted_at": rt.get("transcript_deleted_at"),
        },
        "updated_at": rt.get("captured_at"),
    }


class BlueprintIdsRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)


@browser_router.post("/blueprint-ids")
async def list_blueprint_ids(req: BlueprintIdsRequest) -> dict:
    """Return the subset of provided memory IDs that have a blueprint.

    Used by the Memories list to render BLUEPRINT badges with one batch
    query per page-load instead of one fetch per card.
    """
    return {"ids": list(get_blueprint_ids(req.ids))}


@browser_router.post("/capture/bulk", response_model=CaptureResponse, status_code=201)
async def capture_bulk(
    req: CaptureRequest,
    background_tasks: BackgroundTasks,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CaptureResponse:
    """
    Ingest a retroactive "full session" capture from the scroll-pump or bulk importer.
    
    Identical to /capture but sets `priority=-1` in the blueprint queue so live
    captures skip the line.
    """
    namespace = _get_namespace(credentials)
    _canonicalize_conversation_memory_id(req, namespace)
    
    # We expect flat text for bulk captures (no segments yet for retroactive).
    if req.eventType == "bulk_history" or req.eventType == "ai_conversation":
        content = (
            f"[{req.sourceApp}] {req.title or 'AI Conversation (Bulk)'}\n\n"
            f"{req.assistantText or ''}"
        )
    else:
        content = f"[web] {req.title or req.sourceUrl}\n\n{req.pageContent or ''}"
        
    from apps.shail import segments as _segs
    typed_segments = _segs.parse_segments(content)
        
    ingest_cap = get_settings().capture_ingest_max_chars
    if ingest_cap and len(content) > ingest_cap:
        content = content[:ingest_cap]
    content = _merge_previous_conversation_content(req, content, namespace)
    summary = content[:400]
    log_user_id = namespace.removeprefix("user_") if namespace.startswith("user_") else None

    # Determine capture mode
    # Safely access req model fields in case it's a dict or Pydantic model
    capture_mode = getattr(req, "captureMode", "bulk")
    if capture_mode not in ("bulk", "retroactive", "active"):
        capture_mode = "bulk"

    metadata = {
        "id": req.customId,
        "customId": req.customId,
        "conversationId": getattr(req, "conversationId", "") or "",
        "conversationIdTemporary": bool(getattr(req, "conversationIdTemporary", False)),
        "previousConversationId": getattr(req, "previousConversationId", "") or "",
        "capture_source": getattr(req, "captureSource", "") or "",
        "eventType": req.eventType,
        "sourceApp": req.sourceApp,
        "source": f"browser_{req.sourceApp}",
        "tier": "important",
        "sourceUrl": req.sourceUrl,
        "title": getattr(req, "title", "") or "",
        "summary": summary,
        "timestamp": req.timestamp,
        "captured_ts": str(time.time()),
        "pinned": "false",
        "tags": "[]",
        "namespace": namespace,
        "capture_mode": capture_mode,
        "turnCount": getattr(req, "turnCount", 0) or 0,
    }
    
    try:
        from apps.shail import raw_transcripts as _rt
        _rt.save(
            memory_id=req.customId,
            user_id=log_user_id or "local",
            namespace=namespace,
            content_type=req.eventType,
            content=content,
            metadata=metadata,
            segments=typed_segments,
            capture_mode=capture_mode,
        )
    except Exception as exc:
        logger.warning("raw_transcripts.save failed for %s: %s — continuing", req.customId, exc)
    _cleanup_previous_conversation(req, namespace)

    # Wrap the background task logic so we can pass priority=-1 to enqueue
    def _bg_bulk_ingest():
        try:
            chunk_count = ingest(records=[{
                "id": req.customId,
                "content": content,
                "namespace": namespace,
                "metadata": metadata,
            }])
        except Exception as exc:
            logger.error("Background bulk ingest failed for %s: %s", req.customId, exc)
            chunk_count = 0
            
        if chunk_count > 0:
            try:
                from apps.shail import raw_transcripts as _rt
                _rt.mark_embedded(req.customId, True)
            except Exception:
                pass
            write_event("CAPTURE", f"{req.sourceApp}: {getattr(req, 'title', '')[:80]} ({capture_mode})",
                        user_id=log_user_id, ref_id=req.customId)
                        
        try:
            from apps.shail.blueprint_queue import enqueue as _bq_enqueue
            from apps.shail import pipeline_status as _ps
            _bq_enqueue(
                memory_id=req.customId,
                session_id=None,
                user_id=log_user_id or "local",
                content_type=req.eventType,
                priority=-1,  # Low priority for bulk
            )
            _ps.mark_stage(req.customId, "blueprint_queued", "active",
                           detail={"content_type": req.eventType, "priority": -1})
        except Exception as exc:
            logger.warning("blueprint enqueue failed for %s: %s", req.customId, exc)
            
    background_tasks.add_task(_bg_bulk_ingest)

    return CaptureResponse(
        memoryId=req.customId,
        status="queued",
        summary=summary,
    )


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
                include=["documents", "metadatas"],
                limit=5000,
            )
            metadatas: List[Dict[str, Any]] = []
            seen_ids: set[str] = set()
            for rid, doc, m in zip(
                result.get("ids", []),
                result.get("documents", []) or [],
                result.get("metadatas", []) or [],
            ):
                m = m or {}
                if not is_browser_memory(m, doc or ""):
                    continue
                m = normalize_browser_metadata(m, doc or "")
                logical_id = _logical_record_id(rid, m)
                if logical_id in seen_ids:
                    continue
                seen_ids.add(logical_id)
                metadatas.append(m)

            try:
                from apps.shail import raw_transcripts as _rt
                for raw in _rt.list_recent(namespace=namespace, limit=5000):
                    raw_id = raw.get("memory_id")
                    if not raw_id or raw_id in seen_ids:
                        continue
                    meta = raw.get("metadata") or {}
                    content = raw.get("content") or ""
                    if not is_browser_memory(meta, content):
                        continue
                    meta = normalize_browser_metadata(meta, content)
                    meta.setdefault("timestamp", raw.get("captured_at"))
                    seen_ids.add(raw_id)
                    metadatas.append(meta)
            except Exception as raw_exc:
                logger.warning("Stats raw transcript merge failed: %s", raw_exc)

            total = len(metadatas)

            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            this_week = sum(
                1 for m in metadatas if m.get("timestamp", "") >= week_ago
            )

            source_counts: Dict[str, int] = {}
            latest_ts: Optional[str] = None
            for m in metadatas:
                src = normalize_browser_metadata(m).get("sourceApp", "web")
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


@browser_router.get("/altitude", response_model=AltitudeResponse)
async def get_altitude(
    days: int = 7,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AltitudeResponse:
    """Real capture-volume series for the dashboard altitude chart.

    Bytes are computed from currently stored capture text, grouped by capture
    timestamp. Delete counts come from the live capture log PRUNE events.
    """
    days = max(1, min(days, 90))
    namespace = _get_namespace(credentials)
    user_id = namespace.removeprefix("user_") if namespace.startswith("user_") else ""
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=days - 1)

    buckets: Dict[str, Dict[str, int]] = {
        (start_day + timedelta(days=i)).isoformat(): {"bytes": 0, "captures": 0, "deletes": 0}
        for i in range(days)
    }

    for row in _collect_user_capture_records(namespace).values():
        meta = row.get("metadata") or {}
        dt = _parse_capture_timestamp(meta.get("timestamp") or meta.get("captured_at"))
        if not dt:
            continue
        day = dt.date()
        if day < start_day or day > today:
            continue
        key = day.isoformat()
        content = row.get("content") or ""
        buckets[key]["bytes"] += len(content.encode("utf-8"))
        buckets[key]["captures"] += 1

    if user_id:
        try:
            from apps.shail.capture_log import read_events
            for event in read_events(user_id, limit=200):
                if event.get("event_type") != "PRUNE":
                    continue
                dt = _parse_capture_timestamp(event.get("ts"))
                if not dt:
                    continue
                day = dt.date()
                if start_day <= day <= today:
                    buckets[day.isoformat()]["deletes"] += 1
        except Exception as exc:
            logger.warning("Altitude delete event merge failed for %s: %s", user_id, exc)

    points = [
        AltitudePoint(date=day, **values)
        for day, values in sorted(buckets.items())
    ]
    total_bytes = sum(p.bytes for p in points)
    total_captures = sum(p.captures for p in points)

    midpoint = max(1, len(points) // 2)
    previous = sum(p.captures for p in points[:midpoint])
    current = sum(p.captures for p in points[midpoint:])
    if previous > 0:
        week_over_week = round(((current - previous) / previous) * 100)
    else:
        week_over_week = 100 if current > 0 else 0

    return AltitudeResponse(
        points=points,
        totalBytes=total_bytes,
        totalCaptures=total_captures,
        weekOverWeekPct=week_over_week,
    )


# ── Export / Import ───────────────────────────────────────────────────────────

class ImportResponse(BaseModel):
    imported: int
    skipped: int


@browser_router.get("/export")
async def export_memories(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
):
    """Download all memories for the authenticated namespace as a JSON file."""
    store = _get_store()
    namespace = _get_namespace(credentials)
    try:
        if hasattr(store, "collection"):
            result = store.collection.get(
                where={"namespace": namespace},
                include=["documents", "metadatas"],
            )
            items = []
            seen_ids: set[str] = set()
            for rid, doc, meta in zip(
                result.get("ids", []),
                result.get("documents", []),
                result.get("metadatas", []),
            ):
                meta = meta or {}
                if not is_browser_memory(meta, doc or ""):
                    continue
                meta = normalize_browser_metadata(meta, doc or "")
                logical_id = _logical_record_id(rid, meta)
                if logical_id in seen_ids:
                    continue
                seen_ids.add(logical_id)
                items.append(_meta_to_item(logical_id, doc or "", 0.0, meta, include_content=True).dict())
            try:
                from apps.shail import raw_transcripts as _rt
                for raw in _rt.list_recent(namespace=namespace, limit=5000):
                    raw_id = raw.get("memory_id")
                    if not raw_id or raw_id in seen_ids:
                        continue
                    if not is_browser_memory(raw.get("metadata") or {}, raw.get("content") or ""):
                        continue
                    seen_ids.add(raw_id)
                    items.append(_raw_transcript_to_item(raw, include_content=True).dict())
            except Exception as raw_exc:
                logger.warning("Export raw transcript merge failed: %s", raw_exc)
            payload = json.dumps(items, ensure_ascii=False, indent=2)
            return Response(
                content=payload,
                media_type="application/json",
                headers={"Content-Disposition": 'attachment; filename="shail-export.json"'},
            )
    except Exception as exc:
        logger.error("Export failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    raise HTTPException(status_code=501, detail="Export not supported for this store")


@browser_router.post("/import", response_model=ImportResponse, status_code=200)
async def import_memories(
    body: List[MemoryItem],
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> ImportResponse:
    """Re-index a JSON export. Skips records whose customId already exists."""
    namespace = _get_namespace(credentials)
    store = _get_store()

    # Collect existing customIds to skip duplicates
    existing_ids: set = set()
    if hasattr(store, "collection"):
        try:
            existing = store.collection.get(
                where={"namespace": namespace}, include=[]
            )
            existing_ids = set(existing.get("ids", []))
        except Exception:
            pass

    imported = 0
    skipped = 0
    records_to_ingest = []
    for item in body:
        record_id = item.customId or item.id
        if record_id in existing_ids:
            skipped += 1
            continue
        content = item.content or item.summary or f"[{item.sourceApp}] {item.title}"
        records_to_ingest.append({
            "id": record_id,
            "content": content,
            "namespace": namespace,
            "metadata": {
                "id": record_id,
                "customId": record_id,
                "eventType": item.eventType,
                "sourceApp": item.sourceApp,
                "source": f"browser_{item.sourceApp}",
                "tier": "important",
                "sourceUrl": item.sourceUrl,
                "title": item.title or "",
                "summary": item.summary or content[:400],
                "timestamp": item.timestamp,
                "captured_ts": str(time.time()),
                "pinned": "true" if item.pinned else "false",
                "tags": json.dumps(item.tags),
                "namespace": namespace,
            },
        })

    if records_to_ingest:
        try:
            count = ingest(records=records_to_ingest)
            imported = count
        except Exception as exc:
            logger.error("Import ingest failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    return ImportResponse(imported=imported, skipped=skipped)


# ── Capture settings ──────────────────────────────────────────────────────────

class CaptureSettingsResponse(BaseModel):
    capture_enabled: bool
    blocked_domains: List[str]
    ollama_model: str
    external_api_key: str


class CaptureSettingsUpdate(BaseModel):
    capture_enabled: Optional[bool] = None
    blocked_domains: Optional[List[str]] = None
    ollama_model: Optional[str] = None
    external_api_key: Optional[str] = None


@browser_router.get("/capture-settings", response_model=CaptureSettingsResponse)
async def get_capture_settings(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CaptureSettingsResponse:
    """Get per-user capture settings from SQLite."""
    namespace = _get_namespace(credentials)
    # Anonymous users get static defaults — no user_settings row
    if namespace == NS_BROWSER:
        return CaptureSettingsResponse(
            capture_enabled=True, blocked_domains=[], ollama_model="", external_api_key=""
        )
    user_id = namespace.removeprefix("user_")
    settings = get_user_settings(user_id)
    return CaptureSettingsResponse(**settings)


@browser_router.put("/capture-settings", response_model=CaptureSettingsResponse)
async def put_capture_settings(
    req: CaptureSettingsUpdate,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CaptureSettingsResponse:
    """Update per-user capture settings."""
    namespace = _get_namespace(credentials)
    if namespace == NS_BROWSER:
        raise HTTPException(status_code=401, detail="Sign in to save settings")
    user_id = namespace.removeprefix("user_")
    updates = {k: v for k, v in req.dict().items() if v is not None}
    settings = update_user_settings(user_id, **updates)
    return CaptureSettingsResponse(**settings)


@browser_router.get("/anonymous-count")
async def get_anonymous_count() -> dict:
    """Count memories captured before sign-in (browser_memory namespace)."""
    try:
        result = _get_store().collection.get(where={"namespace": NS_BROWSER}, limit=5000)
        return {"count": len(result["ids"])}
    except Exception:
        return {"count": 0}


class ClaimAnonymousRequest(BaseModel):
    ids: Optional[list] = None  # None = claim all; list of str = claim specific IDs


@browser_router.post("/claim-anonymous")
async def claim_anonymous_memories(
    req: ClaimAnonymousRequest = ClaimAnonymousRequest(),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Move browser_memory records into the authenticated user's namespace.

    If req.ids is None, claims all anonymous records.
    If req.ids is a list of IDs, claims only those specific records.
    """
    namespace = _get_namespace(credentials)
    if namespace == NS_BROWSER:
        raise HTTPException(status_code=401, detail="Sign in required")
    try:
        if req.ids is not None:
            # Selective claim: fetch only the specified IDs
            result = _get_store().collection.get(
                ids=req.ids,
                include=["metadatas"],
            )
        else:
            # Claim all anonymous records
            result = _get_store().collection.get(
                where={"namespace": NS_BROWSER},
                include=["metadatas"],
                limit=5000,
            )
        ids = result["ids"]
        if not ids:
            return {"claimed": 0}
        # Only move records that are actually in the anonymous namespace
        paired = list(zip(ids, result["metadatas"]))
        to_move = [(rid, m) for rid, m in paired if m.get("namespace") == NS_BROWSER]
        if not to_move:
            return {"claimed": 0}
        move_ids = [rid for rid, _ in to_move]
        new_metas = [{**m, "namespace": namespace} for _, m in to_move]
        _get_store().collection.update(ids=move_ids, metadatas=new_metas)
        return {"claimed": len(move_ids)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@browser_router.get("/anonymous-memories")
async def list_anonymous_memories() -> dict:
    """List anonymous memories available to claim (summary only, no auth required)."""
    try:
        result = _get_store().collection.get(
            where={"namespace": NS_BROWSER},
            include=["metadatas"],
            limit=5000,
        )
        items = []
        for rid, meta in zip(result.get("ids", []), result.get("metadatas", [])):
            items.append({
                "id": rid,
                "title": meta.get("title") or meta.get("sourceUrl") or "",
                "sourceApp": meta.get("sourceApp", "web"),
                "timestamp": meta.get("timestamp", ""),
            })
        items.sort(key=lambda x: x["timestamp"], reverse=True)
        return {"items": items, "total": len(items)}
    except Exception:
        return {"items": [], "total": 0}


# ── LLM provider settings ──────────────────────────────────────────────────

class LLMSettingsResponse(BaseModel):
    """Returned to the dashboard. Never includes raw API keys — only flags."""
    active_provider: str = "ollama"
    active_model: str = ""
    openai_configured: bool = False
    anthropic_configured: bool = False


class LLMSettingsUpdate(BaseModel):
    """All fields optional. Pass an empty string for *_api_key to clear it."""
    active_provider: Optional[str] = None
    active_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None


class LLMTestRequest(BaseModel):
    provider: str
    api_key: str = ""
    model: str = ""


@browser_router.get("/llm-settings", response_model=LLMSettingsResponse)
async def get_llm_settings(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> LLMSettingsResponse:
    namespace = _get_namespace(credentials)
    if namespace == NS_BROWSER:
        # Anonymous: return defaults.
        return LLMSettingsResponse(active_provider="ollama")
    user_id = namespace.removeprefix("user_")
    s = get_user_settings(user_id)
    return LLMSettingsResponse(
        active_provider=s.get("active_provider") or "ollama",
        active_model=s.get("active_model") or "",
        openai_configured=bool(s.get("openai_api_key")),
        anthropic_configured=bool(s.get("anthropic_api_key")),
    )


@browser_router.put("/llm-settings", response_model=LLMSettingsResponse)
async def put_llm_settings(
    req: LLMSettingsUpdate,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> LLMSettingsResponse:
    namespace = _get_namespace(credentials)
    if namespace == NS_BROWSER:
        raise HTTPException(status_code=401, detail="Sign in to save settings")
    user_id = namespace.removeprefix("user_")
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if updates.get("active_provider") and updates["active_provider"] not in ("ollama", "openai", "anthropic"):
        raise HTTPException(status_code=400, detail="unknown provider")
    update_user_settings(user_id, **updates)
    return await get_llm_settings(credentials)


@browser_router.post("/llm-settings/test")
async def test_llm_settings(req: LLMTestRequest) -> dict:
    """Validate a provider/key combo without saving. Used by the Settings
    page Test button. No auth needed — the user types their own key here.
    """
    from apps.shail.llm import test_provider
    ok, info = await test_provider(req.provider, req.api_key, req.model)
    return {"ok": ok, "info": info}


# ── Capture log ────────────────────────────────────────────────────────────

@browser_router.get("/capture-log")
async def get_capture_log(
    limit: int = 200,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Return the most recent capture-log events for the signed-in user.
    In-memory ring buffer; resets on backend restart.
    """
    namespace = _get_namespace(credentials)
    if namespace == NS_BROWSER:
        raise HTTPException(status_code=401, detail="Sign in to view capture log")
    user_id = namespace.removeprefix("user_")
    from apps.shail.capture_log import read_events
    events = read_events(user_id, limit=limit)
    return {"events": events, "count": len(events)}


# ── Routes (auto-discovered memory clusters) ───────────────────────────────

@browser_router.get("/routes")
async def get_routes(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Auto-discovered clusters of the user's memories.

    Clustering rule (v1): bucket by tag. Memories with no tags fall into
    a per-source bucket (e.g. "chatgpt", "web") so we still surface a
    useful structure for fresh accounts. Returns the top 8 buckets by
    memory count.

    Read-only — the user can browse a cluster's memories, but the
    clustering is built by SHAIL, not the user.
    """
    store = _get_store()
    namespace = _get_namespace(credentials)
    if not hasattr(store, "collection"):
        return {"routes": []}

    try:
        result = store.collection.get(where={"namespace": namespace}, include=["metadatas"], limit=5000)
        metadatas = [m or {} for m in result.get("metadatas", [])]
    except Exception as e:
        logger.warning("get_routes store fetch failed: %s", e)
        return {"routes": []}

    buckets: Dict[str, Dict[str, Any]] = {}

    def _bump(label: str, axis: str, meta: dict) -> None:
        b = buckets.setdefault(
            label.lower(),
            {"label": label, "axis": axis, "count": 0, "latest_ts": "", "sample_titles": []},
        )
        b["count"] += 1
        ts = meta.get("timestamp", "")
        if ts and ts > b["latest_ts"]:
            b["latest_ts"] = ts
        title = meta.get("title")
        if title and len(b["sample_titles"]) < 3 and title not in b["sample_titles"]:
            b["sample_titles"].append(title)

    for m in metadatas:
        # Tags are stored as JSON-encoded strings in metadata.
        tags_raw = m.get("tags")
        tag_list: List[str] = []
        if isinstance(tags_raw, str) and tags_raw.startswith("["):
            try:
                tag_list = [t for t in json.loads(tags_raw) if isinstance(t, str)]
            except Exception:
                tag_list = []
        elif isinstance(tags_raw, list):
            tag_list = [t for t in tags_raw if isinstance(t, str)]

        if tag_list:
            for t in tag_list:
                _bump(t, "tag", m)
        else:
            src = m.get("sourceApp") or "web"
            _bump(src, "source", m)

    routes = sorted(buckets.values(), key=lambda r: (-r["count"], r["label"]))[:8]
    return {"routes": routes, "total_clusters": len(buckets)}


# ── Horizon (passive wishlist of suggested ascents) ────────────────────────

@browser_router.get("/horizon")
async def get_horizon(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Topics that recur across the user's memories but don't yet have an
    active ascent. Surface them as candidate goals — clicking "Start ascent"
    on the dashboard converts a horizon item into a real ascent.

    Detection (v1): pick clusters from /routes that have ≥3 memories AND
    whose label doesn't appear (case-insensitive) in any active ascent's
    name or description. Manual conversion only — we never auto-create.
    """
    namespace = _get_namespace(credentials)
    if namespace == NS_BROWSER:
        # Anonymous: no ascents to compare against, no horizon either.
        return {"items": []}
    user_id = namespace.removeprefix("user_")

    # Reuse /routes clustering by calling the same logic inline.
    routes_resp = await get_routes(credentials)
    clusters = routes_resp.get("routes", [])

    # Existing active ascents for filtering.
    from apps.shail.auth_store import _conn
    with _conn() as con:
        rows = con.execute(
            "SELECT name, description FROM ascents WHERE user_id = ? AND status = 'active'",
            (user_id,),
        ).fetchall()
    existing_text = " ".join(
        ((r["name"] or "") + " " + (r["description"] or "")) for r in rows
    ).lower()

    items: List[Dict[str, Any]] = []
    for c in clusters:
        if c.get("count", 0) < 3:
            continue
        label = (c.get("label") or "").strip()
        if not label:
            continue
        if label.lower() in existing_text:
            continue
        items.append({
            "label": label,
            "axis": c.get("axis", "tag"),
            "memory_count": c["count"],
            "latest_ts": c.get("latest_ts", ""),
            "sample_titles": c.get("sample_titles", []),
            "suggested_name": label.title(),
            "suggested_description": (
                f"Auto-detected from {c['count']} related memories. "
                + ("Recent: " + ", ".join(c.get("sample_titles", [])[:2]) if c.get("sample_titles") else "")
            ).strip(),
        })

    return {"items": items[:6], "total_candidates": len(items)}
