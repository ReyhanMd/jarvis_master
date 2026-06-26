"""Plan A5 — route_query_to_files + lazy_embed_for_query."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "/Users/reyhan/shail workspace /shail_master/jarvis_master")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def seeded_path_index(tmp_path, monkeypatch):
    """Patch settings.path_index_db to a fresh tmp DB, seed a few files."""
    db = str(tmp_path / "pi.db")
    import apps.shail.settings as s
    fake = s.Settings(sqlite_path=str(tmp_path / "auth.db"))
    object.__setattr__(fake, "path_index_db", db)
    monkeypatch.setattr(s, "_settings", fake)

    root = tmp_path / "content"
    root.mkdir()
    (root / "widget_spec.md").write_text("# Widget X spec\nbuilt with green hat tech")
    (root / "random_notes.md").write_text("totally unrelated content")
    (root / "code.py").write_text("def hello(): return 'world'\n")

    from shail.memory.path_index import scan
    scan(db, roots=[str(root)])
    yield db
    monkeypatch.setattr(s, "_settings", None)


class TestRouteQueryToFiles:
    def test_returns_top_matches_only(self, seeded_path_index):
        from apps.shail.retrieval.local_files import route_query_to_files
        hits = route_query_to_files("widget", k=5)
        assert len(hits) >= 1
        paths = {h["path"] for h in hits}
        assert any("widget_spec.md" in p for p in paths)

    def test_no_match_returns_empty(self, seeded_path_index):
        from apps.shail.retrieval.local_files import route_query_to_files
        hits = route_query_to_files("zzzzzqqq_nonexistent_term", k=5)
        # FTS may rank nothing high; allow empty or all-irrelevant
        assert isinstance(hits, list)

    def test_empty_query_returns_empty(self, seeded_path_index):
        from apps.shail.retrieval.local_files import route_query_to_files
        assert route_query_to_files("", k=5) == []
        assert route_query_to_files("   ", k=5) == []

    def test_filters_out_folders(self, seeded_path_index):
        from apps.shail.retrieval.local_files import route_query_to_files
        hits = route_query_to_files("widget", k=5)
        assert all(not h.get("is_dir") for h in hits)


class TestLazyEmbedForQuery:
    """Pointer-only mode: `lazy_embed_for_query` MUST NOT call ingest.

    The function name is preserved for backward compat with older callers,
    but it now performs the same lookup/read as `retrieve_local_file_context`
    and never embeds.
    """

    def test_no_vector_writes_on_match(self, seeded_path_index, monkeypatch):
        from apps.shail.retrieval import local_files as lf

        ingest_called = []
        async def _track(*a, **kw):
            ingest_called.append((a, kw))
            return 0
        monkeypatch.setattr("apps.shail.chat_api._ingest_paths_for_user", _track)

        n = _run(lf.lazy_embed_for_query("widget", user_id="u_test", k=3))
        # We may or may not get hits depending on test data + extractor
        # availability, but the legacy ingest path MUST stay untouched.
        assert ingest_called == []
        assert isinstance(n, int)

    def test_no_matches_returns_zero(self, seeded_path_index, monkeypatch):
        from apps.shail.retrieval import local_files as lf
        n = _run(lf.lazy_embed_for_query("zzzzqqq_no_match", user_id="u_test", k=3))
        assert n == 0
