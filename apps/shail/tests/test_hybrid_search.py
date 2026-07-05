"""Sprint 3 PR2: hybrid_search orchestrator.

Mocks the semantic path (`rag.search`) and `_apply_time_decay` so tests
do not need Ollama or Chroma. The exact path runs against the real
seeded SQLite memory_facts (via the `isolated_db` fixture).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from apps.shail import exact_index, telemetry
from shail.memory import hybrid as hybrid_mod


def _seed_facts() -> None:
    exact_index.init()
    exact_index.upsert_facts("mem-tesla", [
        {"entity": "Tesla", "attribute": "revenue", "value": "$81B",
         "value_num": 81e9, "unit": "USD", "period": "2023"},
        {"entity": "Tesla", "attribute": "growth", "value": "62%",
         "value_num": 62, "unit": "%", "period": "2023"},
    ])
    exact_index.upsert_facts("mem-toyota", [
        {"entity": "Toyota", "attribute": "revenue", "value": "$280B",
         "value_num": 280e9, "unit": "USD", "period": "2023"},
    ])


def _mock_rag_search(monkeypatch, results):
    """Make rag_search return a fixed list. Bypass time-decay by identity."""
    monkeypatch.setattr(hybrid_mod, "rag_search", lambda q, **kw: results)
    # Patch the local `_apply_time_decay` import inside _run_semantic.
    import apps.shail.chat_api as chat_api
    monkeypatch.setattr(chat_api, "_apply_time_decay",
                        lambda hits, k=12: hits[:k])


# ── Empty / edge cases ─────────────────────────────────────────────────────


def test_empty_query_returns_empty(isolated_db: Path, monkeypatch) -> None:
    _seed_facts()
    _mock_rag_search(monkeypatch, [])
    out = asyncio.run(hybrid_mod.hybrid_search(""))
    assert out == []


def test_no_results_anywhere(isolated_db: Path, monkeypatch) -> None:
    _seed_facts()
    _mock_rag_search(monkeypatch, [])
    out = asyncio.run(hybrid_mod.hybrid_search("ZZZ_no_match_QQQ"))
    assert out == []


# ── Exact-only success path ────────────────────────────────────────────────


def test_exact_query_returns_fact_row(isolated_db: Path, monkeypatch) -> None:
    _seed_facts()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled")
    _mock_rag_search(monkeypatch, [])
    out = asyncio.run(hybrid_mod.hybrid_search("Tesla revenue 2023"))
    assert out, "expected at least one hit"
    content, score, meta = out[0]
    # Must look like a hit from the exact index, not legacy.
    assert "Tesla" in content and "revenue" in content
    assert meta["surface"] in ("fts", "numeric", "exact", "fused")
    assert isinstance(score, float)


# ── Semantic-only path ─────────────────────────────────────────────────────


def test_semantic_only_returns_legacy_shape(isolated_db: Path, monkeypatch) -> None:
    _seed_facts()
    _mock_rag_search(monkeypatch, [
        ("Discussion of onboarding philosophy.", 0.85,
         {"id": "mem-onb", "title": "Onboarding"}),
    ])
    out = asyncio.run(
        hybrid_mod.hybrid_search("summarize what we discussed about onboarding")
    )
    assert out, "expected semantic hit"
    content, score, meta = out[0]
    assert "onboarding" in content.lower()
    assert meta["title"] == "Onboarding"


# ── Fusion: exact + semantic on same memory ────────────────────────────────


def test_fusion_accumulates_when_same_memory_id(isolated_db: Path, monkeypatch) -> None:
    _seed_facts()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled")
    # Semantic hit with same memory_id as the exact fact row.
    _mock_rag_search(monkeypatch, [
        ("Tesla revenue narrative", 0.6, {"id": "mem-tesla", "title": "Tesla"}),
    ])
    out = asyncio.run(hybrid_mod.hybrid_search("Tesla revenue 2023"))
    assert out
    # Top hit should be the fused tesla memory.
    _, _, top_meta = out[0]
    assert top_meta["id"] == "mem-tesla"
    assert top_meta.get("surface") in ("fts", "numeric", "exact", "fused", "semantic")


# ── Always runs both surfaces (never branch-skips) ─────────────────────────


def test_semantic_always_runs_even_for_exact_intent(
    isolated_db: Path, monkeypatch
) -> None:
    """Plan rule: never branch-skip a surface based on intent."""
    _seed_facts()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled")
    called = []
    def _fake_rag(q, **kw):
        called.append(q)
        return []
    monkeypatch.setattr(hybrid_mod, "rag_search", _fake_rag)
    import apps.shail.chat_api as chat_api
    monkeypatch.setattr(chat_api, "_apply_time_decay", lambda hits, k=12: hits[:k])

    asyncio.run(hybrid_mod.hybrid_search("revenue > $50B"))
    assert called, "semantic path must run even on EXACT_VALUE intent"


# ── Telemetry ──────────────────────────────────────────────────────────────


def test_telemetry_path_counter_incremented(isolated_db: Path, monkeypatch) -> None:
    _seed_facts()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled")
    _mock_rag_search(monkeypatch, [])
    telemetry.reset()
    out = asyncio.run(hybrid_mod.hybrid_search("Tesla revenue 2023"))
    counters = telemetry.snapshot()["counters"]
    if out:
        # At least one path counter should have ticked.
        path_keys = [k for k in counters if k.startswith(telemetry.RETRIEVAL_PATH)]
        assert path_keys


# ── Result shape contract ──────────────────────────────────────────────────


def test_result_is_list_of_tuples(isolated_db: Path, monkeypatch) -> None:
    _seed_facts()
    _mock_rag_search(monkeypatch, [
        ("body", 0.5, {"id": "x", "title": "X"}),
    ])
    out = asyncio.run(hybrid_mod.hybrid_search("anything"))
    assert isinstance(out, list)
    for item in out:
        assert isinstance(item, tuple)
        assert len(item) == 3
        c, s, m = item
        assert isinstance(c, str)
        assert isinstance(s, float)
        assert isinstance(m, dict)


def test_top_k_respected(isolated_db: Path, monkeypatch) -> None:
    _seed_facts()
    sem = [(f"body{i}", 0.5 - i * 0.01, {"id": f"x{i}"}) for i in range(15)]
    _mock_rag_search(monkeypatch, sem)
    out = asyncio.run(hybrid_mod.hybrid_search("anything", k=3))
    assert len(out) <= 3


# ── Error resilience ───────────────────────────────────────────────────────


def test_exact_failure_does_not_abort_semantic(isolated_db: Path, monkeypatch) -> None:
    _seed_facts()
    _mock_rag_search(monkeypatch, [
        ("ok", 0.9, {"id": "m"}),
    ])
    def boom(*a, **kw):
        raise RuntimeError("synthetic")
    monkeypatch.setattr(hybrid_mod, "search_fts", boom)
    monkeypatch.setattr(hybrid_mod, "search_numeric", boom)
    out = asyncio.run(hybrid_mod.hybrid_search("Tesla revenue"))
    # Semantic still returns the hit.
    assert out
    assert out[0][2]["id"] == "m"
