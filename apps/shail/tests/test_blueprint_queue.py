"""Plan B5 + B6 + B7 — raw_transcripts, blueprint queue, quality score,
auto-redact gate.
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "/Users/reyhan/shail workspace /shail_master/jarvis_master")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def user_id(isolated_db):
    from apps.shail.auth_store import init_auth_db, create_user
    init_auth_db()
    u = create_user("bp_test@x.com", "password123")
    return u["id"]


# ── raw_transcripts (B5) ─────────────────────────────────────────────────────

class TestRawTranscripts:
    def test_save_and_get(self, isolated_db):
        from apps.shail import raw_transcripts as rt
        rt.save(
            memory_id="m1", user_id="u1", namespace="user_u1",
            content_type="ai_conversation", content="hello world",
            metadata={"sourceApp": "chatgpt"},
        )
        got = rt.get("m1")
        assert got is not None
        assert got["content"] == "hello world"
        assert got["metadata"]["sourceApp"] == "chatgpt"
        assert got["embedded"] == 0
        assert got["blueprinted"] == 0

    def test_save_upserts(self, isolated_db):
        from apps.shail import raw_transcripts as rt
        rt.save(memory_id="m1", user_id="u1", namespace="ns",
                content_type="x", content="v1")
        rt.save(memory_id="m1", user_id="u1", namespace="ns",
                content_type="x", content="v2_updated")
        assert rt.get("m1")["content"] == "v2_updated"

    def test_mark_embedded_and_blueprinted(self, isolated_db):
        from apps.shail import raw_transcripts as rt
        rt.save(memory_id="m1", user_id="u1", namespace="ns",
                content_type="x", content="hello")
        rt.mark_embedded("m1", True)
        rt.mark_blueprinted("m1", True)
        got = rt.get("m1")
        assert got["embedded"] == 1
        assert got["blueprinted"] == 1

    def test_list_unembedded_filters(self, isolated_db):
        from apps.shail import raw_transcripts as rt
        rt.save(memory_id="a", user_id="u", namespace="n", content_type="x", content="A")
        rt.save(memory_id="b", user_id="u", namespace="n", content_type="x", content="B")
        rt.mark_embedded("a", True)
        ids = {r["memory_id"] for r in rt.list_unembedded()}
        assert "b" in ids and "a" not in ids


# ── Quality scoring (B7) ─────────────────────────────────────────────────────

class TestQualityScore:
    def test_empty_blueprint_zero(self):
        from apps.shail.blueprint_queue import compute_quality_score
        assert compute_quality_score(None) == 0.0
        assert compute_quality_score({}) == 0.0

    def test_single_field_low_score(self):
        from apps.shail.blueprint_queue import compute_quality_score
        score = compute_quality_score({"decisions": ["pick rust"]})
        assert 0.0 < score < 0.3

    def test_multi_field_above_threshold(self):
        from apps.shail.blueprint_queue import compute_quality_score
        bp = {
            "decisions": ["a", "b"],
            "key_entities": ["x"],
            "facts": ["f"],
            "next_actions": ["do"],
        }
        # 0.20 + 0.20 + 0.15 + 0.15 = 0.70 — well above 0.4 default
        score = compute_quality_score(bp)
        assert score >= 0.4

    def test_score_clamped_at_one(self):
        from apps.shail.blueprint_queue import compute_quality_score
        bp = {k: ["x"] for k in [
            "decisions", "key_entities", "facts", "next_actions",
            "questions_answered", "open_questions", "metrics", "tables",
        ]}
        assert compute_quality_score(bp) <= 1.0


# ── Queue CRUD + state machine (B6) ──────────────────────────────────────────

class TestBlueprintQueueCRUD:
    def test_enqueue_creates_pending(self, isolated_db):
        from apps.shail.blueprint_queue import enqueue, get_job
        job_id = enqueue(
            memory_id="mem_x", session_id="sess_x",
            user_id="u", content_type="chat_session",
        )
        job = get_job(job_id)
        assert job is not None
        assert job["state"] == "pending"
        assert job["attempts"] == 0
        assert job["memory_id"] == "mem_x"

    def test_enqueue_dedupes_on_memory_id(self, isolated_db):
        """Two enqueues for the same memory_id while no job is done → reuse."""
        from apps.shail.blueprint_queue import enqueue
        a = enqueue(memory_id="m", session_id="s", user_id="u",
                    content_type="ai_conversation")
        b = enqueue(memory_id="m", session_id="s", user_id="u",
                    content_type="ai_conversation")
        assert a == b

    def test_list_jobs_filters_by_state(self, isolated_db):
        from apps.shail.blueprint_queue import enqueue, list_jobs
        enqueue(memory_id="a", session_id=None, user_id="u", content_type="x")
        pending = list_jobs(state="pending")
        assert any(j["memory_id"] == "a" for j in pending)


# ── Worker job processing ────────────────────────────────────────────────────

class TestQueueWorker:
    def test_process_capture_job_marks_done(self, isolated_db, monkeypatch):
        """End-to-end: enqueue a capture job, mock blueprint LLM, run worker
        tick once. Job should land in 'done' with quality score populated."""
        from apps.shail.blueprint_queue import enqueue, _process_job, get_job
        from apps.shail import raw_transcripts as rt

        # Seed the raw transcript the worker will read
        rt.save(memory_id="cap_1", user_id="u_w", namespace="user_u_w",
                content_type="ai_conversation", content="user asked X; assistant said Y")

        async def _fake_blueprint(memory_id, **kwargs):
            return {
                "decisions": ["use rust"],
                "key_entities": ["rust", "ownership"],
                "facts": ["systems language"],
                "next_actions": ["write hello-world"],
            }
        monkeypatch.setattr("apps.shail.blueprints.generate_blueprint", _fake_blueprint)
        monkeypatch.setattr(
            "apps.shail.blueprint_queue._ollama_alive",
            AsyncMock(return_value=True),
        )

        job_id = enqueue(
            memory_id="cap_1", session_id=None,
            user_id="u_w", content_type="ai_conversation",
        )
        job = get_job(job_id)
        _run(_process_job(job))
        done = get_job(job_id)
        assert done["state"] == "done"
        assert done["quality_score"] is not None
        assert done["quality_score"] >= 0.4

    def test_process_failure_increments_attempts(self, isolated_db, monkeypatch):
        from apps.shail.blueprint_queue import enqueue, _process_job, get_job
        from apps.shail import raw_transcripts as rt

        rt.save(memory_id="cap_fail", user_id="u_w", namespace="user_u_w",
                content_type="x", content="hello")

        async def _boom(*a, **k):
            raise RuntimeError("simulated LLM failure")
        monkeypatch.setattr("apps.shail.blueprints.generate_blueprint", _boom)

        job_id = enqueue(memory_id="cap_fail", session_id=None,
                         user_id="u_w", content_type="x")
        _run(_process_job(get_job(job_id)))
        after = get_job(job_id)
        assert after["attempts"] == 1
        assert after["state"] == "pending"  # not yet exhausted, scheduled for retry
        assert "simulated LLM failure" in (after["last_error"] or "")

    def test_max_attempts_marks_failed(self, isolated_db, monkeypatch):
        from apps.shail.blueprint_queue import enqueue, _process_job, get_job
        from apps.shail import raw_transcripts as rt

        rt.save(memory_id="cap_dead", user_id="u_w", namespace="user_u_w",
                content_type="x", content="hello")

        async def _boom(*a, **k):
            raise RuntimeError("always fails")
        monkeypatch.setattr("apps.shail.blueprints.generate_blueprint", _boom)

        job_id = enqueue(memory_id="cap_dead", session_id=None,
                         user_id="u_w", content_type="x", max_attempts=2)
        for _ in range(2):
            _run(_process_job(get_job(job_id)))
        final = get_job(job_id)
        assert final["state"] == "failed"
        assert final["attempts"] == 2


# ── Auto-redact gate (B7) ────────────────────────────────────────────────────

class TestAutoRedact:
    def test_threshold_gate_blocks_low_quality(self, isolated_db, monkeypatch):
        """Score below threshold → no redaction even when flag is on."""
        from apps.shail.blueprint_queue import _try_auto_redact

        called = []
        def _track(session_id, user_id):
            called.append(session_id)
            return {"ok": True, "messages_deleted": 0}
        monkeypatch.setattr("apps.shail.session_backfill.redact_session_transcript", _track)
        monkeypatch.setattr(
            "apps.shail.session_backfill._get_session_auto_redact_flag",
            lambda sid: True,
        )

        _run(_try_auto_redact({"session_id": "s1", "user_id": "u"}, score=0.1))
        assert called == [], "low-quality score should not trigger redact"

    def test_flag_off_blocks_redact(self, isolated_db, monkeypatch):
        from apps.shail.blueprint_queue import _try_auto_redact

        called = []
        def _track(session_id, user_id):
            called.append(session_id)
            return {"ok": True}
        monkeypatch.setattr("apps.shail.session_backfill.redact_session_transcript", _track)
        monkeypatch.setattr(
            "apps.shail.session_backfill._get_session_auto_redact_flag",
            lambda sid: False,
        )

        _run(_try_auto_redact({"session_id": "s1", "user_id": "u"}, score=0.9))
        assert called == [], "auto_redact flag off should block redact"

    def test_high_quality_with_flag_triggers_redact(self, isolated_db, monkeypatch):
        from apps.shail.blueprint_queue import _try_auto_redact

        called = []
        def _track(session_id, user_id):
            called.append((session_id, user_id))
            return {"ok": True, "messages_deleted": 7}
        monkeypatch.setattr("apps.shail.session_backfill.redact_session_transcript", _track)
        monkeypatch.setattr(
            "apps.shail.session_backfill._get_session_auto_redact_flag",
            lambda sid: True,
        )

        _run(_try_auto_redact({"session_id": "s_high", "user_id": "u"}, score=0.85))
        assert called == [("s_high", "u")]


# ── Per-session flag CRUD ────────────────────────────────────────────────────

class TestSessionAutoRedactFlag:
    def test_set_and_get(self, isolated_db, user_id):
        from apps.shail import session_backfill, chat_store
        from apps.shail.blueprints import init_blueprint_db
        init_blueprint_db()
        session_backfill.ensure_phase_c_schema()
        sess = chat_store.create_session(user_id, title="t")
        sid = sess["id"]
        # Default: off
        assert session_backfill._get_session_auto_redact_flag(sid) is False
        # Turn on
        ok = session_backfill.set_session_auto_redact(sid, user_id, True)
        assert ok
        assert session_backfill._get_session_auto_redact_flag(sid) is True
        # Turn off
        session_backfill.set_session_auto_redact(sid, user_id, False)
        assert session_backfill._get_session_auto_redact_flag(sid) is False
