"""Telemetry → Prometheus bridge (Sprint 2).

Wires the existing `apps.shail.telemetry.incr/observe` call sites into
Prometheus metrics WITHOUT touching the call sites themselves.

Strategy:
  1. At startup, monkey-patch `telemetry.incr` and `telemetry.observe` to
     fan-out into Prometheus AFTER updating the in-memory counters.
  2. Map known counter/histogram names to Prometheus instruments declared
     in `shail.observability.metrics.M`.
  3. Unknown metric names pass through silently — never error.

The bridge is idempotent and safe to call multiple times; subsequent calls
are no-ops.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

_INSTALLED = False


def _label_filter(labels: Dict[str, Any], allowed: set) -> Dict[str, str]:
    """Coerce label values to str; drop unknown keys to prevent cardinality explosion."""
    return {k: str(v)[:64] for k, v in labels.items() if k in allowed}


def install_bridge() -> None:
    """Monkey-patch telemetry.incr/observe to also emit Prometheus.

    Safe to call multiple times. Never raises.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    try:
        from apps.shail import telemetry as _t
        from shail.observability.metrics import M
        # Ensure Prometheus side is initialised (no-op if disabled)
        try:
            M.init()
        except Exception:
            pass

        orig_incr = _t.incr
        orig_observe = _t.observe

        # ── Name → Prometheus instrument map ──────────────────────────── #
        # Counters
        counter_map = {
            _t.RETRIEVAL_PATH:               (M.rag_results,         {"path"}),
            _t.RETRIEVAL_FUSION_WINNER:      (M.rag_results,         {"path"}),
            _t.RETRIEVAL_THRESHOLD_DROPS:    (M.hybrid_fallbacks,    {"surface"}),
        }
        # Histograms
        hist_map = {
            _t.RETRIEVAL_LATENCY_MS:         (M.rag_query_seconds,   set()),
        }
        # Additional Sprint-2 names — Prometheus counters for new flows
        sprint2_counters = {
            "memory.dedup_rejections":       (M.ingest_total,        {"status"}),
            "memory.ingest_rejected":        (M.ingest_total,        {"status"}),
            "memory.ingest_succeeded":       (M.ingest_total,        {"status"}),
            "memory.dead_letter":            (M.ingest_total,        {"status"}),
            "memory.usefulness_applied":     (M.ingest_total,        {"status"}),
            "memory.shared_context_write":   (M.cache_hits,          {"namespace", "backend"}),
            "memory.shared_context_read":    (M.cache_hits,          {"namespace", "backend"}),
        }
        counter_map.update(sprint2_counters)

        sprint2_hists = {
            "memory.fusion_seconds":         (M.rag_query_seconds,   set()),
            "memory.usefulness_score":       (M.embedding_seconds,   set()),  # reused histogram
        }
        hist_map.update(sprint2_hists)

        def patched_incr(name: str, value: float = 1.0, **labels):
            orig_incr(name, value, **labels)
            try:
                target = counter_map.get(name)
                if target is None:
                    return
                metric, allowed_labels = target
                clean = _label_filter(labels, allowed_labels)
                if clean:
                    metric.labels(**clean).inc(value)
                else:
                    metric.inc(value)
            except Exception as exc:
                logger.debug("bridge incr failed for %s: %s", name, exc)

        def patched_observe(name: str, value: float, **labels):
            orig_observe(name, value, **labels)
            try:
                target = hist_map.get(name)
                if target is None:
                    return
                metric, allowed_labels = target
                clean = _label_filter(labels, allowed_labels)
                if clean:
                    metric.labels(**clean).observe(value)
                else:
                    metric.observe(value)
            except Exception as exc:
                logger.debug("bridge observe failed for %s: %s", name, exc)

        _t.incr = patched_incr
        _t.observe = patched_observe
        _INSTALLED = True
        logger.info("Telemetry→Prometheus bridge installed")
    except Exception as exc:
        logger.warning("Telemetry bridge install failed: %s", exc)


# Convenience: explicit counter names used by Sprint-2 modules
INGEST_REJECTED      = "memory.ingest_rejected"       # labels: status=quality|dedup|empty
INGEST_SUCCEEDED     = "memory.ingest_succeeded"      # labels: status=local|global
DEDUP_REJECTIONS     = "memory.dedup_rejections"      # labels: status=semantic|hash
DEAD_LETTER          = "memory.dead_letter"           # labels: status=created|recovered|abandoned
USEFULNESS_APPLIED   = "memory.usefulness_applied"    # labels: status=positive|negative|neutral
SHARED_CTX_WRITE     = "memory.shared_context_write"  # labels: namespace=, backend=
SHARED_CTX_READ      = "memory.shared_context_read"   # labels: namespace=, backend=
FUSION_SECONDS       = "memory.fusion_seconds"        # histogram
USEFULNESS_SCORE     = "memory.usefulness_score"      # histogram
