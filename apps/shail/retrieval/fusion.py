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


RRF_K = 60  # Standard Reciprocal Rank Fusion constant (Cormack et al. 2009)


def fuse(
    exact: Iterable[ExactHit],
    semantic: Iterable[SemanticHit],
    *,
    weights: dict,
    k: int = 6,
    fts_threshold: float = 0.0,
    semantic_threshold: float = 0.0,
    global_hits: Optional[Iterable] = None,
    global_threshold: float = 0.0,
    mode: str = "rrf",   # "rrf" (default, Sprint 2) | "weighted" (legacy)
) -> List[FusedHit]:
    """Merge exact + semantic + (optional) global hits into a single ranked list.

    Two ranking modes (selected via `mode`):

      "rrf"      — Reciprocal Rank Fusion. Each surface produces an internal
                   rank; an item appearing at rank r in surface S contributes
                   `w_S / (RRF_K + r)`. Items in multiple surfaces sum
                   contributions. Scale-independent and deterministic.

      "weighted" — Legacy mode. Sums weighted RAW scores across surfaces.
                   Kept for backward compatibility. Vulnerable to score-scale
                   mismatch between surfaces.

    Default: RRF. Tests assert deterministic ranking.
    """
    # Coerce iterables to lists — we need ranks
    exact_list = [h for h in exact if h.score >= fts_threshold]
    sem_list   = [(c, s, m) for c, s, m in semantic if float(s or 0.0) >= semantic_threshold]
    global_list: list = []
    if global_hits is not None and _GlobalHit is not None:
        for gh in global_hits:
            if isinstance(gh, _GlobalHit) and float(gh.score or 0.0) >= global_threshold:
                global_list.append(gh)

    # Sort each surface by raw score (desc) to determine intra-surface ranks
    exact_list.sort(key=lambda h: h.score, reverse=True)
    sem_list.sort(key=lambda t: float(t[1] or 0.0), reverse=True)
    global_list.sort(key=lambda gh: float(gh.score or 0.0), reverse=True)

    w_exact  = float(weights.get("exact",    0.5))
    w_sem    = float(weights.get("semantic", 0.5))
    w_global = float(weights.get("global",   w_sem))

    out: dict[str, FusedHit] = {}

    def _contrib_rrf(rank: int, weight: float) -> float:
        return weight / (RRF_K + rank)

    def _contrib_weighted(raw: float, weight: float) -> float:
        return weight * raw

    contrib = _contrib_rrf if mode == "rrf" else _contrib_weighted

    # ── Exact ────────────────────────────────────────────────────────── #
    for rank_idx, h in enumerate(exact_list, start=1):
        key = h.memory_id or h.fact_id
        c = contrib(rank_idx if mode == "rrf" else float(h.score), w_exact)
        if key in out:
            existing = out[key]
            existing.score += c
            existing.surface = "fused"
            existing.raw_scores["exact"] = float(h.score)
            existing.raw_scores["exact_rank"] = rank_idx
        else:
            out[key] = FusedHit(
                memory_id=key,
                score=c,
                surface="exact",
                content=_format_exact_hit(h),
                metadata=_exact_metadata(h),
                raw_scores={"exact": float(h.score), "exact_rank": rank_idx},
            )

    # ── Semantic ─────────────────────────────────────────────────────── #
    for rank_idx, (content, s, meta) in enumerate(sem_list, start=1):
        raw = float(s or 0.0)
        key = _stable_key_for_semantic(meta or {}, content or "")
        c = contrib(rank_idx if mode == "rrf" else raw, w_sem)
        if key in out:
            existing = out[key]
            existing.score += c
            existing.surface = "fused"
            existing.raw_scores["semantic"] = raw
            existing.raw_scores["semantic_rank"] = rank_idx
        else:
            md = dict(meta or {})
            md.setdefault("surface", "semantic")
            out[key] = FusedHit(
                memory_id=key,
                score=c,
                surface="semantic",
                content=content or "",
                metadata=md,
                raw_scores={"semantic": raw, "semantic_rank": rank_idx},
            )

    # ── Global (SuperMemory) ─────────────────────────────────────────── #
    for rank_idx, gh in enumerate(global_list, start=1):
        raw = float(gh.score or 0.0)
        key = gh.memory_id or (
            "global:" + hashlib.sha256((gh.content or "").encode()).hexdigest()[:12]
        )
        c = contrib(rank_idx if mode == "rrf" else raw, w_global)
        if key in out:
            existing = out[key]
            existing.score += c
            existing.surface = "fused"
            existing.raw_scores["global"] = raw
            existing.raw_scores["global_rank"] = rank_idx
        else:
            meta = dict(gh.metadata or {})
            meta.setdefault("surface", "global")
            out[key] = FusedHit(
                memory_id=key,
                score=c,
                surface="global",
                content=gh.content or "",
                metadata=meta,
                raw_scores={"global": raw, "global_rank": rank_idx},
            )

    # Final ordering — score desc, then memory_id for determinism
    ranked = sorted(out.values(), key=lambda f: (-f.score, f.memory_id))
    return ranked[: max(0, int(k))]
