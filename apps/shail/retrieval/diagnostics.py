"""Local-file retrieval diagnostics.

Answers: "why didn't SHAIL find my PDF?" by surfacing every reason a local-
file hit can fail along the chain:

    path_index FTS match  →  file readable on disk  →  extractor returns text
                            →  best_snippet is non-empty
                            →  hit reaches the LLM prompt

Each retrieval pass records counts under a process-local registry. The UI
polls /path-index/diagnostics to render a health card and flag missing
optional dependencies (pypdf, python-docx, openpyxl, etc.).

This is observability, not control flow. No retrieval decision depends on
the registry — failures are still silent at runtime, just no longer silent
on the dashboard.
"""
from __future__ import annotations

import importlib
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# Module-level — one registry per process.
_LOCK = threading.Lock()
_RETRIEVAL_STATS: Counter = Counter()
_LAST_QUERY_TRACE: List[Dict] = []
_TRACE_LIMIT = 32


def record(event: str, *, value: int = 1) -> None:
    """Record a counter event. Cheap; safe to call from hot paths."""
    with _LOCK:
        _RETRIEVAL_STATS[event] += value


def push_trace(entry: Dict) -> None:
    """Push a per-query trace row. Ring-buffered at _TRACE_LIMIT."""
    with _LOCK:
        _LAST_QUERY_TRACE.append(entry)
        if len(_LAST_QUERY_TRACE) > _TRACE_LIMIT:
            del _LAST_QUERY_TRACE[: len(_LAST_QUERY_TRACE) - _TRACE_LIMIT]


def stats() -> Dict[str, int]:
    with _LOCK:
        return dict(_RETRIEVAL_STATS)


def recent_traces() -> List[Dict]:
    with _LOCK:
        return list(_LAST_QUERY_TRACE)


def reset() -> None:
    with _LOCK:
        _RETRIEVAL_STATS.clear()
        _LAST_QUERY_TRACE.clear()


# ── Extractor dependency probe ──────────────────────────────────────────────


_OPTIONAL_DEPS = {
    ".pdf":  "pypdf",
    ".docx": "docx",       # python-docx imports as `docx`
    ".doc":  "docx",
    ".xlsx": "openpyxl",
    ".xls":  "openpyxl",
    ".pptx": "pptx",
    ".pages": None,        # no python lib — Pages requires external tooling
}


@dataclass
class DependencyStatus:
    extension: str
    module_name: Optional[str]
    available: bool
    error: Optional[str] = None


def probe_extractor_deps() -> List[DependencyStatus]:
    """Check every optional extractor dep at runtime. Used by the diagnostics
    endpoint so the user sees "pypdf not installed" instead of mysterious
    silence."""
    results: list[DependencyStatus] = []
    for ext, mod in _OPTIONAL_DEPS.items():
        if mod is None:
            results.append(DependencyStatus(
                extension=ext, module_name=None, available=False,
                error="no supported extractor (Pages files cannot be indexed)",
            ))
            continue
        try:
            importlib.import_module(mod)
            results.append(DependencyStatus(extension=ext, module_name=mod, available=True))
        except Exception as exc:  # noqa: BLE001
            results.append(DependencyStatus(
                extension=ext, module_name=mod, available=False, error=str(exc),
            ))
    return results


def health_summary() -> Dict:
    """One-shot dashboard payload."""
    deps = probe_extractor_deps()
    return {
        "extractor_deps": [
            {"ext": d.extension, "module": d.module_name,
             "available": d.available, "error": d.error}
            for d in deps
        ],
        "retrieval_stats": stats(),
        "extractor_failures": _extractor_failures_snapshot(),
        "recent_traces": recent_traces(),
    }


def _extractor_failures_snapshot() -> Dict[str, int]:
    """Aggregate extractor failures recorded by path_index._extract_snippet."""
    try:
        from shail.memory.path_index import extractor_failure_summary
        return extractor_failure_summary()
    except Exception:
        return {}
