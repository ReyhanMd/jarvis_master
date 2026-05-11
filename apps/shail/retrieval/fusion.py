"""Weighted rank fusion for hybrid retrieval (Sprint 3).

Pure function. No I/O. No SQLite.

Combines exact-index hits (already in [0,1] via BM25 normalization or 1.0
for numeric exact matches) with semantic hits from `rag_search` (which
returns store-side scores, in practice cosine similarity already
boosted by `_apply_time_decay`). Hits sharing the same `memory_id`
are merged — both surfaces contribute, raising the fused score.

The orchestrator hands `weights` from the `IntentPlan`. Fusion does NOT
re-classify intent. Recency is reflected in the semantic score itself
(time-decayed upstream); the `recency` weight slot is reserved for
future per-surface recency boosts but currently rolls into the semantic
component to keep behavior compositional.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

from apps.shail.exact_index import ExactHit

# GlobalHit — imported lazily to avoid circular import if supermemory_client
# is not yet initialised. Type guard below handles the None case.
try:
    from shail.memory.retrieval_strategy import GlobalHit as _GlobalHit
except ImportError:
    _GlobalHit = None  # type: ignore[assignment,misc]


# Type alias for the legacy semantic tuple shape (matches `rag.search` return).
SemanticHit = Tuple[str, float, dict]


@dataclass
class FusedHit:
    memory_id: str
    score: float
    surface: str                  # "exact" | "semantic" | "fused"
    content: str
    metadata: dict
    raw_scores: dict = field(default_factory=dict)

    def as_tuple(self) -> SemanticHit:
        """Return the legacy `(content, score, metadata)` shape so the
        existing `_build_context` formatter works unchanged."""
        return (self.content, self.score, self.metadata)


def _format_exact_hit(h: ExactHit) -> str:
    """Render a fact row as a human-readable line for context injection."""
    parts: list[str] = []
    if h.entity:
        parts.append(h.entity)
    if h.attribute:
        parts.append(h.attribute)
    head = " ".join(parts).strip() or "(fact)"
    period = f" ({h.period})" if h.period else ""
    value = h.value or ""
    if h.unit and h.unit not in (value or ""):
        value = f"{value} {h.unit}".strip()
    citation = f" [memory_id={h.memory_id}#{h.fact_id[:8]}]" if h.memory_id else ""
    return f"{head}{period}: {value}{citation}".strip()


def _exact_metadata(h: ExactHit) -> dict:
    """Synthesize a metadata dict that downstream `_build_context` can read.

    Keys mirror what semantic Chroma metadata supplies so `_build_context`
    rendering code stays unchanged: customId/id/memory_id, title, etc.
    """
    title_parts = [p for p in (h.entity, h.attribute) if p]
    title = " · ".join(title_parts) if title_parts else "(fact)"
    return {
        "id":          h.memory_id or h.fact_id,
        "memory_id":   h.memory_id or h.fact_id,
        "customId":    h.memory_id or h.fact_id,
        "title":       f"Fact: {title}",
        "surface":     h.surface,
        "fact_id":     h.fact_id,
        "entity":      h.entity,
        "attribute":   h.attribute,
        "value":       h.value,
        "value_num":   h.value_num,
        "unit":        h.unit,
        "period":      h.period,
        "source_span": h.source_span,
    }


def _stable_key_for_semantic(meta: dict, content: str) -> str:
    """Pick a key for dedup. Prefer customId / id / memory_id; fall back to a
    short hash of the content so unrelated rag rows do not collide."""
    for k in ("customId", "id", "memory_id"):
        v = meta.get(k)
        if v:
            return str(v)
    return "sem:" + hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:12]


def fuse(
    exact: Iterable[ExactHit],
    semantic: Iterable[SemanticHit],
    *,
    weights: dict,
    k: int = 6,
    fts_threshold: float = 0.0,
    semantic_threshold: float = 0.0,
    global_hits: Optional[Iterable] = None,   # List[GlobalHit] — Phase 1
    global_threshold: float = 0.0,
) -> List[FusedHit]:
    """Merge exact + semantic hits into a single ranked list.

    Both inputs are lazy-iterable; consumed once. `k` is the final cap.
    Hits below their respective thresholds are dropped before fusion.
    """
    w_exact = float(weights.get("exact", 0.5))
    w_sem   = float(weights.get("semantic", 0.5))

    out: dict[str, FusedHit] = {}

    # ── Exact contributions ──
    for h in exact:
        if h.score < fts_threshold:
            continue
        key = h.memory_id or h.fact_id
        contribution = w_exact * float(h.score)
        if key in out:
            f = out[key]
            f.score += contribution
            f.surface = "fused"
            f.raw_scores["exact"] = float(h.score)
        else:
            out[key] = FusedHit(
                memory_id=key,
                score=contribution,
                surface="exact",
                content=_format_exact_hit(h),
                metadata=_exact_metadata(h),
                raw_scores={"exact": float(h.score)},
            )

    # ── Semantic contributions ──
    for content, sem_score, meta in semantic:
        s = float(sem_score or 0.0)
        if s < semantic_threshold:
            continue
        key = _stable_key_for_semantic(meta or {}, content or "")
        contribution = w_sem * s
        if key in out:
            f = out[key]
            f.score += contribution
            f.surface = "fused"
            f.raw_scores["semantic"] = s
        else:
            md = dict(meta or {})
            md.setdefault("surface", "semantic")
            out[key] = FusedHit(
                memory_id=key,
                score=contribution,
                surface="semantic",
                content=content or "",
                metadata=md,
                raw_scores={"semantic": s},
            )

    # ── Global contributions (SuperMemory Phase 1) ──
    if global_hits is not None and _GlobalHit is not None:
        w_global = float(weights.get("global", w_sem))  # fallback to semantic weight
        for gh in global_hits:
            if not isinstance(gh, _GlobalHit):
                continue
            s = float(gh.score or 0.0)
            if s < global_threshold:
                continue
            key = gh.memory_id or ("global:" + hashlib.sha256((gh.content or "").encode()).hexdigest()[:12])
            contribution = w_global * s
            if key in out:
                f = out[key]
                f.score += contribution
                f.surface = "fused"
                f.raw_scores["global"] = s
            else:
                meta = dict(gh.metadata or {})
                meta.setdefault("surface", "global")
                out[key] = FusedHit(
                    memory_id=key,
                    score=contribution,
                    surface="global",
                    content=gh.content or "",
                    metadata=meta,
                    raw_scores={"global": s},
                )

    ranked = sorted(out.values(), key=lambda f: f.score, reverse=True)
    return ranked[: max(0, int(k))]
