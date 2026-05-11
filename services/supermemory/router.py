"""Route handlers for SuperMemory sidecar (Phase 4)."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from services.supermemory.auth import verify_api_key
from services.supermemory.models import (
    HealthResponse,
    IngestRequest,
    IngestResponse,
    MemoryHit,
    QueryRequest,
    QueryResponse,
    ReindexResponse,
    StatsResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_api_key)])


# ── /query ─────────────────────────────────────────────────────────────── #

@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """Hybrid retrieval: local + optional SuperMemory global."""
    try:
        from shail.memory.hybrid import hybrid_search
        hits_raw = await hybrid_search(
            req.q,
            namespace=req.namespace,
            k=req.k,
            retrieval_strategy=req.strategy,
            use_global_memory=(req.strategy in ("hybrid", "global_only")),
        )
        hits = [
            MemoryHit(
                content=h[0],
                score=float(h[1]),
                metadata=h[2] if len(h) > 2 else {},
                surface=h[2].get("surface", "unknown") if len(h) > 2 and h[2] else "unknown",
            )
            for h in hits_raw
        ]
        return QueryResponse(
            hits=hits,
            total=len(hits),
            strategy_used=req.strategy,
        )
    except Exception as exc:
        logger.error("query endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── /ingest ────────────────────────────────────────────────────────────── #

@router.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest) -> IngestResponse:
    """Ingest content into local + optionally global SuperMemory."""
    try:
        import hashlib
        content_hash = hashlib.sha256(req.content.encode()).hexdigest()
        mem_id = None

        # Local ingest
        try:
            import asyncio
            from shail.memory.rag import ingest as rag_ingest
            record = {
                "content":   req.content,
                "metadata":  {**req.metadata, "tags": req.container_tags, "quality_score": req.quality_score},
                "namespace": req.namespace,
                "tags":      req.container_tags,
            }
            if asyncio.iscoroutinefunction(rag_ingest):
                await rag_ingest(records=[record])
            else:
                await asyncio.to_thread(rag_ingest, records=[record])
        except Exception as exc:
            logger.warning("Sidecar local ingest failed: %s", exc)

        # Global ingest
        try:
            from apps.shail.settings import get_settings
            if get_settings().supermemory_use_global:
                from shail.memory.supermemory_client import get_supermemory_client
                mem_id = await get_supermemory_client().ingest_global(
                    content=req.content,
                    metadata=req.metadata,
                    container_tags=req.container_tags,
                    custom_id=content_hash,
                )
        except Exception as exc:
            logger.warning("Sidecar global ingest failed: %s", exc)

        return IngestResponse(id=mem_id or content_hash, status="ok")
    except Exception as exc:
        logger.error("ingest endpoint error: %s", exc)
        return IngestResponse(status="error", message=str(exc))


# ── /health ────────────────────────────────────────────────────────────── #

@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    local_ok = False
    global_ok = False
    cache_ok  = False
    cache_backend = "unknown"

    try:
        from shail.memory.rag import search as rag_search
        rag_search("health check", k=1)
        local_ok = True
    except Exception:
        pass

    try:
        from shail.memory.supermemory_client import get_supermemory_client
        global_ok = await get_supermemory_client().health_check()
    except Exception:
        pass

    try:
        from shail.memory.cache import get_retrieval_cache
        c = get_retrieval_cache()
        cache_ok = c._enabled
        cache_backend = c._backend_type
    except Exception:
        pass

    status = "ok" if local_ok else ("degraded" if global_ok else "error")
    return HealthResponse(
        status=status,
        local_rag=local_ok,
        global_supermemory=global_ok,
        cache=cache_ok,
        cache_backend=cache_backend,
    )


# ── /stats ─────────────────────────────────────────────────────────────── #

@router.get("/stats", response_model=StatsResponse)
async def stats() -> StatsResponse:
    cache_bytes = 0
    cache_backend = "unknown"
    sm_reachable = False

    try:
        from shail.memory.cache import get_retrieval_cache
        c = get_retrieval_cache()
        cache_bytes   = c.size_bytes()
        cache_backend = c._backend_type
    except Exception:
        pass

    try:
        from shail.memory.supermemory_client import get_supermemory_client
        sm_reachable = await get_supermemory_client().health_check()
    except Exception:
        pass

    return StatsResponse(
        total_docs_local=0,   # would need VectorStore.count() — extend later
        cache_size_bytes=cache_bytes,
        cache_backend=cache_backend,
        supermemory_reachable=sm_reachable,
    )


# ── /reindex ───────────────────────────────────────────────────────────── #

@router.post("/reindex", response_model=ReindexResponse)
async def reindex() -> ReindexResponse:
    """Trigger local Chroma reindex (placeholder — extend per VectorStore impl)."""
    try:
        # Hook into rag.reindex if available
        from shail.memory import rag
        if hasattr(rag, "reindex"):
            import asyncio
            if asyncio.iscoroutinefunction(rag.reindex):
                await rag.reindex()
            else:
                await asyncio.to_thread(rag.reindex)
        return ReindexResponse(status="ok", message="Reindex triggered")
    except Exception as exc:
        return ReindexResponse(status="error", message=str(exc))
