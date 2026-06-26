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


def _req(**overrides):
    base = dict(
        customId="mem-1",
        sourceApp="chatgpt",
        eventType="ai_conversation",
        sourceUrl="https://chatgpt.com/c/abc",
        conversationId="conv-1",
        title="Thread",
        timestamp="2026-05-08T00:00:00Z",
        userText="latest question",
        assistantText="User: first question\n\nAssistant: first answer\n\n---\n\nUser: second question\n\nAssistant: second answer",
        pageContent=None,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_capture_artifact_and_materialization_roundtrip(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "capture.db"
    monkeypatch.setattr(settings_mod, "_settings", _fake_settings(tmp_path, db))

    async def _fake_extract_blueprint(**kwargs):
        return {
            "summary": "conversation",
            "decisions": [],
            "questions_answered": [],
            "open_questions": [],
            "next_actions": [],
            "key_entities": [],
            "reasoning_chains": [],
            "failed_attempts": [],
            "facts": [],
            "metrics": [],
            "tables": [],
            "extensions": {},
        }

    embedded: list[dict] = []

    def _fake_ingest(*, records=None, paths=None):
        embedded.extend(records or [])
        return len(records or [])

    monkeypatch.setattr(blueprints, "extract_blueprint", _fake_extract_blueprint)
    monkeypatch.setattr(capture_store, "ingest", _fake_ingest)

    capture_store.init_capture_store()
    artifact = capture_store.create_capture_artifact(
        _req(),
        content="[chatgpt] Thread\n\nUser: latest question\n\nAssistant: ...",
        summary="summary",
    )
    materialization = asyncio.run(
        capture_store.create_materialization(
            artifact.artifact_id,
            user_id="u1",
            namespace="user_u1",
            promote=True,
        )
    )

    assert artifact.memory_id == "mem-1"
    assert materialization is not None
    assert materialization["memory_id"] == "mem-1"
    assert len(materialization["chunks"]) == 2
    assert materialization["chunks"][0]["chunk_key"] == "turn:0001"
    assert materialization["chunks"][1]["chunk_key"] == "turn:0002"
    assert any(rec["id"] == "mem-1" for rec in embedded)
    assert any(rec["id"] == "mem-1#turn:0001" for rec in embedded)

    active = capture_store.get_active_materialization("mem-1")
    assert active is not None
    assert active["materialization_id"] == materialization["materialization_id"]

    bp = blueprints.get_blueprint("mem-1")
    assert bp is not None
    assert bp["artifact_id"] == artifact.artifact_id
    assert bp["materialization_id"] == materialization["materialization_id"]


def test_replay_job_shadow_creates_materialization(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "capture.db"
    monkeypatch.setattr(settings_mod, "_settings", _fake_settings(tmp_path, db))

    async def _fake_extract_blueprint(**kwargs):
        return {
            "summary": "page",
            "decisions": [],
            "questions_answered": [],
            "open_questions": [],
            "next_actions": [],
            "key_entities": [],
            "reasoning_chains": [],
            "failed_attempts": [],
            "facts": [],
            "metrics": [],
            "tables": [],
            "extensions": {},
        }

    monkeypatch.setattr(blueprints, "extract_blueprint", _fake_extract_blueprint)
    monkeypatch.setattr(capture_store, "ingest", lambda **kwargs: 0)

    capture_store.init_capture_store()
    artifact = capture_store.create_capture_artifact(
        _req(
            customId="mem-2",
            eventType="page_visit",
            sourceApp="web",
            conversationId=None,
            sourceUrl="https://example.com/report",
            userText="",
            assistantText="",
            pageContent="Quarterly report text",
        ),
        content="[web] Report\n\nQuarterly report text",
        summary="report",
    )
    replay_job_id = capture_store.create_replay_job(
        mode="shadow",
        scope_type="artifact_id",
        scope_ref=artifact.artifact_id,
    )
    job = asyncio.run(
        capture_store.run_replay_job(
            replay_job_id,
            user_id="u1",
            namespace="user_u1",
        )
    )
    assert job is not None
    assert job["status"] == "ready"
    assert len(job["items"]) == 1
    assert job["items"][0]["status"] == "ready"
    mats = capture_store.list_materializations("mem-2")
    assert len(mats) == 1
    assert mats[0]["is_active"] is False


def test_replay_job_promote_activates_materialization(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "promote.db"
    monkeypatch.setattr(settings_mod, "_settings", _fake_settings(tmp_path, db))

    async def _fake_extract_blueprint(**kwargs):
        return None

    monkeypatch.setattr(blueprints, "extract_blueprint", _fake_extract_blueprint)
    monkeypatch.setattr(capture_store, "ingest", lambda **kwargs: 0)
    monkeypatch.setattr(capture_store, "_legacy_vector_ids", lambda _mid: [])
    monkeypatch.setattr(capture_store, "_delete_vector_ids", lambda _ids: None)

    capture_store.init_capture_store()
    artifact = capture_store.create_capture_artifact(_req(), content="x", summary="s")
    job_id = capture_store.create_replay_job(
        mode="promote",
        scope_type="artifact_id",
        scope_ref=artifact.artifact_id,
    )
    job = asyncio.run(capture_store.run_replay_job(job_id, user_id="u1", namespace="user_u1"))
    assert job is not None
    assert job["status"] == "promoted"
    assert job["items"][0]["status"] == "promoted"
    active = capture_store.get_active_materialization(artifact.memory_id)
    assert active is not None
    health = capture_store.capture_health(artifact.memory_id)
    assert health["active_materialization_id"] == active["materialization_id"]
    assert health["replay_jobs"]
    assert health["replay_jobs"][0]["replay_job_id"] == job_id


def test_legacy_backfill_creates_artifact_once(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "backfill.db"
    monkeypatch.setattr(settings_mod, "_settings", _fake_settings(tmp_path, db))
    capture_store.init_capture_store()

    artifact_id = capture_store.backfill_legacy_memory(
        memory_id="legacy-1",
        content="legacy text body",
        metadata={"sourceApp": "web", "sourceUrl": "https://example.com/x", "eventType": "page_visit"},
    )
    assert artifact_id is not None
    artifacts = capture_store.list_artifacts("legacy-1")
    assert len(artifacts) == 1
    assert artifacts[0]["completeness"] == "legacy_partial"
    # idempotent
    again = capture_store.backfill_legacy_memory(
        memory_id="legacy-1",
        content="legacy text body",
        metadata={"sourceApp": "web", "sourceUrl": "https://example.com/x"},
    )
    assert again == artifact_id
    assert len(capture_store.list_artifacts("legacy-1")) == 1


def test_replay_job_filters_by_since_and_limit(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "filter.db"
    monkeypatch.setattr(settings_mod, "_settings", _fake_settings(tmp_path, db))

    async def _fake_extract_blueprint(**kwargs):
        return None

    monkeypatch.setattr(blueprints, "extract_blueprint", _fake_extract_blueprint)
    monkeypatch.setattr(capture_store, "ingest", lambda **kwargs: 0)
    monkeypatch.setattr(capture_store, "_legacy_vector_ids", lambda _mid: [])
    monkeypatch.setattr(capture_store, "_delete_vector_ids", lambda _ids: None)

    capture_store.init_capture_store()
    a1 = capture_store.create_capture_artifact(
        _req(customId="m-a", conversationId="cv-a", sourceUrl="https://x.com/a"),
        content="x", summary="s",
    )
    a2 = capture_store.create_capture_artifact(
        _req(customId="m-b", conversationId="cv-b", sourceUrl="https://x.com/b"),
        content="x", summary="s",
    )
    assert a1.artifact_kind == a2.artifact_kind == "normalized_text_capture"
    job_id = capture_store.create_replay_job(
        mode="shadow",
        scope_type="artifact_kind",
        scope_ref="normalized_text_capture",
        options={"limit": 1},
    )
    job = asyncio.run(capture_store.run_replay_job(job_id, user_id="u1", namespace="user_u1"))
    assert job is not None
    assert len(job["items"]) == 1
