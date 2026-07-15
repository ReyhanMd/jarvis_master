from __future__ import annotations

from pathlib import Path
from unittest import mock
import asyncio
import sys
import types


def _setup(tmp_path: Path, monkeypatch):
    from apps.shail.settings import get_settings

    db_path = str(tmp_path / "evidence.sqlite3")
    root = tmp_path / "approved"
    root.mkdir()
    settings = get_settings()
    monkeypatch.setattr(settings, "path_index_db", db_path, raising=False)
    monkeypatch.setattr(settings, "sqlite_path", db_path, raising=False)
    monkeypatch.setattr(settings, "shail_local_files_k", 5, raising=False)
    monkeypatch.setattr(settings, "shail_local_files_snippet_chars", 800, raising=False)
    monkeypatch.setattr(settings, "shail_local_files_read_cap_bytes", 10_000, raising=False)
    return db_path, root


def _scan_and_graph(db_path: str, root: Path):
    from apps.shail import local_graph
    from shail.memory import path_index

    path_index.scan(db_path, roots=[str(root)])
    local_graph.build_local_file_graph(
        path_db=db_path,
        graph_db=db_path,
        env_roots=[str(root)],
        limit=500,
    )


def test_evidence_bundle_includes_direct_match(tmp_path, monkeypatch):
    from apps.shail.evidence_bundle import build_evidence_bundle

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Pitch_v1.md").write_text("Dubai pricing plan for Alpha", encoding="utf-8")
    _scan_and_graph(db_path, root)

    bundle = build_evidence_bundle("pricing Alpha", k=5, include_graph=True)

    assert bundle.selected_files
    assert bundle.direct_matches
    assert bundle.selected_files[0].evidence_source == "direct"
    assert "LOCAL FILE EVIDENCE BUNDLE" in bundle.prompt_context
    assert bundle.confidence in {"medium", "high"}


def test_evidence_bundle_adds_graph_neighbors(tmp_path, monkeypatch):
    from apps.shail.evidence_bundle import build_evidence_bundle

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Pricing.md").write_text("Dubai pricing plan", encoding="utf-8")
    (root / "Dubai_Revenue_Model.md").write_text("Revenue model notes", encoding="utf-8")
    _scan_and_graph(db_path, root)

    bundle = build_evidence_bundle("pricing", k=8, include_graph=True, max_graph_neighbors=5)

    paths = {Path(item.path).name for item in bundle.graph_expansions}
    assert "Dubai_Revenue_Model.md" in paths
    assert any(item.graph_relation for item in bundle.graph_expansions)


def test_evidence_bundle_respects_denied_and_deleted_paths(tmp_path, monkeypatch):
    from apps.shail.evidence_bundle import build_evidence_bundle
    from shail.memory import path_index

    db_path, root = _setup(tmp_path, monkeypatch)
    blocked = root / "private"
    blocked.mkdir()
    allowed = root / "allowed.md"
    denied = blocked / "secret.md"
    gone = root / "gone.md"
    allowed.write_text("pricing visible", encoding="utf-8")
    denied.write_text("pricing secret", encoding="utf-8")
    gone.write_text("pricing gone", encoding="utf-8")
    path_index.add_deny_path(db_path, str(blocked), reason="private")
    _scan_and_graph(db_path, root)
    gone.unlink()
    _scan_and_graph(db_path, root)

    bundle = build_evidence_bundle("pricing", k=8, include_graph=True)
    paths = {item.path for item in [*bundle.selected_files, *bundle.graph_expansions]}

    assert str(allowed) in paths
    assert str(denied) not in paths
    assert str(gone) not in paths


def test_evidence_bundle_suppresses_duplicate_content(tmp_path, monkeypatch):
    from apps.shail.evidence_bundle import build_evidence_bundle

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Pitch_A.md").write_text("duplicate pricing body", encoding="utf-8")
    (root / "Dubai_Pitch_B.md").write_text("duplicate pricing body", encoding="utf-8")
    _scan_and_graph(db_path, root)

    bundle = build_evidence_bundle("duplicate pricing", k=8, include_graph=True)

    assert bundle.suppressed_files
    assert any(item.is_duplicate_candidate for item in bundle.suppressed_files)
    assert any("Duplicate files" in warning for warning in bundle.warnings)


def test_evidence_bundle_marks_latest_version_candidate(tmp_path, monkeypatch):
    from apps.shail.evidence_bundle import build_evidence_bundle

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Pitch_v1.md").write_text("pricing old terms", encoding="utf-8")
    (root / "Dubai_Pitch_v2.md").write_text("pricing updated terms", encoding="utf-8")
    _scan_and_graph(db_path, root)

    bundle = build_evidence_bundle("pricing terms", k=8, include_graph=True)
    latest = [item for item in [*bundle.selected_files, *bundle.suppressed_files] if item.is_latest_candidate]

    assert latest
    assert any("v2" in Path(item.path).name for item in latest)
    assert any("Older related versions" in warning for warning in bundle.warnings)


def test_evidence_bundle_pointer_only_no_vector_ingest(tmp_path, monkeypatch):
    from apps.shail.evidence_bundle import build_evidence_bundle

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "memo.md").write_text("pricing memo", encoding="utf-8")
    _scan_and_graph(db_path, root)

    with mock.patch("shail.memory.rag.ingest") as mock_ingest:
        build_evidence_bundle("pricing", k=5, include_graph=True)
        assert not mock_ingest.called


def test_evidence_bundle_skips_oversized_graph_neighbor_with_warning(tmp_path, monkeypatch):
    from apps.shail.evidence_bundle import build_evidence_bundle

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Pricing.md").write_text("pricing source", encoding="utf-8")
    (root / "Dubai_Large_Context.md").write_text("large context " * 5000, encoding="utf-8")
    _scan_and_graph(db_path, root)

    bundle = build_evidence_bundle(
        "pricing",
        k=8,
        include_graph=True,
        max_graph_neighbors=5,
        read_cap_bytes=1024,
    )

    assert any("too_large" in warning for warning in bundle.warnings)


def test_local_rag_evidence_endpoint_shape(tmp_path, monkeypatch):
    auth_api = types.ModuleType("apps.shail.auth_api")
    auth_api.get_current_user = lambda: "test-user"
    monkeypatch.setitem(sys.modules, "apps.shail.auth_api", auth_api)

    from apps.shail.local_rag_api import LocalEvidenceRequest, local_rag_evidence

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Pricing.md").write_text("pricing endpoint evidence", encoding="utf-8")
    _scan_and_graph(db_path, root)

    res = asyncio.run(local_rag_evidence(
        LocalEvidenceRequest(query="pricing", k=5, include_graph=True),
        user_id="test-user",
    ))

    data = res.model_dump()
    assert data["query"] == "pricing"
    assert data["selected_files"]
    assert "prompt_context" in data
    assert "confidence" in data
