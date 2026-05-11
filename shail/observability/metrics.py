"""Prometheus metrics for SHAIL (Phase 6).

All metrics are NOOP when prometheus_client is not installed or
metrics_enabled=False.  Never raises — safe to call everywhere.

Usage:
    from shail.observability.metrics import M
    M.rag_query_seconds.observe(elapsed)
    M.cache_hits.labels(namespace="code", backend="redis").inc()
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# ── Lazy-init guard ────────────────────────────────────────────────────── #
_initialized = False
_prom_available = False


def _try_import():
    global _prom_available
    try:
        import prometheus_client  # noqa: F401
        _prom_available = True
    except ImportError:
        _prom_available = False
    return _prom_available


class _Noop:
    """Fallback stub for all prometheus_client metric types."""
    def labels(self, **_): return self
    def inc(self, *_, **__): pass
    def dec(self, *_, **__): pass
    def set(self, *_, **__): pass
    def observe(self, *_, **__): pass
    def time(self): return _NoopCtx()

class _NoopCtx:
    def __enter__(self): return self
    def __exit__(self, *_): pass


class _Metrics:
    """Singleton holder for all SHAIL Prometheus metrics."""

    def __init__(self) -> None:
        self._ready = False
        # Pre-assign noops; real metrics populated in _init()
        self.rag_query_seconds    = _Noop()
        self.embedding_seconds    = _Noop()
        self.cache_hits           = _Noop()
        self.cache_misses         = _Noop()
        self.supermemory_ingest   = _Noop()
        self.hybrid_fallbacks     = _Noop()
        self.rag_results          = _Noop()
        self.vector_store_docs    = _Noop()
        self.cache_size_bytes     = _Noop()
        self.task_duration        = _Noop()
        self.task_total           = _Noop()
        self.ingest_total         = _Noop()

    def init(self) -> None:
        if self._ready:
            return
        from apps.shail.settings import get_settings
        if not get_settings().metrics_enabled:
            self._ready = True
            return
        if not _try_import():
            logger.info("prometheus_client not installed — metrics disabled")
            self._ready = True
            return

        try:
            import prometheus_client as prom

            # ── Histograms ───────────────────────────────────────────── #
            self.rag_query_seconds = prom.Histogram(
                "shail_rag_query_seconds",
                "Time spent on RAG retrieval (hybrid_search)",
                buckets=[.05, .1, .25, .5, 1, 2.5, 5],
            )
            self.embedding_seconds = prom.Histogram(
                "shail_embedding_seconds",
                "Time spent generating embeddings",
                buckets=[.01, .05, .1, .25, .5, 1],
            )
            self.task_duration = prom.Histogram(
                "shail_task_duration_seconds",
                "End-to-end task execution time",
                labelnames=["agent"],
                buckets=[.1, .5, 1, 2.5, 5, 10, 30, 60],
            )

            # ── Counters ─────────────────────────────────────────────── #
            self.cache_hits = prom.Counter(
                "shail_cache_hits_total",
                "Cache hits",
                labelnames=["namespace", "backend"],
            )
            self.cache_misses = prom.Counter(
                "shail_cache_misses_total",
                "Cache misses",
                labelnames=["namespace"],
            )
            self.supermemory_ingest = prom.Counter(
                "supermemory_ingest_total",
                "SuperMemory ingest attempts",
                labelnames=["status", "agent"],
            )
            self.hybrid_fallbacks = prom.Counter(
                "hybrid_retrieval_fallbacks_total",
                "Hybrid retrieval global fallback triggers",
                labelnames=["reason"],
            )
            self.rag_results = prom.Counter(
                "shail_rag_results_total",
                "RAG results by surface",
                labelnames=["surface"],
            )
            self.task_total = prom.Counter(
                "shail_task_total",
                "Tasks routed",
                labelnames=["agent", "status"],
            )
            self.ingest_total = prom.Counter(
                "shail_ingest_total",
                "Auto-ingest attempts",
                labelnames=["status"],
            )

            # ── Gauges ───────────────────────────────────────────────── #
            self.vector_store_docs = prom.Gauge(
                "shail_vector_store_docs",
                "Documents in vector store",
                labelnames=["namespace"],
            )
            self.cache_size_bytes = prom.Gauge(
                "shail_cache_size_bytes",
                "Cache storage size in bytes",
                labelnames=["backend"],
            )

            self._ready = True
            logger.info("SHAIL Prometheus metrics initialized")
        except Exception as exc:
            logger.warning("Metrics init failed: %s — running with noops", exc)
            self._ready = True

    @contextmanager
    def time_rag(self):
        """Context manager: time a RAG retrieval block."""
        if not isinstance(self.rag_query_seconds, _Noop):
            with self.rag_query_seconds.time():
                yield
        else:
            start = time.perf_counter()
            try:
                yield
            finally:
                pass  # noop — don't bother

    @contextmanager
    def time_embedding(self):
        if not isinstance(self.embedding_seconds, _Noop):
            with self.embedding_seconds.time():
                yield
        else:
            yield


# Module-level singleton
M = _Metrics()


def init_metrics() -> None:
    """Call once at app startup (main.py lifespan)."""
    M.init()
