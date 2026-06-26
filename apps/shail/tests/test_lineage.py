"""Sprint 5 PR2 + PR3: versioned fact upsert + as-of intent."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.shail import exact_index
from apps.shail.exact_index import (
    NumericFilter,
    search_numeric,
    search_numeric_historical,
    upsert_facts_versioned,
)
from apps.shail.retrieval.intent import classify, QueryIntent


# ── upsert_facts_versioned ──────────────────────────────────────────────────


def _seed_initial(isolated_db: Path) -> None:
    exact_index.init()
    upsert_facts_versioned("mem-1", [
        {"entity": "Acme", "attribute": "churn", "value": "4.2%",
         "value_num": 4.2, "unit": "%", "period": "Jan 2025"},
    ])


def test_first_version_inserts_with_is_latest(isolated_db: Path) -> None:
    exact_index.init()
    n = upsert_facts_versioned("mem-1", [
        {"entity": "X", "attribute": "y", "value": "1", "value_num": 1, "period": "P"},
    ])
    assert n == 1
    with sqlite3.connect(isolated_db) as con:
        rows = con.execute(
            "SELECT entry_version, is_latest, parent_fact_id, superseded_by FROM memory_facts"
        ).fetchall()
    assert rows == [(1, 1, None, None)]


def test_unchanged_value_no_op(isolated_db: Path) -> None:
    _seed_initial(isolated_db)
    upsert_facts_versioned("mem-1", [
        {"entity": "Acme", "attribute": "churn", "value": "4.2%",
         "value_num": 4.2, "unit": "%", "period": "Jan 2025"},
    ])
    with sqlite3.connect(isolated_db) as con:
        n = con.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
    assert n == 1


def test_value_change_creates_new_version(isolated_db: Path) -> None:
    _seed_initial(isolated_db)
    upsert_facts_versioned("mem-1", [
        {"entity": "Acme", "attribute": "churn", "value": "3.8%",
         "value_num": 3.8, "unit": "%", "period": "Jan 2025"},
    ])
    with sqlite3.connect(isolated_db) as con:
        rows = con.execute(
            "SELECT value, entry_version, is_latest, parent_fact_id, superseded_by "
            "FROM memory_facts ORDER BY entry_version"
        ).fetchall()
    assert len(rows) == 2
    old, new = rows
    assert old[0] == "4.2%" and old[1] == 1 and old[2] == 0  # is_latest=0
    assert new[0] == "3.8%" and new[1] == 2 and new[2] == 1  # is_latest=1
    # parent_fact_id of new must equal fact_id of prior; superseded_by of prior must equal new fact_id.
    assert new[3] is not None
    assert old[4] is not None


def test_only_one_is_latest_per_identity(isolated_db: Path) -> None:
    _seed_initial(isolated_db)
    upsert_facts_versioned("mem-1", [
        {"entity": "Acme", "attribute": "churn", "value": "3.8%",
         "value_num": 3.8, "unit": "%", "period": "Jan 2025"},
    ])
    with sqlite3.connect(isolated_db) as con:
        n_latest = con.execute(
            "SELECT COUNT(*) FROM memory_facts WHERE is_latest = 1 "
            "AND entity='Acme' AND attribute='churn' AND period='Jan 2025'"
        ).fetchone()[0]
    assert n_latest == 1


def test_search_numeric_returns_only_latest(isolated_db: Path) -> None:
    _seed_initial(isolated_db)
    upsert_facts_versioned("mem-1", [
        {"entity": "Acme", "attribute": "churn", "value": "3.8%",
         "value_num": 3.8, "unit": "%", "period": "Jan 2025"},
    ])
    hits = search_numeric(NumericFilter(entity="Acme", attribute="churn"), k=10)
    assert len(hits) == 1
    assert hits[0].value == "3.8%"


def test_search_numeric_historical_returns_all(isolated_db: Path) -> None:
    _seed_initial(isolated_db)
    upsert_facts_versioned("mem-1", [
        {"entity": "Acme", "attribute": "churn", "value": "3.8%",
         "value_num": 3.8, "unit": "%", "period": "Jan 2025"},
    ])
    hits = search_numeric_historical(NumericFilter(entity="Acme", attribute="churn"), k=10)
    values = [h.value for h in hits]
    assert "3.8%" in values
    assert "4.2%" in values


# ── as-of intent classification ─────────────────────────────────────────────


def test_intent_detects_as_of() -> None:
    plan = classify("what was Acme churn as of Jan 2025")
    assert plan.historical is True
    assert plan.as_of == "Jan 2025"


def test_intent_detects_previously() -> None:
    plan = classify("previously, what was the revenue in 2023")
    assert plan.historical is True


def test_intent_no_historical_for_present_query() -> None:
    plan = classify("what is current churn for Acme in 2025")
    assert plan.historical is False
    assert plan.as_of is None


def test_intent_historical_without_period_still_marked() -> None:
    plan = classify("what was the prior churn rate")
    assert plan.historical is True
    assert plan.as_of is None  # no period → no specific token


# ── flag-gated routing through save_blueprint ──────────────────────────────


def test_save_blueprint_uses_versioned_writer_when_flag_on(
    isolated_db: Path, monkeypatch
) -> None:
    from apps.shail import blueprints, settings
    exact_index.init()
    s = settings.get_settings()
    monkeypatch.setattr(s, "shail_exact_index_write", True)
    monkeypatch.setattr(s, "shail_blueprint_versioning", True)

    bp_v1 = {
        "summary": "x", "decisions": [], "questions_answered": [],
        "open_questions": [], "next_actions": [], "key_entities": [],
        "reasoning_chains": [], "failed_attempts": [],
        "facts": [{"entity": "Acme", "attribute": "churn", "value": "4.2%",
                   "value_num": 4.2, "unit": "%", "period": "Jan 2025"}],
        "metrics": [], "tables": [], "extensions": {},
    }
    bp_v2 = {**bp_v1, "facts": [
        {"entity": "Acme", "attribute": "churn", "value": "3.8%",
         "value_num": 3.8, "unit": "%", "period": "Jan 2025"},
    ]}
    blueprints.save_blueprint("m1", bp_v1, user_id="u", namespace="n", content_type="ai_conversation")
    blueprints.save_blueprint("m1", bp_v2, user_id="u", namespace="n", content_type="ai_conversation")

    with sqlite3.connect(isolated_db) as con:
        rows = con.execute(
            "SELECT value, is_latest FROM memory_facts ORDER BY entry_version"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0] == ("4.2%", 0)
    assert rows[1] == ("3.8%", 1)


def test_save_blueprint_plain_writer_when_versioning_off(
    isolated_db: Path, monkeypatch
) -> None:
    from apps.shail import blueprints, settings
    exact_index.init()
    s = settings.get_settings()
    monkeypatch.setattr(s, "shail_exact_index_write", True)
    monkeypatch.setattr(s, "shail_blueprint_versioning", False)

    bp = {
        "facts": [{"entity": "Acme", "attribute": "churn", "value": "4.2%",
                   "value_num": 4.2, "period": "Jan 2025"}],
        "metrics": [], "tables": [], "summary": "", "decisions": [],
        "questions_answered": [], "open_questions": [], "next_actions": [],
        "key_entities": [], "reasoning_chains": [], "failed_attempts": [],
        "extensions": {},
    }
    blueprints.save_blueprint("m1", bp, user_id="u", namespace="n", content_type="ai_conversation")
    bp_changed = {**bp, "facts": [
        {"entity": "Acme", "attribute": "churn", "value": "3.8%",
         "value_num": 3.8, "period": "Jan 2025"},
    ]}
    blueprints.save_blueprint("m1", bp_changed, user_id="u", namespace="n", content_type="ai_conversation")

    with sqlite3.connect(isolated_db) as con:
        rows = con.execute(
            "SELECT value, is_latest FROM memory_facts"
        ).fetchall()
    # Plain UPSERT — same fact_id → single row, value updated to latest.
    assert len(rows) == 1
    assert rows[0] == ("3.8%", 1)
