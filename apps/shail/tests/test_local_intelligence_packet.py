from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest import mock


def _setup(tmp_path: Path, monkeypatch):
    from apps.shail.settings import get_settings

    db_path = str(tmp_path / "local_intelligence.sqlite3")
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
    monkeypatch.setattr(settings, "shail_local_intelligence_llm", False, raising=False)
    return db_path, root


def _build_all(db_path: str, root: Path):
    from apps.shail import local_graph, local_semantic_reasoning, local_semantics
    from shail.memory import path_index

    path_index.scan(db_path, roots=[str(root)])
    local_semantics.build_semantics(path_db=db_path, semantics_db=db_path, limit=500, force=True)
    local_semantic_reasoning.build_reasoning(semantics_db=db_path, limit=500)
    local_graph.build_local_file_graph(path_db=db_path, graph_db=db_path, env_roots=[str(root)], limit=500)


def test_packet_includes_grounded_answer_and_canonical_fact(tmp_path, monkeypatch):
    from apps.shail import local_intelligence

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Revenue_v1.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    (root / "Dubai_Revenue_v2.md").write_text("Dubai Revenue is $2M.", encoding="utf-8")
    _build_all(db_path, root)

    packet = local_intelligence.build_intelligence_packet("What do we know about Dubai Revenue?", user_id="u", k=8)

    assert packet.packet_id.startswith("intel_")
    assert packet.answer
    assert packet.evidence_bundle_id
    assert packet.canonical_facts
    assert any(fact["status"] in {"accepted", "conflicted"} for fact in packet.canonical_facts)
    assert packet.supporting_evidence
    assert packet.source_map


def test_packet_surfaces_conflicts_and_recommended_actions(tmp_path, monkeypatch):
    from apps.shail import local_intelligence

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Pricing_v1.md").write_text("Dubai Pricing is $10K.", encoding="utf-8")
    (root / "Dubai_Pricing_v2.md").write_text("Dubai Pricing is $20K.", encoding="utf-8")
    _build_all(db_path, root)

    packet = local_intelligence.build_intelligence_packet("Dubai Pricing", user_id="u", k=8)

    assert packet.conflicts
    assert any("competing" in action.lower() for action in packet.recommended_next_actions)
    assert any(fact["status"] in {"conflicted", "unresolved"} for fact in packet.canonical_facts)


def test_packet_creates_gap_report_for_missing_evidence(tmp_path, monkeypatch):
    from apps.shail import local_intelligence

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "notes.md").write_text("Alpha launch notes only.", encoding="utf-8")
    _build_all(db_path, root)

    packet = local_intelligence.build_intelligence_packet("Mars acquisition revenue", user_id="u", k=5)

    assert packet.confidence in {"insufficient", "low"}
    assert packet.gaps
    assert packet.follow_up_questions


def test_packet_excludes_denied_and_deleted_files(tmp_path, monkeypatch):
    from apps.shail import local_intelligence
    from shail.memory import path_index

    db_path, root = _setup(tmp_path, monkeypatch)
    blocked = root / "private"
    blocked.mkdir()
    allowed = root / "public.md"
    denied = blocked / "secret.md"
    gone = root / "gone.md"
    allowed.write_text("Dubai Revenue is $3M.", encoding="utf-8")
    denied.write_text("Dubai Revenue is $99M.", encoding="utf-8")
    gone.write_text("Dubai Revenue is $5M.", encoding="utf-8")
    path_index.add_deny_path(db_path, str(blocked), reason="private")
    _build_all(db_path, root)
    gone.unlink()
    path_index.scan(db_path, roots=[str(root)])

    packet = local_intelligence.build_intelligence_packet("Dubai Revenue", user_id="u", k=8)
    paths = {str(item.get("path") or "") for item in [*packet.source_map, *packet.supporting_evidence]}
    answer_blob = packet.answer + "\n" + "\n".join(str(f.get("value") or "") for f in packet.canonical_facts)

    assert str(allowed) in paths
    assert str(denied) not in paths
    assert str(gone) not in paths
    assert "$99M" not in answer_blob
    assert "$5M" not in answer_blob


def test_packet_source_map_suppresses_duplicates_and_marks_latest(tmp_path, monkeypatch):
    from apps.shail import local_intelligence

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "Dubai_Pitch_v1.md").write_text("Dubai Pricing is $10K.", encoding="utf-8")
    (root / "Dubai_Pitch_v2.md").write_text("Dubai Pricing is $20K.", encoding="utf-8")
    (root / "Dubai_Pitch_copy.md").write_text("Dubai Pricing is $20K.", encoding="utf-8")
    _build_all(db_path, root)

    packet = local_intelligence.build_intelligence_packet("Dubai Pricing", user_id="u", k=8)

    assert any(item.get("suppressed") for item in packet.source_map)
    assert any(item.get("is_latest_candidate") for item in packet.source_map)


def test_packet_pointer_only_no_vector_ingest(tmp_path, monkeypatch):
    from apps.shail import local_intelligence

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "memo.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    _build_all(db_path, root)

    with mock.patch("shail.memory.rag.ingest") as mock_ingest:
        local_intelligence.build_intelligence_packet("Dubai Revenue", user_id="u", k=5)
        assert not mock_ingest.called


def test_intelligence_packet_api_and_storage_shape(tmp_path, monkeypatch):
    auth_api = types.ModuleType("apps.shail.auth_api")
    auth_api.get_current_user = lambda: "test-user"
    monkeypatch.setitem(sys.modules, "apps.shail.auth_api", auth_api)

    from apps.shail.local_rag_api import (
        LocalIntelligencePacketRequest,
        local_rag_intelligence_facts_search,
        local_rag_intelligence_packet,
        local_rag_intelligence_packet_get,
        local_rag_intelligence_status,
    )

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "api.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    _build_all(db_path, root)

    res = asyncio.run(local_rag_intelligence_packet(
        LocalIntelligencePacketRequest(query="Dubai Revenue", k=5, include_graph=True, include_answer=True),
        user_id="test-user",
    ))
    status = asyncio.run(local_rag_intelligence_status(user_id="test-user"))
    facts = asyncio.run(local_rag_intelligence_facts_search(q="Dubai", limit=20, user_id="test-user"))
    fetched = asyncio.run(local_rag_intelligence_packet_get(res.packet_id, user_id="test-user"))

    assert res.packet_id
    assert status["packets"] == 1
    assert facts["items"]
    assert fetched.packet_id == res.packet_id


def test_ollama_unavailable_does_not_fail_packet(tmp_path, monkeypatch):
    from apps.shail import local_intelligence
    from apps.shail.settings import get_settings

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "memo.md").write_text("Dubai Revenue is $1M.", encoding="utf-8")
    _build_all(db_path, root)
    monkeypatch.setattr(get_settings(), "shail_local_intelligence_llm", True, raising=False)
    monkeypatch.setattr(get_settings(), "ollama_base_url", "http://127.0.0.1:9", raising=False)

    packet = local_intelligence.build_intelligence_packet("Dubai Revenue", user_id="u", k=5)

    assert packet.answer
    assert any("ollama" in warning.lower() for warning in packet.warnings)
