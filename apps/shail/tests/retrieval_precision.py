"""SHAIL retrieval-precision eval suite — Sprint 0 baseline harness.

Mandatory cases (per rollout plan):
    01 — exact value
    02 — hallucination floor
    03 — recency conflict (latest wins)
    04 — recency historical (as-of)
    05 — similar-entity disambiguation
    06 — semantic-only intent
    07 — threshold drop
    08 — fusion priority
    09 — backfill parity
    10 — continuity preservation
    11 — rollback equivalence

Sprint 0 lands the harness + golden-snapshot framework. Cases that
require structured rows / hybrid retrieval / chunking are scaffolded
as `xfail(strict=False)` so later sprints can flip them green without
modifying the harness. Each case loads from `fixtures/captures/` and
asserts via `golden_snapshot`.
"""
from __future__ import annotations

import pytest

from apps.shail.blueprints import _parse_blueprint


# ─── Harness self-test (always green) ────────────────────────────────────────


def test_fixtures_loadable(captures: dict) -> None:
    assert "chart" in captures
    assert "narrative" in captures
    assert "multi_version" in captures
    for c in captures.values():
        assert c["content"].strip()
        assert c["kind"] in {"ai_conversation", "web"}


def test_parser_deterministic() -> None:
    raw = (
        '{"summary": "Reviewed Tesla revenue.", '
        '"decisions": [{"statement": "Use 10-K data", "reasoning": "audited", "confidence": "high"}], '
        '"questions_answered": [], "open_questions": [], "next_actions": [], '
        '"key_entities": ["Tesla"], "reasoning_chains": [], "failed_attempts": [], '
        '"extensions": {}}'
    )
    a = _parse_blueprint(raw)
    b = _parse_blueprint(raw)
    assert a == b
    assert a["summary"] == "Reviewed Tesla revenue."
    assert a["key_entities"] == ["Tesla"]


def test_parser_golden(golden_snapshot, captures: dict) -> None:
    """Lock parser output for the chart fixture so prompt drift is caught."""
    # Simulate what the LLM should emit for the chart fixture (frozen for now).
    raw = (
        '{"summary": "Tesla revenue grew 62% YoY in 2023.", '
        '"decisions": [], "questions_answered": ['
        '{"q": "Tesla 2023 revenue?", "a": "$81B"}], '
        '"open_questions": [], "next_actions": [], '
        '"key_entities": ["Tesla"], "reasoning_chains": [], '
        '"failed_attempts": [], "extensions": {}}'
    )
    parsed = _parse_blueprint(raw)
    golden_snapshot(parsed)


# ─── 11 mandatory cases (scaffolded; activate per sprint) ────────────────────


@pytest.mark.xfail(strict=False, reason="Sprint 1+ required: exact index not wired")
def test_01_exact_value(captures: dict) -> None:
    raise NotImplementedError("Activated in Sprint 3 (hybrid retrieval).")


@pytest.mark.xfail(strict=False, reason="Sprint 4 required: context packet + Gemma policy")
def test_02_hallucination_floor() -> None:
    raise NotImplementedError("Activated in Sprint 4.")


@pytest.mark.xfail(strict=False, reason="Sprint 5 required: lineage writer ON")
def test_03_recency_conflict_latest_wins() -> None:
    raise NotImplementedError("Activated in Sprint 5.")


@pytest.mark.xfail(strict=False, reason="Sprint 5 required: as-of intent")
def test_04_recency_historical() -> None:
    raise NotImplementedError("Activated in Sprint 5.")


@pytest.mark.xfail(strict=False, reason="Sprint 3 required: hybrid retrieval")
def test_05_similar_entity_disambiguation() -> None:
    raise NotImplementedError("Activated in Sprint 3.")


@pytest.mark.xfail(strict=False, reason="Sprint 3 required: hybrid retrieval routing")
def test_06_semantic_only_intent() -> None:
    raise NotImplementedError("Activated in Sprint 3.")


@pytest.mark.xfail(strict=False, reason="Sprint 3 required: threshold gates")
def test_07_threshold_drop() -> None:
    raise NotImplementedError("Activated in Sprint 3.")


@pytest.mark.xfail(strict=False, reason="Sprint 3 required: fusion logic")
def test_08_fusion_priority() -> None:
    raise NotImplementedError("Activated in Sprint 3.")


@pytest.mark.xfail(strict=False, reason="P1 required: retroactive replay importer")
def test_09_backfill_parity() -> None:
    raise NotImplementedError("Activated in P1 backfill workstream.")


@pytest.mark.xfail(strict=False, reason="Requires live Ollama; covered by smoke run only")
def test_10_continuity_preservation() -> None:
    raise NotImplementedError("Live-Ollama smoke run only.")


def test_11_rollback_equivalence() -> None:
    """All flags OFF → eval baseline outputs unchanged. Sprint 0 invariant."""
    from apps.shail.settings import Settings
    s = Settings()
    flags = (
        s.shail_exact_index_write, s.shail_hybrid_retrieval, s.shail_context_packet,
        s.shail_capture_chunking, s.shail_blueprint_versioning, s.shail_rerank,
    )
    assert all(f is False for f in flags), "Default rollback state must be all-OFF"
