"""Sprint 1 PR3: memory_facts writer + flag-gated save_blueprint integration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.shail import exact_index, telemetry


# ── compute_fact_id ─────────────────────────────────────────────────────────


def test_fact_id_deterministic() -> None:
    a = exact_index.compute_fact_id("mem1", "Tesla", "revenue", "2023")
    b = exact_index.compute_fact_id("mem1", "Tesla", "revenue", "2023")
    assert a == b
    assert len(a) == 32


def test_fact_id_distinguishes_periods() -> None:
    a = exact_index.compute_fact_id("mem1", "Tesla", "revenue", "2022")
    b = exact_index.compute_fact_id("mem1", "Tesla", "revenue", "2023")
    assert a != b


def test_fact_id_case_insensitive_on_identity() -> None:
    a = exact_index.compute_fact_id("mem1", "Tesla", "Revenue", "2023")
    b = exact_index.compute_fact_id("mem1", "tesla", "revenue", "2023")
    assert a == b


def test_fact_id_distinguishes_memories() -> None:
    a = exact_index.compute_fact_id("mem1", "Tesla", "revenue", "2023")
    b = exact_index.compute_fact_id("mem2", "Tesla", "revenue", "2023")
    assert a != b


# ── upsert_facts ────────────────────────────────────────────────────────────


def _seed_schema(isolated_db: Path) -> None:
    exact_index.init()


def test_upsert_writes_rows(isolated_db: Path) -> None:
    _seed_schema(isolated_db)
    facts = [
        {"entity": "Tesla", "attribute": "revenue", "value": "$81B",
         "value_num": 81e9, "unit": "USD", "period": "2023",
         "source_span": "10-K", "confidence": 0.9},
        {"entity": "Tesla", "attribute": "growth", "value": "62%",
         "value_num": 62, "unit": "%", "period": "2023"},
    ]
    n = exact_index.upsert_facts("mem1", facts)
    assert n == 2
    with sqlite3.connect(isolated_db) as con:
        rows = con.execute(
            "SELECT entity, attribute, value, value_num, period FROM memory_facts ORDER BY attribute"
        ).fetchall()
    assert rows[0] == ("Tesla", "growth", "62%", 62.0, "2023")
    assert rows[1] == ("Tesla", "revenue", "$81B", 81e9, "2023")


def test_upsert_idempotent(isolated_db: Path) -> None:
    _seed_schema(isolated_db)
    facts = [{"entity": "Tesla", "attribute": "revenue", "value": "$81B",
              "value_num": 81e9, "period": "2023"}]
    exact_index.upsert_facts("mem1", facts)
    exact_index.upsert_facts("mem1", facts)
    exact_index.upsert_facts("mem1", facts)
    with sqlite3.connect(isolated_db) as con:
        n = con.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
    assert n == 1


def test_upsert_updates_value_on_conflict(isolated_db: Path) -> None:
    """Same identity + new value → row updated, no duplicate."""
    _seed_schema(isolated_db)
    exact_index.upsert_facts("mem1", [
        {"entity": "Tesla", "attribute": "revenue", "value": "$80B",
         "value_num": 80e9, "period": "2023"}
    ])
    exact_index.upsert_facts("mem1", [
        {"entity": "Tesla", "attribute": "revenue", "value": "$81B",
         "value_num": 81e9, "period": "2023"}
    ])
    with sqlite3.connect(isolated_db) as con:
        rows = con.execute(
            "SELECT value, value_num FROM memory_facts"
        ).fetchall()
    assert rows == [("$81B", 81e9)]


def test_empty_facts_list_skips_write(isolated_db: Path) -> None:
    _seed_schema(isolated_db)
    n = exact_index.upsert_facts("mem1", [])
    assert n == 0


def test_telemetry_counter_increments(isolated_db: Path) -> None:
    _seed_schema(isolated_db)
    telemetry.reset()
    exact_index.upsert_facts("mem1", [
        {"entity": "X", "attribute": "y", "value": "z"}
    ])
    counters = telemetry.snapshot()["counters"]
    assert counters[telemetry.BLUEPRINT_FACTS_EXTRACTED] == 1.0


def test_collect_blueprint_facts_merges_metrics_and_facts() -> None:
    bp = {
        "facts":   [{"entity": "X", "attribute": "a", "value": "1"}],
        "metrics": [{"entity": "Y", "attribute": "b", "value": "2"}],
        "tables":  [{"title": "T", "rows": []}],
    }
    out = exact_index.collect_blueprint_facts(bp)
    assert len(out) == 2
    assert out[0]["entity"] == "X"
    assert out[1]["entity"] == "Y"


# ── save_blueprint integration (flag-gated) ─────────────────────────────────


def _make_blueprint() -> dict:
    return {
        "summary": "Tesla revenue review",
        "decisions": [], "questions_answered": [], "open_questions": [],
        "next_actions": [], "key_entities": ["Tesla"],
        "reasoning_chains": [], "failed_attempts": [],
        "facts": [
            {"entity": "Tesla", "attribute": "revenue", "value": "$81B",
             "value_num": 81e9, "unit": "USD", "period": "2023"},
        ],
        "metrics": [
            {"entity": "Tesla", "attribute": "growth", "value": "62%",
             "value_num": 62, "unit": "%", "period": "2023"},
        ],
        "tables": [],
        "extensions": {},
    }


def test_save_blueprint_skips_facts_when_flag_off(isolated_db: Path) -> None:
    """Default flag state must NOT write to memory_facts."""
    from apps.shail import blueprints, settings
    exact_index.init()
    # Confirm default OFF
    s = settings.get_settings()
    assert s.shail_exact_index_write is False
    blueprints.save_blueprint(
        "mem1", _make_blueprint(),
        user_id="u1", namespace="ns", content_type="ai_conversation",
    )
    with sqlite3.connect(isolated_db) as con:
        n_bp = con.execute("SELECT COUNT(*) FROM blueprints").fetchone()[0]
        n_facts = con.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
    assert n_bp == 1
    assert n_facts == 0


def test_save_blueprint_writes_facts_when_flag_on(isolated_db: Path, monkeypatch) -> None:
    """Flag ON → blueprint + facts persisted in one transaction."""
    from apps.shail import blueprints, settings
    exact_index.init()
    s = settings.get_settings()
    monkeypatch.setattr(s, "shail_exact_index_write", True)
    blueprints.save_blueprint(
        "mem1", _make_blueprint(),
        user_id="u1", namespace="ns", content_type="ai_conversation",
    )
    with sqlite3.connect(isolated_db) as con:
        n_bp = con.execute("SELECT COUNT(*) FROM blueprints").fetchone()[0]
        n_facts = con.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
        rows = con.execute(
            "SELECT entity, attribute, value_num FROM memory_facts ORDER BY attribute"
        ).fetchall()
    assert n_bp == 1
    assert n_facts == 2
    assert rows == [("Tesla", "growth", 62.0), ("Tesla", "revenue", 81e9)]


def test_save_blueprint_facts_idempotent_on_resave(isolated_db: Path, monkeypatch) -> None:
    """Re-saving same blueprint must not duplicate fact rows."""
    from apps.shail import blueprints, settings
    exact_index.init()
    s = settings.get_settings()
    monkeypatch.setattr(s, "shail_exact_index_write", True)
    blueprints.save_blueprint(
        "mem1", _make_blueprint(),
        user_id="u1", namespace="ns", content_type="ai_conversation",
    )
    blueprints.save_blueprint(
        "mem1", _make_blueprint(),
        user_id="u1", namespace="ns", content_type="ai_conversation",
    )
    with sqlite3.connect(isolated_db) as con:
        n = con.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
    assert n == 2  # 2 facts, not 4


def test_save_blueprint_survives_facts_failure(isolated_db: Path, monkeypatch) -> None:
    """If facts write raises, blueprint row must still persist."""
    from apps.shail import blueprints, settings, exact_index as ei
    ei.init()
    s = settings.get_settings()
    monkeypatch.setattr(s, "shail_exact_index_write", True)

    def boom(*a, **kw):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(ei, "upsert_facts", boom)

    blueprints.save_blueprint(
        "mem1", _make_blueprint(),
        user_id="u1", namespace="ns", content_type="ai_conversation",
    )
    with sqlite3.connect(isolated_db) as con:
        n = con.execute("SELECT COUNT(*) FROM blueprints").fetchone()[0]
    assert n == 1
