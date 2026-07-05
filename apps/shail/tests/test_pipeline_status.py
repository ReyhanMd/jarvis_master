"""Tests for the per-memory pipeline status tracker."""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from apps.shail import pipeline_status as PS


@pytest.fixture()
def temp_db(monkeypatch):
    """Point auth_store at a tmp sqlite so pipeline_status writes there."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    import apps.shail.auth_store as A
    real_conn = A._conn

    def fake_conn():
        con = sqlite3.connect(tmp.name)
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(A, "_conn", fake_conn)
    yield tmp.name
    os.unlink(tmp.name)


def test_mark_stage_persists_and_get_returns_row(temp_db):
    PS.mark_stage("mem1", "captured", "done", size_bytes=1024)
    status = PS.get_status("mem1")
    assert "captured" in status["stages"]
    assert status["stages"]["captured"]["state"] == "done"
    assert status["stages"]["captured"]["size_bytes"] == 1024


def test_stage_progression_visible(temp_db):
    PS.mark_stage("m2", "captured", "done")
    PS.mark_stage("m2", "segmented", "done", size_bytes=5)
    PS.mark_stage("m2", "blueprint_extracting", "active")
    s = PS.get_status("m2")
    assert s["current_stage"] == "blueprint_extracting"
    assert s["current_state"] == "active"
    assert set(s["stages"].keys()) >= {"captured", "segmented", "blueprint_extracting"}


def test_active_list_filters_to_in_flight(temp_db):
    PS.mark_stage("a", "captured", "done")
    PS.mark_stage("b", "blueprint_extracting", "active")
    PS.mark_stage("c", "embedded", "active")
    active = PS.list_active()
    memory_ids = {row["memory_id"] for row in active}
    assert "b" in memory_ids
    assert "c" in memory_ids
    assert "a" not in memory_ids


def test_failed_state_persists_error(temp_db):
    PS.mark_stage("err1", "blueprint_extracting", "failed", error="ollama timeout")
    s = PS.get_status("err1")
    assert s["stages"]["blueprint_extracting"]["state"] == "failed"
    assert s["stages"]["blueprint_extracting"]["error"] == "ollama timeout"
