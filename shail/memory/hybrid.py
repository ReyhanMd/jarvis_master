"""Hybrid retrieval orchestrator (Sprint 3 PR2).

Combines exact-index hits (FTS5 BM25 + numeric WHERE) with semantic
hits (legacy `rag.search` → `_apply_time_decay`) via weighted fusion.

Returns the SAME shape as `rag.search`: `list[(content, score, metadata)]`.
This is the explicit contract that lets `chat_api._build_context`
drop in `hybrid_search` behind a feature flag without touching any
downstream rendering code.

Fusion ALWAYS runs both surfaces — never branch-skips on intent. Intent
only steers the per-surface weights and constructs a numeric filter
when the query syntax warrants one.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Tuple

from apps.shail import telemetry
from apps.shail.exact_index import (
    ExactHit,
    search_fts,
    search_numeric,
    search_numeric_historical,
)
from apps.shail.retrieval import fusion
from apps.shail.retrieval.intent import IntentPlan, QueryIntent, classify
from apps.shail.settings import get_settings
from shail.memory.rag import search as rag_search

logger = logging.getLogger(__name__)

# Tuned defaults. Eval suite drives future adjustments.
DEFAULT_K = 6
DEFAULT_OVERFETCH = 12
DEFAULT_FTS_THRESHOLD = 0.0       # post-normalization (0..1); 0 = no gate
DEFAULT_SEMANTIC_THRESHOLD = 0.0  # legacy semantic scores not normalized; gate off

SemanticHit = Tuple[str, float, dict]


def _run_exact(plan: IntentPlan, *, fts_k: int) -> List[ExactHit]:
    """Run BOTH exact surfaces (FTS + numeric) sequentially in one thread.

    Both touch SQLite which is not async-friendly, so a single worker
    thread is fine. Results deduped by `fact_id`; on collision keep the
    higher-scoring hit.
    """
    out: List[ExactHit] = []

    if plan.numeric_filter is not None and not plan.numeric_filter.is_empty():
        try:
            # Sprint 5 PR3: route to historical reader when intent classifier
            # detected "as of" / "previously" / "prior" cues.
            if getattr(plan, "historical", False):
                out.extend(search_numeric_historical(plan.numeric_filter, k=fts_k))
            else:
                out.extend(search_numeric(plan.numeric_filter, k=fts_k))
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_numeric failed: %s", exc)

    if plan.fts_query:
        try:
            out.extend(search_fts(plan.fts_query, k=fts_k))
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_fts failed: %s", exc)

    by_id: dict[str, ExactHit] = {}
    for h in out:
        cur = by_id.get(h.fact_id)
        if cur is None or h.score > cur.score:
            by_id[h.fact_id] = h
    return list(by_id.values())


def _run_semantic(query: str, *, namespace: Optional[str], k: int) -> List[SemanticHit]:
    """Run legacy semantic path. Time-decay is applied here so fusion
    sees recency-aware scores. Mirrors `chat_api._build_context._rag`.
    """
    # Lazy-import time decay to avoid a circular import on chat_api.
    from apps.shail.chat_api import _apply_time_decay
    try:
        raw = rag_search(query, k=k, namespace=namespace)
        return _apply_time_decay(raw, k=k)
    except Exception as exc:  # noqa: BLE001
        logger.warning("semantic path failed: %s", exc)
        return []


async def hybrid_search(
    query: str,
    *,
    namespace: Optional[str] = None,
    k: int = DEFAULT_K,
    overfetch_k: int = DEFAULT_OVERFETCH,
    use_global_memory: bool = False,      # Phase 1: SuperMemory global fallback
    retrieval_strategy: str = "local_only",  # local_only | global_only | hybrid
) -> List[SemanticHit]:
    """Drop-in replacement for `rag.search` + `_apply_time_decay`.

    Returns top-`k` `(content, score, metadata)` tuples in the same
    legacy shape so the downstream `_build_context` formatter is
    untouched.

    Phase 1 extension:
      When use_global_memory=True (or retrieval_strategy="hybrid"), and local
      results fall below settings.supermemory_fallback_threshold, SuperMemory
      global store is queried and results merged via fusion.fuse(global_hits=...).
    """
    if not query or not query.strip():
        return []

    plan = classify(query)
    settings = get_settings()

    # ── Phase 2: Cache check ──
    from shail.memory.cache import get_retrieval_cache
    cache = get_retrieval_cache()
    if settings.cache_enabled:
        cached = await cache.get(query, namespace, k)
        if cached is not None:
            logger.debug("hybrid_search: cache HIT for q=%r ns=%s", query[:40], namespace)
            try:
                from apps.shail import telemetry
                telemetry.incr(telemetry.RETRIEVAL_PATH, path="cache_hit")
            except Exception:
                pass
            return cached

    # Resolve effective strategy from both param and settings
    effective_strategy = retrieval_strategy
    if use_global_memory and effective_strategy == "local_only":
        effective_strategy = "hybrid"
    if settings.supermemory_use_global and effective_strategy == "local_only":
        effective_strategy = settings.retrieval_strategy

    # ── Local retrieval (skip for global_only) ──
    exact_hits: list = []
    semantic_hits: list = []

    if effective_strategy != "global_only":
        exact_task = asyncio.to_thread(_run_exact, plan, fts_k=overfetch_k)
        sem_task   = asyncio.to_thread(_run_semantic, query, namespace=namespace, k=overfetch_k)
        exact_hits, semantic_hits = await asyncio.gather(exact_task, sem_task)

        # Threshold gates (telemetry-aware).
        exact_dropped = sum(1 for h in exact_hits if h.score < DEFAULT_FTS_THRESHOLD)
        sem_dropped   = sum(1 for _, s, _ in semantic_hits if float(s or 0.0) < DEFAULT_SEMANTIC_THRESHOLD)
        if exact_dropped:
            telemetry.incr(telemetry.RETRIEVAL_THRESHOLD_DROPS, value=exact_dropped, surface="exact")
        if sem_dropped:
            telemetry.incr(telemetry.RETRIEVAL_THRESHOLD_DROPS, value=sem_dropped, surface="semantic")

    # ── Global fallback (Phase 1) ──
    global_hits = None
    local_hit_count = len(exact_hits) + len(semantic_hits)
    should_query_global = (
        effective_strategy in ("hybrid", "global_only")
        and (
            effective_strategy == "global_only"
            or local_hit_count < settings.supermemory_fallback_threshold
        )
    )

    if should_query_global:
        try:
            from shail.memory.supermemory_client import get_supermemory_client
            sm_client = get_supermemory_client()
            global_hits = await sm_client.query_global(
                query, k=k, namespace=namespace or "default"
            )
            if global_hits:
                telemetry.incr(telemetry.RETRIEVAL_PATH, path="global")
                logger.debug(
                    "hybrid_search: global fallback returned %d hits (local=%d < threshold=%d)",
                    len(global_hits), local_hit_count, settings.supermemory_fallback_threshold,
                )
        except Exception as exc:
            logger.warning("hybrid_search: global fallback failed: %s", exc)
            global_hits = None

    fused = fusion.fuse(
        exact=exact_hits,
        semantic=semantic_hits,
        weights=plan.weights,
        k=k,
        fts_threshold=DEFAULT_FTS_THRESHOLD,
        semantic_threshold=DEFAULT_SEMANTIC_THRESHOLD,
        global_hits=global_hits,           # Phase 1
    )

    # Telemetry: which path each hit came from.
    for h in fused:
        telemetry.incr(telemetry.RETRIEVAL_PATH, path=h.surface)
    if fused:
        telemetry.incr(telemetry.RETRIEVAL_FUSION_WINNER, path=fused[0].surface)

    if settings.shail_retrieval_debug:
        logger.info(
            "hybrid_search q=%r intent=%s exact=%d sem=%d global=%d fused=%d top=%s strategy=%s",
            query, plan.intent.value,
            len(exact_hits), len(semantic_hits),
            len(global_hits) if global_hits else 0,
            len(fused),
            (fused[0].surface, round(fused[0].score, 3)) if fused else None,
            effective_strategy,
        )

    result = [h.as_tuple() for h in fused]

    # ── Phase 2: Cache store ──
    if settings.cache_enabled and result:
        try:
            await cache.set(query, namespace, k, result)
        except Exception as exc:
            logger.debug("hybrid_search: cache write failed: %s", exc)

    return result
