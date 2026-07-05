"""Sprint 1 PR1: memory_facts table + FTS5 schema."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def test_init_creates_blueprints_table(isolated_db: Path) -> None:
    from apps.shail import exact_index
    exact_index.init()
    with sqlite3.connect(isolated_db) as con:
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "blueprints" in names
    assert "memory_facts" in names


def test_memory_facts_columns(isolated_db: Path) -> None:
    from apps.shail import exact_index
    exact_index.init()
    with sqlite3.connect(isolated_db) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(memory_facts)")}
    expected = {
        "fact_id", "memory_id", "entity", "attribute", "value", "value_num",
        "unit", "period", "source_span", "confidence",
        "entry_version", "is_latest", "parent_fact_id", "superseded_by",
        "created_at",
    }
    assert expected.issubset(cols)


def test_init_idempotent(isolated_db: Path) -> None:
    from apps.shail import exact_index
    exact_index.init()
    exact_index.init()
    exact_index.init()
    with sqlite3.connect(isolated_db) as con:
        n = con.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
    assert n == 0


def test_fts5_detection(isolated_db: Path) -> None:
    from apps.shail import exact_index
    exact_index.init()
    # Most modern SQLite ships with FTS5; assert detection works either way.
    detected = exact_index.has_fts5()
    assert isinstance(detected, bool)


def test_fts_trigger_sync_when_available(isolated_db: Path) -> None:
    """If FTS5 present, INSERT into memory_facts must populate fts shadow."""
    from apps.shail import exact_index
    exact_index.init()
    if not exact_index.has_fts5():
        pytest.skip("FTS5 not compiled into this SQLite build")
    with sqlite3.connect(isolated_db) as con:
        con.execute(
            "INSERT INTO memory_facts "
            "(fact_id, memory_id, entity, attribute, value, period, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("f1", "m1", "Tesla", "revenue", "$81B", "2023", "2024-01-01"),
        )
        con.commit()
        n = con.execute(
            "SELECT COUNT(*) FROM memory_facts_fts WHERE memory_facts_fts MATCH 'Tesla'"
        ).fetchone()[0]
    assert n == 1
