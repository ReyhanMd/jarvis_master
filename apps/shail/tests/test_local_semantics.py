from __future__ import annotations

from pathlib import Path
from unittest import mock
import asyncio
import sys
import types


def _setup(tmp_path: Path, monkeypatch):
    from apps.shail.settings import get_settings

    db_path = str(tmp_path / "phase4.sqlite3")
    root = tmp_path / "approved"
    root.mkdir()
    settings = get_settings()
    monkeypatch.setattr(settings, "path_index_db", db_path, raising=False)
    monkeypatch.setattr(settings, "sqlite_path", db_path, raising=False)
    monkeypatch.setattr(settings, "scan_roots", [str(root)], raising=False)
    monkeypatch.setattr(settings, "shail_local_files_k", 5, raising=False)
    monkeypatch.setattr(settings, "shail_local_files_snippet_chars", 900, raising=False)
    monkeypatch.setattr(settings, "shail_local_files_read_cap_bytes", 100_000, raising=False)
    return db_path, root


def _scan(db_path: str, root: Path):
    from shail.memory import path_index

    path_index.scan(db_path, roots=[str(root)])


def _build_semantics(db_path: str, root: Path):
    from apps.shail import local_semantics

    _scan(db_path, root)
    return local_semantics.build_semantics(path_db=db_path, semantics_db=db_path, limit=500)


def test_extracts_entities_dates_money_percent_tasks_and_facts(tmp_path, monkeypatch):
    from apps.shail import local_semantics

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "dubai_plan.md").write_text(
        "# Dubai Pricing\n"
        "Reyhan met Alpha Labs on Jan 12 2026.\n"
        "Revenue target is $4.2M and churn is 4.2%.\n"
        "- [ ] Send pricing deck by 2026-02-01\n"
        "Decision: approved the Dubai launch plan.\n",
        encoding="utf-8",
    )

    result = _build_semantics(db_path, root)
    found = local_semantics.search("Dubai", semantics_db=db_path, limit=50)

    assert result["processed"] == 1
    assert result["entities"] >= 2
    assert result["facts"] >= 4
    assert result["tasks"] == 1
    assert any(e["label"] == "Reyhan" for e in found["entities"])
    assert any(f["unit"] == "USD" and f["value_num"] == 4_200_000 for f in found["facts"])
    assert any(f["unit"] == "%" and f["value_num"] == 4.2 for f in found["facts"])
    assert any(t["due_date"] == "2026-02-01" for t in found["tasks"])
    assert any(f["attribute"] == "decision" for f in found["facts"])


def test_semantics_skips_unchanged_and_reextracts_changed_files(tmp_path, monkeypatch):
    from apps.shail import local_semantics

    db_path, root = _setup(tmp_path, monkeypatch)
    file_path = root / "metrics.md"
    file_path.write_text("Revenue is $1M.", encoding="utf-8")

    first = _build_semantics(db_path, root)
    second = local_semantics.build_semantics(path_db=db_path, semantics_db=db_path, limit=500)

    file_path.write_text("Revenue is $2M.", encoding="utf-8")
    _scan(db_path, root)
    third = local_semantics.build_semantics(path_db=db_path, semantics_db=db_path, limit=500)
    found = local_semantics.search("$2M", semantics_db=db_path, limit=50)

    assert first["processed"] == 1
    assert second["skipped"] == 1
    assert third["processed"] == 1
    assert any(f["value"] == "$2M" for f in found["facts"])


def test_semantics_hide_denied_and_deleted_files(tmp_path, monkeypatch):
    from apps.shail import local_semantics
    from shail.memory import path_index

    db_path, root = _setup(tmp_path, monkeypatch)
    blocked = root / "private"
    blocked.mkdir()
    allowed = root / "allowed.md"
    denied = blocked / "secret.md"
    gone = root / "gone.md"
    allowed.write_text("Visible Revenue is $1M.", encoding="utf-8")
    denied.write_text("Secret Revenue is $99M.", encoding="utf-8")
    gone.write_text("Gone Revenue is $5M.", encoding="utf-8")
    path_index.add_deny_path(db_path, str(blocked), reason="private")

    _build_semantics(db_path, root)
    gone.unlink()
    _scan(db_path, root)

    found = local_semantics.search("Revenue", semantics_db=db_path, limit=50)
    paths = {item["path"] for item in [*found["facts"], *found["entities"], *found["tasks"]]}

    assert str(allowed) in paths
    assert str(denied) not in paths
    assert str(gone) not in paths


def test_graph_contains_semantic_nodes_and_edges(tmp_path, monkeypatch):
    from apps.shail import local_graph, local_semantics

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "launch.md").write_text("Reyhan owns launch. Revenue is $3M. - [ ] Call Alpha Labs", encoding="utf-8")
    _build_semantics(db_path, root)
    graph = local_graph.build_local_file_graph(path_db=db_path, graph_db=db_path, env_roots=[str(root)], limit=500)

    node_types = {node["type"] for node in graph["nodes"]}
    relations = {edge["relation"] for edge in graph["relations"]}

    assert {"person", "money_value", "task"}.issubset(node_types)
    assert "mentions_person" in relations
    assert "has_metric" in relations
    assert "has_task" in relations


def test_evidence_bundle_includes_semantic_facts_and_warnings(tmp_path, monkeypatch):
    from apps.shail.evidence_bundle import build_evidence_bundle
    from apps.shail import local_graph

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "revenue_a.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    (root / "revenue_b.md").write_text("Dubai Revenue is $2M.", encoding="utf-8")
    _build_semantics(db_path, root)
    local_graph.build_local_file_graph(path_db=db_path, graph_db=db_path, env_roots=[str(root)], limit=500)

    bundle = build_evidence_bundle("Dubai Revenue", k=8, include_graph=True)

    assert bundle.semantic_facts
    assert "Semantic evidence:" in bundle.prompt_context
    assert bundle.semantic_warnings
    assert any("Conflicting semantic facts" in warning for warning in bundle.semantic_warnings)


def test_empty_semantics_returns_low_confidence_without_fake_facts(tmp_path, monkeypatch):
    from apps.shail import local_semantics

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "empty.md").write_text("plain words only", encoding="utf-8")
    _build_semantics(db_path, root)
    found = local_semantics.search("plain", semantics_db=db_path, limit=50)

    assert found["facts"] == []
    assert found["tasks"] == []


def test_semantics_pointer_only_no_vector_ingest(tmp_path, monkeypatch):
    from apps.shail import local_semantics

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "memo.md").write_text("Revenue is $1M.", encoding="utf-8")
    _scan(db_path, root)

    with mock.patch("shail.memory.rag.ingest") as mock_ingest:
        local_semantics.build_semantics(path_db=db_path, semantics_db=db_path, limit=500)
        assert not mock_ingest.called


def test_semantics_api_endpoint_shapes(tmp_path, monkeypatch):
    auth_api = types.ModuleType("apps.shail.auth_api")
    auth_api.get_current_user = lambda: "test-user"
    monkeypatch.setitem(sys.modules, "apps.shail.auth_api", auth_api)

    from apps.shail.local_rag_api import (
        local_rag_semantics_build,
        local_rag_semantics_file,
        local_rag_semantics_search,
        local_rag_semantics_status,
    )
    from shail.memory import path_index

    db_path, root = _setup(tmp_path, monkeypatch)
    file_path = root / "api.md"
    file_path.write_text("Reyhan Revenue is $1M. - [ ] Follow up", encoding="utf-8")
    _scan(db_path, root)

    build = asyncio.run(local_rag_semantics_build(limit=500, force=False, user_id="test-user"))
    status = asyncio.run(local_rag_semantics_status(user_id="test-user"))
    search = asyncio.run(local_rag_semantics_search(q="Revenue", limit=50, user_id="test-user"))
    row = path_index.get_by_path(db_path, str(file_path))
    by_file = asyncio.run(local_rag_semantics_file(file_id=row["id"], user_id="test-user"))

    assert build.processed == 1
    assert status.facts >= 1
    assert search["facts"]
    assert by_file["facts"]
