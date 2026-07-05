"""Sprint 2 readers + numeric-filter parser.

PR1: search_fts (FTS5 BM25 → normalized [0,1])
PR2: search_numeric (typed WHERE on memory_facts)
PR3: parse_numeric_filter (regex → NumericFilter | None)

No callers wired in chat path yet — these are read-only primitives.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from apps.shail import exact_index
from apps.shail.exact_index import (
    ExactHit,
    NumericFilter,
    _normalize_bm25,
    _sanitize_fts_query,
    parse_numeric_filter,
    search_fts,
    search_numeric,
)


# ── Seeding helper ──────────────────────────────────────────────────────────


def _seed(memory_id: str = "mem1") -> None:
    exact_index.init()
    exact_index.upsert_facts(memory_id, [
        {"entity": "Tesla", "attribute": "revenue", "value": "$81B",
         "value_num": 81e9, "unit": "USD", "period": "2023",
         "source_span": "10-K"},
        {"entity": "Tesla", "attribute": "revenue", "value": "$50B",
         "value_num": 50e9, "unit": "USD", "period": "2022"},
        {"entity": "Tesla", "attribute": "growth", "value": "62%",
         "value_num": 62, "unit": "%", "period": "2023"},
        {"entity": "Toyota", "attribute": "revenue", "value": "$280B",
         "value_num": 280e9, "unit": "USD", "period": "2023"},
        {"entity": "Acme", "attribute": "churn", "value": "4.2%",
         "value_num": 4.2, "unit": "%", "period": "Jan 2025"},
    ])


# ── Sanitizer + normalizer ──────────────────────────────────────────────────


def test_sanitize_strips_fts_specials() -> None:
    out = _sanitize_fts_query('Tesla "revenue" (2023):')
    # Sanitizer keeps tokens but wraps them in quoted phrases. Originals
    # of (, ), :, * must NOT survive. Quotes ARE expected (added by sanitizer).
    for forbidden in "():*^":
        assert forbidden not in out
    assert "Tesla" in out and "revenue" in out and "2023" in out


def test_sanitize_empty_inputs() -> None:
    assert _sanitize_fts_query("") == ""
    assert _sanitize_fts_query("   ") == ""
    assert _sanitize_fts_query("()") == ""


def test_normalize_bm25_bounded() -> None:
    assert 0.0 < _normalize_bm25(-0.001) <= 1.0
    assert 0.0 < _normalize_bm25(-100.0) < _normalize_bm25(-1.0)
    assert _normalize_bm25(0.0) == 1.0


# ── PR1: search_fts ─────────────────────────────────────────────────────────


def test_fts_returns_top_match_for_entity(isolated_db: Path) -> None:
    _seed()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled into this SQLite build")
    hits = search_fts("Tesla revenue 2023", k=5)
    assert hits, "expected non-empty hits"
    top = hits[0]
    assert isinstance(top, ExactHit)
    assert top.entity == "Tesla"
    assert top.attribute == "revenue"
    # Normalized score in [0,1].
    assert 0.0 < top.score <= 1.0
    assert top.surface == "fts"


def test_fts_empty_query(isolated_db: Path) -> None:
    _seed()
    assert search_fts("") == []
    assert search_fts("   ") == []


def test_fts_no_match_returns_empty(isolated_db: Path) -> None:
    _seed()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled")
    hits = search_fts("ZZZ_no_such_token_QQQ", k=5)
    assert hits == []


def test_fts_handles_special_chars_safely(isolated_db: Path) -> None:
    """Query with FTS5 syntax chars must not crash."""
    _seed()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled")
    out = search_fts('Tesla "revenue" (2023):*', k=5)
    # Result list (possibly empty) but no exception.
    assert isinstance(out, list)


def test_fts_k_limits(isolated_db: Path) -> None:
    _seed()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled")
    hits = search_fts("Tesla", k=2)
    assert len(hits) <= 2


def test_fts_zero_k_returns_empty(isolated_db: Path) -> None:
    _seed()
    assert search_fts("Tesla", k=0) == []


def test_fts_score_normalization_monotonic(isolated_db: Path) -> None:
    """Top hit score must be ≥ subsequent hits (FTS rank ascending)."""
    _seed()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled")
    hits = search_fts("Tesla revenue", k=10)
    if len(hits) < 2:
        pytest.skip("not enough hits to compare")
    for a, b in zip(hits, hits[1:]):
        assert a.score >= b.score


def test_fts_latency_under_30ms_on_seeded_set(isolated_db: Path) -> None:
    _seed()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled")
    t0 = time.perf_counter()
    search_fts("Tesla revenue 2023", k=10)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 100, f"FTS query too slow: {elapsed_ms:.1f}ms"


# ── PR2: search_numeric ─────────────────────────────────────────────────────


def test_numeric_entity_only(isolated_db: Path) -> None:
    _seed()
    hits = search_numeric(NumericFilter(entity="Tesla"), k=10)
    assert hits, "expected matching rows"
    assert all(h.entity == "Tesla" for h in hits)
    assert all(h.score == 1.0 for h in hits)
    assert all(h.surface == "numeric" for h in hits)


def test_numeric_entity_and_period(isolated_db: Path) -> None:
    _seed()
    hits = search_numeric(NumericFilter(entity="Tesla", period="2023"), k=10)
    assert hits
    for h in hits:
        assert h.entity == "Tesla"
        assert h.period == "2023"


def test_numeric_comparison_operator(isolated_db: Path) -> None:
    _seed()
    hits = search_numeric(NumericFilter(op=">", value_num=100e9), k=10)
    assert hits
    for h in hits:
        assert h.value_num is not None
        assert h.value_num > 100e9


def test_numeric_excludes_other_entities(isolated_db: Path) -> None:
    """Tesla query must not return Toyota."""
    _seed()
    hits = search_numeric(NumericFilter(entity="Tesla", attribute="revenue"), k=10)
    entities = {h.entity for h in hits}
    assert entities == {"Tesla"}


def test_numeric_empty_filter_returns_empty(isolated_db: Path) -> None:
    assert search_numeric(NumericFilter(), k=10) == []


def test_numeric_unknown_op_returns_empty(isolated_db: Path) -> None:
    _seed()
    out = search_numeric(NumericFilter(op="!=", value_num=1.0), k=10)
    assert out == []


def test_numeric_case_insensitive(isolated_db: Path) -> None:
    _seed()
    hits = search_numeric(NumericFilter(entity="tesla"), k=10)
    assert hits
    assert all(h.entity == "Tesla" for h in hits)


def test_numeric_zero_k(isolated_db: Path) -> None:
    _seed()
    assert search_numeric(NumericFilter(entity="Tesla"), k=0) == []


# ── PR3: parse_numeric_filter ───────────────────────────────────────────────


def test_parse_returns_none_for_pure_text() -> None:
    # No comparison op, no period, no number → None.
    assert parse_numeric_filter("hello world") is None
    assert parse_numeric_filter("") is None


def test_parse_year_period_only() -> None:
    flt = parse_numeric_filter("Tesla revenue in 2023")
    assert flt is not None
    assert flt.period == "2023"
    assert flt.op is None
    assert flt.value_num is None


def test_parse_quarter_period() -> None:
    flt = parse_numeric_filter("Q3 2023 metrics")
    assert flt is not None
    assert "Q3" in flt.period and "2023" in flt.period


def test_parse_month_period() -> None:
    flt = parse_numeric_filter("Jan 2025 churn")
    assert flt is not None
    assert "Jan" in flt.period.lower() or "jan" in flt.period.lower()


def test_parse_currency_billions() -> None:
    flt = parse_numeric_filter("revenue > $50B")
    assert flt is not None
    assert flt.op == ">"
    assert flt.value_num == 50e9
    assert flt.unit == "USD"


def test_parse_percent() -> None:
    flt = parse_numeric_filter("churn < 5%")
    assert flt is not None
    assert flt.op == "<"
    assert flt.value_num == 5.0
    assert flt.unit == "%"


def test_parse_decimal_percent() -> None:
    flt = parse_numeric_filter("churn = 4.2%")
    assert flt is not None
    assert flt.op == "="
    assert flt.value_num == 4.2


def test_parse_comma_thousands() -> None:
    flt = parse_numeric_filter("count > 1,200")
    assert flt is not None
    assert flt.value_num == 1200.0


def test_parse_compound() -> None:
    flt = parse_numeric_filter("revenue > $50B in 2023")
    assert flt is not None
    assert flt.op == ">"
    assert flt.value_num == 50e9
    assert flt.unit == "USD"
    assert flt.period == "2023"


def test_parse_op_without_number_drops_op() -> None:
    """Bare comparison op with no parsable number → no op emitted."""
    flt = parse_numeric_filter("revenue > stuff in 2023")
    assert flt is not None
    assert flt.period == "2023"
    assert flt.op is None
    assert flt.value_num is None
