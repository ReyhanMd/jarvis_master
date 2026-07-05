"""Lightweight in-process counters for retrieval-evolution rollout.

Local-first: no external sinks. Thread-safe via Lock. Read with snapshot()
for tests / debugging endpoints. Add sinks (Prometheus, OpenTelemetry) later
without touching call sites.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict


_lock = threading.Lock()
_counters: Dict[str, float] = defaultdict(float)
_histograms: Dict[str, list] = defaultdict(list)


def incr(name: str, value: float = 1.0, **labels) -> None:
    key = _key(name, labels)
    with _lock:
        _counters[key] += value


def observe(name: str, value: float, **labels) -> None:
    key = _key(name, labels)
    with _lock:
        _histograms[key].append(value)


def snapshot() -> Dict[str, object]:
    with _lock:
        return {
            "counters": dict(_counters),
            "histograms": {k: list(v) for k, v in _histograms.items()},
        }


def reset() -> None:
    with _lock:
        _counters.clear()
        _histograms.clear()


def _key(name: str, labels: Dict[str, object]) -> str:
    if not labels:
        return name
    parts = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return f"{name}{{{parts}}}"


# Canonical counter names (string constants prevent typos at call sites).
RETRIEVAL_PATH = "retrieval.path"                       # labels: path={exact,semantic,fused}
RETRIEVAL_THRESHOLD_DROPS = "retrieval.threshold_drops"  # labels: surface={exact,semantic}
RETRIEVAL_FUSION_WINNER = "retrieval.fusion_winner_path" # labels: path
BLUEPRINT_FACTS_EXTRACTED = "blueprint.facts_extracted_count"
GEMMA_HALLUCINATED_NUMBER = "gemma.hallucinated_number_emitted"
INGEST_CHUNKS_PER_CAPTURE = "ingest.chunks_per_capture"  # histogram
BLUEPRINT_VERSIONS_PER_FACT = "blueprint.versions_per_fact"  # histogram
RETRIEVAL_LATENCY_MS = "retrieval.latency_ms"            # histogram, labels: path
CAPTURE_INDEX_FAIL = "capture.index_fail"               # counter: live-turn indexing failure
