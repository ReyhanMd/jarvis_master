"""Sprint 3 PR1: weighted rank fusion."""
from __future__ import annotations

from apps.shail.exact_index import ExactHit
from apps.shail.retrieval.fusion import FusedHit, fuse


_W_EXACT = {"exact": 0.7, "semantic": 0.2, "recency": 0.1}
_W_SEM   = {"exact": 0.2, "semantic": 0.7, "recency": 0.1}


def make_exact(memory_id: str = "m1", score: float = 0.9, *, fact_id: str = None,
               entity: str = "Tesla", attribute: str = "revenue",
               value: str = "$81B", period: str = "2023") -> ExactHit:
    return ExactHit(
        fact_id=fact_id or f"f-{memory_id}-{attribute}",
        memory_id=memory_id,
        entity=entity, attribute=attribute, value=value,
        value_num=None, unit="USD", period=period,
        source_span="span", confidence=0.9,
        score=score, raw_score=score, surface="fts",
    )


# ── basic merging ──────────────────────────────────────────────────────────


def test_fuse_empty_inputs_returns_empty() -> None:
    assert fuse([], [], weights=_W_EXACT) == []


def test_only_exact() -> None:
    out = fuse([make_exact("m1", 0.9)], [], weights=_W_EXACT, mode="weighted")
    assert len(out) == 1
    assert out[0].surface == "exact"
    assert abs(out[0].score - 0.7 * 0.9) < 1e-9


def test_only_semantic() -> None:
    sem = [("body text", 0.8, {"id": "m2", "title": "T"})]
    out = fuse([], sem, weights=_W_SEM, mode="weighted")
    assert len(out) == 1
    assert out[0].surface == "semantic"
    assert abs(out[0].score - 0.7 * 0.8) < 1e-9


def test_same_memory_id_fuses() -> None:
    """Both surfaces hitting same memory_id → score accumulates, surface=fused."""
    sem = [("body about tesla", 0.8, {"id": "m1"})]
    exact = [make_exact("m1", 0.9)]
    out = fuse(exact, sem, weights=_W_EXACT, mode="weighted")
    assert len(out) == 1
    f = out[0]
    assert f.surface == "fused"
    assert "exact" in f.raw_scores and "semantic" in f.raw_scores
    expected = 0.7 * 0.9 + 0.2 * 0.8
    assert abs(f.score - expected) < 1e-9


def test_different_memory_ids_kept_separate() -> None:
    sem = [("body about toyota", 0.8, {"id": "m2"})]
    exact = [make_exact("m1", 0.9)]
    out = fuse(exact, sem, weights=_W_EXACT)
    keys = {f.memory_id for f in out}
    assert keys == {"m1", "m2"}


# ── ranking ────────────────────────────────────────────────────────────────


def test_ranking_descending() -> None:
    exact = [make_exact("m1", 0.9), make_exact("m2", 0.5, fact_id="f2")]
    out = fuse(exact, [], weights=_W_EXACT)
    assert out[0].score > out[1].score
    assert out[0].memory_id == "m1"


def test_top_k_caps_results() -> None:
    exact = [make_exact(f"m{i}", 0.9 - i * 0.1, fact_id=f"f{i}") for i in range(5)]
    out = fuse(exact, [], weights=_W_EXACT, k=3)
    assert len(out) == 3


# ── thresholds ─────────────────────────────────────────────────────────────


def test_fts_threshold_drops_low_exact() -> None:
    exact = [make_exact("m1", 0.9), make_exact("m2", 0.1, fact_id="f2")]
    out = fuse(exact, [], weights=_W_EXACT, fts_threshold=0.5)
    assert {f.memory_id for f in out} == {"m1"}


def test_semantic_threshold_drops_low_semantic() -> None:
    sem = [
        ("a", 0.9, {"id": "m1"}),
        ("b", 0.2, {"id": "m2"}),
    ]
    out = fuse([], sem, weights=_W_SEM, semantic_threshold=0.5)
    assert {f.memory_id for f in out} == {"m1"}


# ── content + metadata shape ───────────────────────────────────────────────


def test_exact_content_includes_entity_value_period() -> None:
    out = fuse([make_exact("m1", 0.9)], [], weights=_W_EXACT)
    text = out[0].content
    assert "Tesla" in text
    assert "revenue" in text
    assert "2023" in text
    assert "$81B" in text


def test_exact_metadata_carries_legacy_keys() -> None:
    out = fuse([make_exact("m1", 0.9)], [], weights=_W_EXACT)
    meta = out[0].metadata
    # `_build_context` reads these — must be present.
    assert meta["customId"] == "m1"
    assert meta["id"] == "m1"
    assert meta["memory_id"] == "m1"
    assert meta["title"].startswith("Fact: ")
    assert meta["surface"] in ("fts", "exact", "fused")


def test_semantic_metadata_passthrough() -> None:
    sem = [("body", 0.8, {"id": "m2", "title": "X", "captured_ts": "2024-01-01"})]
    out = fuse([], sem, weights=_W_SEM)
    meta = out[0].metadata
    assert meta["title"] == "X"
    assert meta["captured_ts"] == "2024-01-01"


def test_as_tuple_matches_legacy_shape() -> None:
    out = fuse([make_exact("m1", 0.9)], [], weights=_W_EXACT)
    t = out[0].as_tuple()
    assert isinstance(t, tuple)
    assert len(t) == 3
    content, score, meta = t
    assert isinstance(content, str)
    assert isinstance(score, float)
    assert isinstance(meta, dict)
