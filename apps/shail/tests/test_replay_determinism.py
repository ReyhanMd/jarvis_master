from __future__ import annotations

import asyncio
import types
from pathlib import Path

import apps.shail.settings as settings_mod
from apps.shail import blueprints, capture_store


def _fake_settings(tmp_path: Path, db: Path):
    return settings_mod.Settings(
        sqlite_path=str(db),
        capture_artifact_dir=str(tmp_path / "capture_artifacts"),
        capture_bundle_version="capture-v1.0.0",
        shail_exact_index_write=False,
    )


async def _empty_blueprint(**_kwargs):
    return None


def _patch(monkeypatch, tmp_path: Path, db: Path):
    monkeypatch.setattr(settings_mod, "_settings", _fake_settings(tmp_path, db))
    monkeypatch.setattr(blueprints, "extract_blueprint", _empty_blueprint)
    monkeypatch.setattr(capture_store, "ingest", lambda **_kw: 0)
    monkeypatch.setattr(capture_store, "_legacy_vector_ids", lambda _mid: [])
    monkeypatch.setattr(capture_store, "_delete_vector_ids", lambda _ids: None)


def _make_req(**overrides):
    base = dict(
        customId="mem-det-1",
        sourceApp="chatgpt",
        eventType="ai_conversation",
        sourceUrl="https://chatgpt.com/c/det",
        conversationId="conv-det",
        title="Det",
        timestamp="2026-05-08T00:00:00Z",
        userText="q",
        assistantText="User: a\n\nAssistant: b\n\n---\n\nUser: c\n\nAssistant: d",
        pageContent=None,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _chunk_signature(materialization: dict) -> list[tuple]:
    return [
        (
            chunk["chunk_key"],
            chunk["chunk_type"],
            chunk["ordinal"],
            chunk["chunk_hash"],
            chunk["vector_id"],
        )
        for chunk in materialization["chunks"]
    ]


def test_transcript_replay_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "det.db"
    _patch(monkeypatch, tmp_path, db)
    capture_store.init_capture_store()
    artifact = capture_store.create_capture_artifact(_make_req(), content="x", summary="s")
    a = asyncio.run(capture_store.create_materialization(artifact.artifact_id, user_id="u", namespace="user_u"))
    b = asyncio.run(capture_store.create_materialization(artifact.artifact_id, user_id="u", namespace="user_u"))
    assert a is not None and b is not None
    assert a["memory_id"] == b["memory_id"] == artifact.memory_id
    assert _chunk_signature(a) == _chunk_signature(b)


def test_promote_then_rollback_restores_vector_ids(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "rb.db"
    _patch(monkeypatch, tmp_path, db)
    capture_store.init_capture_store()
    artifact = capture_store.create_capture_artifact(_make_req(), content="x", summary="s")
    first = asyncio.run(
        capture_store.create_materialization(
            artifact.artifact_id, user_id="u", namespace="user_u", promote=True,
        )
    )
    second = asyncio.run(
        capture_store.create_materialization(
            artifact.artifact_id, user_id="u", namespace="user_u",
            options={"replay": "second"}, promote=True,
        )
    )
    assert first and second
    assert first["materialization_id"] != second["materialization_id"]
    rolled = capture_store.promote_materialization(
        first["materialization_id"], namespace="user_u", user_id="u",
    )
    assert rolled is not None
    assert rolled["is_active"] == 1 or rolled["is_active"] is True
    active = capture_store.get_active_materialization(artifact.memory_id)
    assert active and active["materialization_id"] == first["materialization_id"]
    assert _chunk_signature(active) == _chunk_signature(first)


def test_github_diff_chunking_and_metadata(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "gh.db"
    _patch(monkeypatch, tmp_path, db)
    capture_store.init_capture_store()
    diff = {
        "owner": "acme",
        "repo": "svc",
        "pr_number": 42,
        "base_sha": "aaa",
        "head_sha": "bbb",
        "files": [
            {
                "path": "src/app.ts",
                "hunks": [
                    {"header": "@@ -1,2 +1,3 @@", "lines": [
                        {"kind": " ", "text": "ctx"},
                        {"kind": "+", "text": "added"},
                    ]},
                ],
            },
        ],
    }
    req = _make_req(
        customId="pr-mem",
        eventType="document",
        sourceApp="web",
        sourceUrl="https://github.com/acme/svc/pull/42/files",
        conversationId=None,
        userText="",
        assistantText="",
        pageContent="diff",
    )
    artifact = capture_store.create_capture_artifact(
        req,
        content="diff",
        summary="pr",
        raw_payload={"github_diff": diff},
    )
    mat = asyncio.run(
        capture_store.create_materialization(artifact.artifact_id, user_id="u", namespace="user_u")
    )
    assert mat is not None
    keys = [c["chunk_key"] for c in mat["chunks"]]
    assert "file:src/app.ts:hunk:001" in keys
    hunk = next(c for c in mat["chunks"] if c["chunk_key"] == "file:src/app.ts:hunk:001")
    assert hunk["chunk_type"] == "code_diff_hunk"
    assert hunk["metadata"]["repo"] == "svc"
    assert hunk["metadata"]["pr_number"] == 42


def test_html_table_chunking(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "tbl.db"
    _patch(monkeypatch, tmp_path, db)
    capture_store.init_capture_store()
    req = _make_req(
        customId="tbl-mem",
        eventType="html_page",
        sourceApp="web",
        sourceUrl="https://example.com/dash",
        conversationId=None,
        userText="",
        assistantText="",
        pageContent="page",
    )
    artifact = capture_store.create_capture_artifact(
        req,
        content="page",
        summary="dash",
        raw_payload={"html_tables": [{
            "title": "Sales Q1",
            "columns": ["region", "revenue"],
            "rows": [["NA", "100"], ["EU", "80"]],
            "column_types": ["text", "numeric"],
            "source_locator": "table#sales",
        }]},
    )
    mat = asyncio.run(
        capture_store.create_materialization(artifact.artifact_id, user_id="u", namespace="user_u")
    )
    assert mat is not None
    assert mat["chunks"][0]["chunk_type"] == "table"
    assert mat["chunks"][0]["metadata"]["title"] == "Sales Q1"
    assert mat["chunks"][0]["never_split"] is True


def test_pdf_block_chunking(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "pdf.db"
    _patch(monkeypatch, tmp_path, db)
    capture_store.init_capture_store()
    req = _make_req(
        customId="pdf-mem",
        eventType="pdf_doc",
        sourceApp="web",
        sourceUrl="https://example.com/paper.pdf",
        conversationId=None,
        userText="",
        assistantText="",
        pageContent="paragraph one\n\nparagraph two",
    )
    artifact = capture_store.create_capture_artifact(
        req,
        content="paragraph one\n\nparagraph two",
        summary="paper",
    )
    mat = asyncio.run(
        capture_store.create_materialization(artifact.artifact_id, user_id="u", namespace="user_u")
    )
    assert mat is not None
    types_ = {c["chunk_type"] for c in mat["chunks"]}
    assert types_ == {"pdf_block"}
    assert len(mat["chunks"]) == 2
