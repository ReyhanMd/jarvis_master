from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest import mock


def _setup(tmp_path: Path, monkeypatch):
    from apps.shail.settings import get_settings

    db_path = str(tmp_path / "grounded_answer.sqlite3")
    root = tmp_path / "approved"
    root.mkdir()
    settings = get_settings()
    monkeypatch.setattr(settings, "path_index_db", db_path, raising=False)
    monkeypatch.setattr(settings, "sqlite_path", db_path, raising=False)
    monkeypatch.setattr(settings, "scan_roots", [str(root)], raising=False)
    monkeypatch.setattr(settings, "shail_local_files_k", 5, raising=False)
    monkeypatch.setattr(settings, "shail_local_files_snippet_chars", 900, raising=False)
    monkeypatch.setattr(settings, "shail_local_files_read_cap_bytes", 100_000, raising=False)
    monkeypatch.setattr(settings, "shail_local_files_in_chat", True, raising=False)
    monkeypatch.setattr(settings, "shail_local_semantic_llm", False, raising=False)
    return db_path, root


def _build_all(db_path: str, root: Path):
    from apps.shail import local_graph, local_semantic_reasoning, local_semantics
    from shail.memory import path_index

    path_index.scan(db_path, roots=[str(root)])
    local_semantics.build_semantics(path_db=db_path, semantics_db=db_path, limit=500, force=True)
    local_semantic_reasoning.build_reasoning(semantics_db=db_path, limit=500)
    local_graph.build_local_file_graph(path_db=db_path, graph_db=db_path, env_roots=[str(root)], limit=500)


def test_grounded_answer_uses_preferred_resolved_fact(tmp_path, monkeypatch):
    from apps.shail.grounded_answer import build_grounded_answer

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Revenue_v1.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    (root / "Dubai_Revenue_v2.md").write_text("Dubai Revenue is $2M.", encoding="utf-8")
    _build_all(db_path, root)

    answer = build_grounded_answer("What is Dubai Revenue?", user_id="u", k=8, include_graph=True)

    assert answer.confidence in {"medium", "high"}
    assert "$2M" in answer.answer
    assert answer.semantic_resolutions
    assert answer.semantic_conflicts
    assert any(c.get("answer_confidence") == answer.confidence for c in answer.citations)
    assert any(c.get("evidence_bundle_id") == answer.evidence_bundle_id for c in answer.citations)


def test_grounded_answer_warns_on_conflict(tmp_path, monkeypatch):
    from apps.shail.grounded_answer import build_grounded_answer

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Pricing_v1.md").write_text("Dubai Pricing is $10K.", encoding="utf-8")
    (root / "Dubai_Pricing_v2.md").write_text("Dubai Pricing is $20K.", encoding="utf-8")
    _build_all(db_path, root)

    answer = build_grounded_answer("Dubai Pricing", user_id="u", k=8, include_graph=True)

    assert answer.semantic_conflicts
    assert any("conflicting values" in warning.lower() for warning in answer.warnings)
    assert all("answer_confidence" in citation for citation in answer.citations)


def test_grounded_answer_missing_evidence_is_insufficient(tmp_path, monkeypatch):
    from apps.shail.grounded_answer import build_grounded_answer

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "notes.md").write_text("Alpha launch notes only.", encoding="utf-8")
    _build_all(db_path, root)

    answer = build_grounded_answer("Mars acquisition revenue", user_id="u", k=5, include_graph=True)

    assert answer.confidence in {"insufficient", "low"}
    if answer.confidence == "insufficient":
        assert "without guessing" in answer.answer
    assert answer.follow_up_questions


def test_grounded_answer_ambiguous_query_asks_followup(tmp_path, monkeypatch):
    from apps.shail.grounded_answer import build_grounded_answer

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "revenue.md").write_text("Dubai Revenue is $4M.", encoding="utf-8")
    _build_all(db_path, root)

    answer = build_grounded_answer("latest", user_id="u", k=5, include_graph=True)

    assert answer.follow_up_questions
    assert answer.confidence in {"low", "insufficient"}


def test_grounded_answer_denied_folder_exclusion(tmp_path, monkeypatch):
    from apps.shail.grounded_answer import build_grounded_answer
    from shail.memory import path_index

    db_path, root = _setup(tmp_path, monkeypatch)
    blocked = root / "private"
    blocked.mkdir()
    allowed = root / "public.md"
    denied = blocked / "secret.md"
    allowed.write_text("Dubai Revenue is $3M.", encoding="utf-8")
    denied.write_text("Dubai Revenue is $99M.", encoding="utf-8")
    path_index.add_deny_path(db_path, str(blocked), reason="private")
    _build_all(db_path, root)

    answer = build_grounded_answer("Dubai Revenue", user_id="u", k=8, include_graph=True)
    paths = {str(item.get("path") or "") for item in answer.evidence_summary}

    assert str(allowed) in paths
    assert str(denied) not in paths
    assert "$99M" not in answer.answer


def test_grounded_answer_respects_local_files_disabled(tmp_path, monkeypatch):
    from apps.shail.grounded_answer import build_grounded_answer
    from apps.shail.settings import get_settings

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "revenue.md").write_text("Dubai Revenue is $4M.", encoding="utf-8")
    _build_all(db_path, root)
    monkeypatch.setattr(get_settings(), "shail_local_files_in_chat", False, raising=False)

    answer = build_grounded_answer("Dubai Revenue", user_id="u", k=5, include_graph=True)

    assert answer.confidence == "insufficient"
    assert answer.citations == []
    assert any("disabled" in warning.lower() for warning in answer.warnings)


def test_grounded_answer_pointer_only_no_vector_ingest(tmp_path, monkeypatch):
    from apps.shail.grounded_answer import build_grounded_answer

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "memo.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    _build_all(db_path, root)

    with mock.patch("shail.memory.rag.ingest") as mock_ingest:
        build_grounded_answer("Dubai Revenue", user_id="u", k=5, include_graph=True)
        assert not mock_ingest.called


def test_local_rag_answer_endpoint_shape(tmp_path, monkeypatch):
    auth_api = types.ModuleType("apps.shail.auth_api")
    auth_api.get_current_user = lambda: "test-user"
    monkeypatch.setitem(sys.modules, "apps.shail.auth_api", auth_api)

    from apps.shail.local_rag_api import LocalAnswerRequest, local_rag_answer

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "api.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    _build_all(db_path, root)

    res = asyncio.run(local_rag_answer(
        LocalAnswerRequest(query="Dubai Revenue", k=5, include_graph=True),
        user_id="test-user",
    ))
    data = res.model_dump()

    assert data["query"] == "Dubai Revenue"
    assert data["evidence_bundle_id"]
    assert data["confidence"] in {"high", "medium", "low", "insufficient"}
    assert "citations" in data
    assert "quality_signals" in data
