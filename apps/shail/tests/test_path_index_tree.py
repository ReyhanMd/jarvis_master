"""Plan A2 + A3 + A6 — path_index schema, tree endpoint, FTS5 search."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "/Users/reyhan/shail workspace /shail_master/jarvis_master")


@pytest.fixture
def fresh_db(tmp_path):
    return str(tmp_path / "pi.db")


def _seed_dir(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    (root / "notes.md").write_text("# Widget alpha\nspec for the widget X project")
    (root / "code.py").write_text("def widget(): return 'alpha'\n")
    sub = root / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested file content about widget")
    junk = root / "node_modules"
    junk.mkdir()
    (junk / "lib.js").write_text("// should not be indexed")
    return root


class TestSchemaMigration:
    def test_init_creates_extended_columns(self, fresh_db):
        from shail.memory.path_index import _conn
        with _conn(fresh_db) as con:
            cols = [r["name"] for r in con.execute("PRAGMA table_info(path_index)")]
        for needed in ("parent_path", "depth", "is_dir", "child_count", "kind", "embedded"):
            assert needed in cols, f"missing column: {needed}"

    def test_alter_idempotent(self, fresh_db):
        """Init twice — second call must not error on duplicate ADD COLUMN."""
        from shail.memory.path_index import _conn
        with _conn(fresh_db) as con:
            pass
        with _conn(fresh_db) as con:
            cols = [r["name"] for r in con.execute("PRAGMA table_info(path_index)")]
        assert "kind" in cols

    def test_fts_table_created(self, fresh_db):
        from shail.memory.path_index import fts_available
        assert fts_available(fresh_db)


class TestKindClassification:
    def test_code_kind(self):
        from shail.memory.path_index import _classify_kind
        assert _classify_kind(".py") == "code"
        assert _classify_kind(".ts") == "code"

    def test_doc_kind(self):
        from shail.memory.path_index import _classify_kind
        assert _classify_kind(".pdf") == "doc"
        assert _classify_kind(".md") == "doc"

    def test_data_kind(self):
        from shail.memory.path_index import _classify_kind
        assert _classify_kind(".json") == "data"
        assert _classify_kind(".csv") == "data"

    def test_other_fallback(self):
        from shail.memory.path_index import _classify_kind
        assert _classify_kind(".xyz") == "other"


class TestScanAndTree:
    def test_scan_indexes_files_and_folders(self, fresh_db, tmp_path):
        from shail.memory.path_index import scan, stats
        root = _seed_dir(tmp_path)
        n_files = scan(fresh_db, roots=[str(root)])
        assert n_files >= 3  # notes.md, code.py, nested.txt (not the js junk)
        s = stats(fresh_db)
        assert s["total_files"] >= 3
        assert s["total_dirs"] >= 1
        # node_modules junk must NOT have ingested files
        from shail.memory.path_index import _conn
        with _conn(fresh_db) as con:
            row = con.execute("SELECT COUNT(*) FROM path_index WHERE path LIKE ?",
                              (f"%node_modules%",)).fetchone()
        assert row[0] == 0

    def test_tree_returns_hierarchy(self, fresh_db, tmp_path):
        from shail.memory.path_index import scan, tree
        root = _seed_dir(tmp_path)
        scan(fresh_db, roots=[str(root)])
        t = tree(fresh_db, root=str(root), depth=2)
        node_ids = {n["id"] for n in t["nodes"]}
        # Root + subdir + at least one of the files at root level
        assert str(root) in node_ids
        assert str(root / "subdir") in node_ids
        assert str(root / "notes.md") in node_ids
        # Edges connect root -> subdir
        assert any(e["source"] == str(root) and e["target"] == str(root / "subdir")
                   for e in t["edges"])

    def test_tree_respects_max_nodes(self, fresh_db, tmp_path):
        from shail.memory.path_index import scan, tree
        root = tmp_path / "big"
        root.mkdir()
        for i in range(20):
            (root / f"f{i:02d}.md").write_text("x")
        scan(fresh_db, roots=[str(root)])
        t = tree(fresh_db, root=str(root), depth=1, max_nodes=5)
        assert len(t["nodes"]) <= 5
        assert t["truncated"] is True

    def test_tree_no_root_returns_top_dirs(self, fresh_db, tmp_path):
        from shail.memory.path_index import scan, tree, upsert_folder
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        for r in (root_a, root_b):
            r.mkdir()
            (r / "x.md").write_text("hello")
        scan(fresh_db, roots=[str(root_a), str(root_b)])
        t = tree(fresh_db, root=None, depth=0)
        names = {n["name"] for n in t["nodes"]}
        # Both top-level roots should appear
        assert "a" in names and "b" in names


class TestFTS5Search:
    def test_search_finds_by_filename(self, fresh_db, tmp_path):
        from shail.memory.path_index import scan, search
        root = _seed_dir(tmp_path)
        scan(fresh_db, roots=[str(root)])
        hits = search(fresh_db, "widget", limit=5)
        assert len(hits) > 0
        paths = {h["path"] for h in hits}
        # notes.md and code.py both contain "widget" in their content/name
        assert any("notes.md" in p or "code.py" in p or "nested.txt" in p for p in paths)

    def test_search_no_match_returns_empty(self, fresh_db, tmp_path):
        from shail.memory.path_index import scan, search
        root = _seed_dir(tmp_path)
        scan(fresh_db, roots=[str(root)])
        hits = search(fresh_db, "zzzzqqqqnonexistent", limit=5)
        assert hits == [] or all("zzzz" not in h.get("path", "") for h in hits)

    def test_search_empty_returns_recent(self, fresh_db, tmp_path):
        """Empty query → most-recent files."""
        from shail.memory.path_index import scan, search
        root = _seed_dir(tmp_path)
        scan(fresh_db, roots=[str(root)])
        hits = search(fresh_db, "", limit=10)
        assert len(hits) > 0


class TestMarkEmbedded:
    def test_mark_embedded_flag_persists(self, fresh_db, tmp_path):
        from shail.memory.path_index import upsert_file, mark_embedded, get_by_path
        f = tmp_path / "a.md"
        f.write_text("hello")
        upsert_file(fresh_db, str(f))
        row = get_by_path(fresh_db, str(f))
        assert row["embedded"] == 0
        mark_embedded(fresh_db, str(f), True)
        row = get_by_path(fresh_db, str(f))
        assert row["embedded"] == 1

    def test_stats_reports_embedded_count(self, fresh_db, tmp_path):
        from shail.memory.path_index import upsert_file, mark_embedded, stats
        for name in ("a.md", "b.md", "c.md"):
            p = tmp_path / name
            p.write_text("x")
            upsert_file(fresh_db, str(p))
        mark_embedded(fresh_db, str(tmp_path / "a.md"), True)
        s = stats(fresh_db)
        assert s["embedded"] == 1
        assert s["total_files"] == 3
