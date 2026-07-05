"""Sprint 4 PR1: deterministic context packet builder."""
from __future__ import annotations

import pytest

from apps.shail.retrieval import packet


def make_hit(content: str, score: float, *, memory_id: str = "m1",
             surface: str = "semantic", title: str = "T") -> tuple:
    meta = {
        "id": memory_id, "memory_id": memory_id, "customId": memory_id,
        "title": title, "surface": surface,
    }
    return (content, score, meta)


# ── section headers always present ─────────────────────────────────────────


def test_empty_input_renders_all_sections() -> None:
    out = packet.build([])
    for header in (
        "=== EXACT_FACTS ===",
        "=== STRUCTURED_FACTS ===",
        "=== SUPPORTING_CONTEXT ===",
        "=== CITATIONS ===",
    ):
        assert header in out.text
    # Each empty section uses the (none) marker so Gemma policy fires.
    assert out.sections["EXACT_FACTS"] == "(none)"
    assert out.sections["STRUCTURED_FACTS"] == "(none)"
    assert out.sections["SUPPORTING_CONTEXT"] == "(none)"
    assert out.sections["CITATIONS"] == "(none)"


# ── routing by surface ─────────────────────────────────────────────────────


def test_exact_surface_routes_to_exact_facts() -> None:
    hit = make_hit("Tesla revenue (2023): $81B", 0.95,
                   memory_id="m-tesla", surface="exact", title="Tesla")
    out = packet.build([hit])
    assert "Tesla revenue (2023): $81B" in out.sections["EXACT_FACTS"]
    assert out.sections["SUPPORTING_CONTEXT"] == "(none)"


def test_fts_surface_routes_to_exact_facts() -> None:
    hit = make_hit("body", 0.7, surface="fts")
    out = packet.build([hit])
    assert out.sections["EXACT_FACTS"] != "(none)"


def test_numeric_surface_routes_to_exact_facts() -> None:
    hit = make_hit("body", 1.0, surface="numeric")
    out = packet.build([hit])
    assert out.sections["EXACT_FACTS"] != "(none)"


def test_fused_surface_routes_to_exact_facts() -> None:
    hit = make_hit("body", 1.4, surface="fused")
    out = packet.build([hit])
    assert out.sections["EXACT_FACTS"] != "(none)"


def test_semantic_surface_routes_to_supporting() -> None:
    hit = make_hit("Discussion of churn drivers.", 0.7, surface="semantic")
    out = packet.build([hit])
    assert out.sections["SUPPORTING_CONTEXT"] != "(none)"
    assert out.sections["EXACT_FACTS"] == "(none)"


def test_missing_surface_treated_as_semantic() -> None:
    """Legacy hits with no `surface` key must NOT pollute EXACT_FACTS."""
    h = ("body", 0.5, {"id": "x", "title": "X"})  # no surface
    out = packet.build([h])
    assert out.sections["EXACT_FACTS"] == "(none)"
    assert "body" in out.sections["SUPPORTING_CONTEXT"]


# ── citations ──────────────────────────────────────────────────────────────


def test_citations_collect_all_memory_ids() -> None:
    hits = [
        make_hit("a", 0.9, memory_id="m1", surface="exact"),
        make_hit("b", 0.5, memory_id="m2", surface="semantic"),
    ]
    out = packet.build(hits)
    assert "m1" in out.fact_ids
    assert "m2" in out.fact_ids
    assert "m1" in out.sections["CITATIONS"]
    assert "m2" in out.sections["CITATIONS"]


def test_citation_score_format() -> None:
    out = packet.build([make_hit("x", 0.873, memory_id="m1", surface="exact")])
    assert "score=0.87" in out.sections["CITATIONS"]


# ── structured rows passthrough ────────────────────────────────────────────


def test_structured_rows_render_in_section() -> None:
    rows = [
        {"entity": "Tesla", "attribute": "revenue", "value": "$81B",
         "period": "2023", "memory_id": "m-tesla"},
    ]
    out = packet.build([], structured_rows=rows)
    body = out.sections["STRUCTURED_FACTS"]
    assert "Tesla revenue" in body
    assert "$81B" in body
    assert "(2023)" in body
    assert "memory_id=m-tesla" in body


# ── caps + priority truncation ─────────────────────────────────────────────


def test_section_capped_when_oversized() -> None:
    """Cap triggers when total rendered body exceeds the section cap. Per-line
    snippet truncation keeps single hits short, so we feed many hits."""
    hits = [
        ("body" + str(i), 0.5,
         {"id": f"m{i}", "title": "T" * 80, "surface": "semantic"})
        for i in range(40)
    ]
    out = packet.build(hits)
    assert "[truncated]" in out.text
    assert "SUPPORTING_CONTEXT" in out.truncated_sections


def test_exact_facts_never_truncated_first() -> None:
    """EXACT_FACTS preserved at all costs — only SUPPORTING/STRUCTURED truncate first."""
    exact_hit = ("Tesla revenue (2023): $81B", 1.0,
                 {"id": "e", "title": "E", "surface": "exact"})
    support_hits = [
        ("body" + str(i), 0.5,
         {"id": f"s{i}", "title": "S" * 80, "surface": "semantic"})
        for i in range(40)
    ]
    out = packet.build([exact_hit] + support_hits)
    assert "EXACT_FACTS" not in out.truncated_sections
    assert "SUPPORTING_CONTEXT" in out.truncated_sections


# ── ordering ───────────────────────────────────────────────────────────────


def test_section_order_in_text() -> None:
    out = packet.build([])
    text = out.text
    i_exact = text.find("=== EXACT_FACTS ===")
    i_struct = text.find("=== STRUCTURED_FACTS ===")
    i_supp = text.find("=== SUPPORTING_CONTEXT ===")
    i_cite = text.find("=== CITATIONS ===")
    assert i_exact < i_struct < i_supp < i_cite
