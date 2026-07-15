from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path


def _setup(tmp_path: Path, monkeypatch):
    from apps.shail.settings import get_settings

    db_path = str(tmp_path / "reasoning.sqlite3")
    root = tmp_path / "approved"
    root.mkdir()
    settings = get_settings()
    monkeypatch.setattr(settings, "path_index_db", db_path, raising=False)
    monkeypatch.setattr(settings, "sqlite_path", db_path, raising=False)
    monkeypatch.setattr(settings, "scan_roots", [str(root)], raising=False)
    monkeypatch.setattr(settings, "shail_local_files_k", 5, raising=False)
    monkeypatch.setattr(settings, "shail_local_files_snippet_chars", 800, raising=False)
    monkeypatch.setattr(settings, "shail_local_files_read_cap_bytes", 100_000, raising=False)
    return db_path, root


def _build_semantics(db_path: str, root: Path):
    from apps.shail import local_semantics
    from shail.memory import path_index

    path_index.scan(db_path, roots=[str(root)])
    return local_semantics.build_semantics(path_db=db_path, semantics_db=db_path, limit=500, force=True)


def test_reasoning_groups_equivalent_facts_and_resolves(tmp_path, monkeypatch):
    from apps.shail import local_semantic_reasoning

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "revenue_a.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    (root / "revenue_b.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    _build_semantics(db_path, root)

    result = local_semantic_reasoning.build_reasoning(semantics_db=db_path, limit=500)
    search = local_semantic_reasoning.search("Dubai Revenue", semantics_db=db_path, limit=20)

    assert result["groups"] >= 1
    assert result["claims"] >= 2
    assert any(g["preferred_claim"] for g in search["items"])
    assert any((g["preferred_claim"] or {}).get("support_count", 0) >= 2 for g in search["items"])


def test_reasoning_detects_conflict_and_prefers_latest_version(tmp_path, monkeypatch):
    from apps.shail import local_semantic_reasoning

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Revenue_v1.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    (root / "Dubai_Revenue_v2.md").write_text("Dubai Revenue is $2M.", encoding="utf-8")
    _build_semantics(db_path, root)

    result = local_semantic_reasoning.build_reasoning(semantics_db=db_path, limit=500)
    conflicts = local_semantic_reasoning.conflicts(semantics_db=db_path, limit=20)

    assert result["conflicts"] >= 1
    assert conflicts["items"]
    assert any("v2" in ((g["preferred_claim"] or {}).get("path") or "") for g in conflicts["items"])
    assert any("Competing" or g.get("warnings") for g in conflicts["items"])


def test_reasoning_ignores_denied_and_deleted_files(tmp_path, monkeypatch):
    from apps.shail import local_semantic_reasoning
    from shail.memory import path_index

    db_path, root = _setup(tmp_path, monkeypatch)
    blocked = root / "private"
    blocked.mkdir()
    allowed = root / "allowed.md"
    denied = blocked / "secret.md"
    gone = root / "gone.md"
    allowed.write_text("Dubai Revenue is $1M.", encoding="utf-8")
    denied.write_text("Dubai Revenue is $99M.", encoding="utf-8")
    gone.write_text("Dubai Revenue is $5M.", encoding="utf-8")
    path_index.add_deny_path(db_path, str(blocked), reason="private")
    _build_semantics(db_path, root)
    gone.unlink()
    path_index.scan(db_path, roots=[str(root)])

    local_semantic_reasoning.build_reasoning(semantics_db=db_path, limit=500)
    search = local_semantic_reasoning.search("Dubai Revenue", semantics_db=db_path, limit=20)
    paths = {
        claim["path"]
        for group in search["items"]
        for claim in [group.get("preferred_claim"), *(group.get("competing_claims") or [])]
        if claim
    }

    assert str(allowed) in paths
    assert str(denied) not in paths
    assert str(gone) not in paths


def test_reasoning_is_idempotent_and_pointer_only(tmp_path, monkeypatch):
    import sqlite3

    from apps.shail import local_semantic_reasoning

    db_path, root = _setup(tmp_path, monkeypatch)
    body = "Dubai Revenue is $1M. " + ("raw-body-token " * 80)
    (root / "memo.md").write_text(body, encoding="utf-8")
    _build_semantics(db_path, root)

    first = local_semantic_reasoning.build_reasoning(semantics_db=db_path, limit=500)
    second = local_semantic_reasoning.build_reasoning(semantics_db=db_path, limit=500)
    with sqlite3.connect(db_path) as con:
        blobs = "\n".join(
            row[0] or ""
            for row in con.execute("SELECT metadata_json FROM local_semantic_fact_claims").fetchall()
        )

    assert first == second
    assert "raw-body-token raw-body-token raw-body-token raw-body-token" not in blobs


def test_evidence_bundle_uses_reasoning_and_warns_conflicts(tmp_path, monkeypatch):
    from apps.shail import local_graph, local_semantic_reasoning
    from apps.shail.evidence_bundle import build_evidence_bundle

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Revenue_v1.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    (root / "Dubai_Revenue_v2.md").write_text("Dubai Revenue is $2M.", encoding="utf-8")
    _build_semantics(db_path, root)
    local_semantic_reasoning.build_reasoning(semantics_db=db_path, limit=500)
    local_graph.build_local_file_graph(path_db=db_path, graph_db=db_path, env_roots=[str(root)], limit=500)

    bundle = build_evidence_bundle("Dubai Revenue", k=8, include_graph=True)

    assert bundle.semantic_resolutions
    assert bundle.semantic_conflicts
    assert bundle.reasoning_warnings
    assert "Resolved semantic facts:" in bundle.prompt_context
    assert any("Preferred resolved semantic fact" in item.reason for item in bundle.selected_files)


def test_graph_contains_reasoning_edges(tmp_path, monkeypatch):
    from apps.shail import local_graph, local_semantic_reasoning

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Revenue_v1.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    (root / "Dubai_Revenue_v2.md").write_text("Dubai Revenue is $2M.", encoding="utf-8")
    _build_semantics(db_path, root)
    local_semantic_reasoning.build_reasoning(semantics_db=db_path, limit=500)

    graph = local_graph.build_local_file_graph(path_db=db_path, graph_db=db_path, env_roots=[str(root)], limit=500)
    relations = {edge["relation"] for edge in graph["relations"]}
    node_types = {node["type"] for node in graph["nodes"]}

    assert "fact_group" in node_types
    assert "supports_answer" in relations
    assert "contradicts" in relations


def test_reasoning_api_endpoint_shapes(tmp_path, monkeypatch):
    auth_api = types.ModuleType("apps.shail.auth_api")
    auth_api.get_current_user = lambda: "test-user"
    monkeypatch.setitem(sys.modules, "apps.shail.auth_api", auth_api)

    from apps.shail.local_rag_api import (
        LocalReasoningBuildRequest,
        local_rag_semantics_reasoning_build,
        local_rag_semantics_reasoning_conflicts,
        local_rag_semantics_reasoning_search,
        local_rag_semantics_reasoning_status,
    )

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "api.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    _build_semantics(db_path, root)

    build = asyncio.run(local_rag_semantics_reasoning_build(
        LocalReasoningBuildRequest(limit=500, force=False),
        user_id="test-user",
    ))
    status = asyncio.run(local_rag_semantics_reasoning_status(user_id="test-user"))
    search = asyncio.run(local_rag_semantics_reasoning_search(q="Dubai", limit=50, user_id="test-user"))
    conflicts = asyncio.run(local_rag_semantics_reasoning_conflicts(limit=50, user_id="test-user"))

    assert build.groups >= 1
    assert status.claims >= 1
    assert search["items"]
    assert "items" in conflicts
