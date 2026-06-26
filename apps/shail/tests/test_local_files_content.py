"""Content-aware local-file retrieval tests.

Covers the four critical fixes from the local-file production push:
  P1. Binary content lands in summary_snippet so FTS5 matches by content.
  P2. Diagnostics surface extractor-dep failures.
  P3. Pointer-only retrieval — no vector writes for any local file.
  P4. Scoring + stopword strip + size guards.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from apps.shail.retrieval import local_files as LF
from apps.shail.retrieval import diagnostics as DIAG
from shail.memory import path_index as PI


@pytest.fixture()
def temp_index(monkeypatch):
    """Isolated path_index DB + scan root for each test."""
    tmpdir = tempfile.mkdtemp(prefix="shail_lf_test_")
    db_path = os.path.join(tmpdir, "path_index.db")
    root = Path(tmpdir) / "docs"
    root.mkdir()
    yield db_path, root
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── P1: binary content → FTS5 match ─────────────────────────────────────────


def test_plain_text_snippet_indexed(temp_index):
    db_path, root = temp_index
    (root / "notes.md").write_text(
        "# Q3 revenue notes\n\nRevenue hit $4.2M, up 12% YoY. Owner: Mira.",
        encoding="utf-8",
    )
    PI.upsert_file(db_path, str(root / "notes.md"))
    rows = PI.search(db_path, "revenue Mira", limit=5)
    assert any("notes.md" in r["path"] for r in rows), \
        "FTS5 should match the markdown by content terms"


def test_extract_snippet_invokes_extractor_for_binary(temp_index, monkeypatch):
    """For a .pdf, _extract_snippet should call the rag extractor instead of
    returning None. Critical bug #1: without this, FTS5 stores nothing for
    binary docs and content-based questions miss every PDF on the device."""
    db_path, root = temp_index
    fake_pdf = root / "report.pdf"
    fake_pdf.write_bytes(b"%PDF-fake-content")

    extracted = "Q3 board memo: revenue up 12%. Owner: Mira. Risk: supply chain."

    with mock.patch(
        "shail.memory.path_index._extract_snippet",
        wraps=PI._extract_snippet,
    ) as wrapped:
        with mock.patch(
            "shail.memory.rag._extract_text_from_file",
            return_value=extracted,
        ):
            PI.upsert_file(db_path, str(fake_pdf))
            assert wrapped.called

    # Confirm snippet stored
    row = PI.get_by_path(db_path, str(fake_pdf))
    assert row is not None
    assert row["summary_snippet"] and "Mira" in row["summary_snippet"]


def test_binary_content_indexed_makes_fts_match(temp_index, monkeypatch):
    db_path, root = temp_index
    fake_pdf = root / "board.pdf"
    fake_pdf.write_bytes(b"%PDF-fake")

    extracted = "Project Atlas: roadmap discussion. Acquired Globex assets in Q3."

    with mock.patch(
        "shail.memory.rag._extract_text_from_file",
        return_value=extracted,
    ):
        PI.upsert_file(db_path, str(fake_pdf))

    rows = PI.search(db_path, "Globex Atlas", limit=5)
    matching = [r for r in rows if r["path"] == str(fake_pdf)]
    assert matching, "PDF should be discoverable by indexed content"


# ── P2: diagnostics ─────────────────────────────────────────────────────────


def test_diagnostics_records_retrieval_stats():
    DIAG.reset()
    DIAG.record("hit_too_large")
    DIAG.record("hits_emitted", value=3)
    s = DIAG.stats()
    assert s.get("hit_too_large") == 1
    assert s.get("hits_emitted") == 3


def test_health_summary_lists_extractor_deps():
    summary = DIAG.health_summary()
    assert "extractor_deps" in summary
    exts = {d["ext"] for d in summary["extractor_deps"]}
    assert {".pdf", ".docx", ".xlsx"}.issubset(exts)


def test_diagnostics_pushes_query_trace(temp_index, monkeypatch):
    """retrieve_local_file_context should push a trace row per query."""
    db_path, root = temp_index
    monkeypatch.setattr(
        LF.get_settings(), "path_index_db", db_path, raising=False,
    )
    DIAG.reset()
    LF.retrieve_local_file_context("query about nothing", k=3)
    traces = DIAG.recent_traces()
    assert len(traces) >= 1
    assert traces[-1]["query"].startswith("query about")


# ── P3: pointer-only — no vector writes ─────────────────────────────────────


def test_route_query_to_files_does_not_touch_vector_store(temp_index, monkeypatch):
    """Verify the retrieval path doesn't import shail.memory.rag.ingest."""
    db_path, root = temp_index
    (root / "memo.md").write_text("Q3 revenue $4.2M", encoding="utf-8")
    PI.upsert_file(db_path, str(root / "memo.md"))

    monkeypatch.setattr(
        LF.get_settings(), "path_index_db", db_path, raising=False,
    )

    with mock.patch("shail.memory.rag.ingest") as mock_ingest:
        LF.retrieve_local_file_context("revenue", k=3)
        assert not mock_ingest.called, \
            "Pointer-only retrieval must not write to the vector store"


# ── P4: scoring + stopword strip + size guard ───────────────────────────────


def test_stopwords_dropped_from_fts_query():
    assert LF._tokenize_for_fts("what is in my resume") == ["resume"]
    assert LF._tokenize_for_fts("how does the Q3 report look?") == ["Q3", "report", "look"]


def test_fts_query_safe_with_special_chars():
    """Apostrophes / question marks / hyphens must not break the FTS expr."""
    q = LF._build_fts_query("what's in dad's report?")
    # Output uses bare alphanumeric tokens — no stray quotes or special chars
    assert q is not None
    assert "?" not in q
    assert "'" not in q


def test_empty_query_returns_no_hits(temp_index, monkeypatch):
    db_path, _ = temp_index
    monkeypatch.setattr(
        LF.get_settings(), "path_index_db", db_path, raising=False,
    )
    assert LF.route_query_to_files("") == []
    assert LF.route_query_to_files("   ") == []


def test_score_is_propagated_from_fts(temp_index, monkeypatch):
    db_path, root = temp_index
    (root / "a.md").write_text("alpha beta gamma delta", encoding="utf-8")
    (root / "b.md").write_text("delta only", encoding="utf-8")
    PI.upsert_file(db_path, str(root / "a.md"))
    PI.upsert_file(db_path, str(root / "b.md"))

    monkeypatch.setattr(
        LF.get_settings(), "path_index_db", db_path, raising=False,
    )

    rows = LF.route_query_to_files("alpha gamma", k=5)
    assert rows, "FTS should match alpha/gamma"
    for r in rows:
        assert "_score_norm" in r
        assert 0.0 <= r["_score_norm"] <= 1.0


def test_oversized_file_dropped_by_read_cap(temp_index, monkeypatch):
    db_path, root = temp_index
    big = root / "huge.md"
    big.write_text("token " * 10_000, encoding="utf-8")
    PI.upsert_file(db_path, str(big))

    monkeypatch.setattr(
        LF.get_settings(), "path_index_db", db_path, raising=False,
    )

    # 1KB cap — file is way bigger than that.
    DIAG.reset()
    hits = LF.retrieve_local_file_context("token", k=3, read_cap_bytes=1024)
    assert hits == []
    assert DIAG.stats().get("hit_too_large", 0) >= 1
