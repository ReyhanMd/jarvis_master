"""Phase C — session backfill, timeline, retention, continue-capture gating."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def _run(coro):
    """Run a coroutine to completion. Avoids pytest-asyncio dep."""
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------------------
# DB bootstrap fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def chat_db(isolated_db: Path, monkeypatch):
    """Initialize auth + blueprint + phase-c schemas on an isolated DB."""
    from apps.shail.auth_store import init_auth_db
    from apps.shail.blueprints import init_blueprint_db
    from apps.shail.session_backfill import ensure_phase_c_schema

    init_auth_db()
    init_blueprint_db()
    ensure_phase_c_schema()

    # Create a fake user so chat_sessions FK is satisfied.
    with sqlite3.connect(str(isolated_db)) as con:
        con.execute(
            "INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("u_test", "test@example.com", "fake_hash", "2026-01-01T00:00:00+00:00"),
        )
    return isolated_db


@pytest.fixture
def seeded_session(chat_db: Path):
    """Create a session with 3 turns of Q+A."""
    from apps.shail import chat_store
    sess = chat_store.create_session("u_test", title="ML discussion")
    sid = sess["id"]
    chat_store.append_message(sid, "u_test", "user", "What is gradient descent?")
    chat_store.append_message(sid, "u_test", "assistant",
                              "Iterative optimization that follows the negative gradient of a loss function.")
    chat_store.append_message(sid, "u_test", "user", "Why use Adam over SGD?")
    chat_store.append_message(sid, "u_test", "assistant",
                              "Adam combines momentum + adaptive learning rates; faster convergence on noisy gradients.")
    chat_store.append_message(sid, "u_test", "user", "What about RMSProp?")
    chat_store.append_message(sid, "u_test", "assistant",
                              "RMSProp scales the learning rate per parameter by recent gradient magnitude.")
    return sid


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

class TestPhaseCSchema:
    def test_columns_added_idempotently(self, chat_db: Path) -> None:
        from apps.shail.session_backfill import ensure_phase_c_schema
        # Call twice — must not raise
        ensure_phase_c_schema()
        ensure_phase_c_schema()
        with sqlite3.connect(str(chat_db)) as con:
            cols = {r[1] for r in con.execute("PRAGMA table_info(chat_sessions)")}
        assert "retention_policy" in cols
        assert "capture_enabled" in cols
        assert "blueprint_memory_id" in cols
        assert "backfilled_at" in cols

    def test_capture_default_enabled(self, chat_db: Path, seeded_session: str) -> None:
        from apps.shail.session_backfill import is_capture_enabled
        assert is_capture_enabled(seeded_session) is True


# ---------------------------------------------------------------------------
# Backfill driver
# ---------------------------------------------------------------------------

class TestBackfill:
    def test_backfill_indexes_all_turns(self, chat_db: Path, seeded_session: str, monkeypatch) -> None:
        """Each Q+A pair should be re-indexed exactly once.

        Sprint 1: backfill batches into a single ingest() call, not per-pair
        _index_past_chat_turn() calls. Mock ingest and verify records.
        """
        from apps.shail import session_backfill

        ingest_calls: list[list[dict]] = []
        def _fake_ingest(records=None, **kwargs):
            ingest_calls.append(list(records or []))
            return len(records or [])  # pretend all embedded successfully
        monkeypatch.setattr("shail.memory.rag.ingest", _fake_ingest)
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )

        summary = _run(session_backfill.backfill_session(seeded_session, "u_test"))
        assert summary.turns_seen == 6
        assert summary.turns_indexed == 3
        assert summary.turns_skipped == 0
        assert summary.degraded_mode is False
        # Sprint 1: one batched ingest() call, not three
        assert len(ingest_calls) == 1
        assert len(ingest_calls[0]) == 3
        assert all(r["metadata"]["session_id"] == seeded_session for r in ingest_calls[0])
        assert all(r["metadata"]["session_title"] == "ML discussion" for r in ingest_calls[0])

    def test_backfill_idempotent(self, chat_db: Path, seeded_session: str, monkeypatch) -> None:
        from apps.shail import session_backfill

        ingest_calls = {"n": 0, "total_records": 0}
        def _fake_ingest(records=None, **kwargs):
            ingest_calls["n"] += 1
            ingest_calls["total_records"] += len(records or [])
            return len(records or [])
        monkeypatch.setattr("shail.memory.rag.ingest", _fake_ingest)
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )

        s1 = _run(session_backfill.backfill_session(seeded_session, "u_test", include_blueprint=False))
        s2 = _run(session_backfill.backfill_session(seeded_session, "u_test", include_blueprint=False))
        assert s1.turns_indexed == s2.turns_indexed == 3
        # Sprint 1: 2 backfills × 1 batched ingest = 2 calls (was 6 per-pair)
        assert ingest_calls["n"] == 2
        assert ingest_calls["total_records"] == 6

    def test_backfill_session_not_found(self, chat_db: Path, monkeypatch) -> None:
        from apps.shail import session_backfill
        monkeypatch.setattr("shail.memory.rag.ingest", lambda **k: 0)
        summary = _run(session_backfill.backfill_session("nonexistent_id", "u_test"))
        assert summary.turns_seen == 0
        assert "session_not_found" in summary.errors

    def test_backfill_stamps_backfilled_at(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        from apps.shail import session_backfill
        monkeypatch.setattr(
            "shail.memory.rag.ingest",
            lambda records=None, **k: len(records or []),
        )
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )
        _run(session_backfill.backfill_session(seeded_session, "u_test", include_blueprint=False))
        meta = session_backfill.get_session_meta(seeded_session, "u_test")
        assert meta is not None
        assert meta.get("backfilled_at") is not None

    def test_backfill_generates_session_blueprint(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        from apps.shail import session_backfill
        from apps.shail import blueprints as bp_mod
        monkeypatch.setattr(
            "shail.memory.rag.ingest",
            lambda records=None, **k: len(records or []),
        )

        fake_bp = {
            "summary": "ML optimizer discussion",
            "decisions": [],
            "questions_answered": [
                {"q": "What is gradient descent?", "a": "Follows neg gradient"},
            ],
            "open_questions": [],
            "next_actions": [],
            "key_entities": ["Adam", "SGD", "RMSProp", "gradient descent"],
            "reasoning_chains": [],
            "failed_attempts": [],
            "facts": [], "metrics": [], "tables": [], "extensions": {},
        }

        async def _fake_gen(memory_id, *, content, content_type, user_id, namespace, **kwargs):
            bp_mod.save_blueprint(
                memory_id, fake_bp,
                user_id=user_id, namespace=namespace, content_type=content_type,
            )
            return fake_bp
        monkeypatch.setattr(session_backfill, "generate_blueprint", _fake_gen)

        summary = _run(session_backfill.backfill_session(seeded_session, "u_test"))
        assert summary.blueprint_generated is True
        assert summary.blueprint_memory_id == f"session_{seeded_session}"

        meta = session_backfill.get_session_meta(seeded_session, "u_test")
        assert meta["blueprint_memory_id"] == f"session_{seeded_session}"


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

class TestTimeline:
    def test_timeline_pairs_turns(self, chat_db: Path, seeded_session: str) -> None:
        from apps.shail.session_backfill import build_timeline
        tl = build_timeline(seeded_session, "u_test")
        assert tl is not None
        assert len(tl["turns"]) == 3
        for t in tl["turns"]:
            assert t["user_msg"]["role"] == "user"
            assert t["asst_msg"]["role"] == "assistant"
        assert tl["session"]["title"] == "ML discussion"

    def test_timeline_no_blueprint_when_not_generated(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail.session_backfill import build_timeline
        tl = build_timeline(seeded_session, "u_test")
        assert tl["blueprint"] is None
        assert tl["retention"]["raw_available"] is True

    def test_timeline_session_not_found(self, chat_db: Path) -> None:
        from apps.shail.session_backfill import build_timeline
        assert build_timeline("ghost_id", "u_test") is None


# ---------------------------------------------------------------------------
# Capture toggle
# ---------------------------------------------------------------------------

class TestCaptureToggle:
    def test_disable_capture(self, chat_db: Path, seeded_session: str) -> None:
        from apps.shail.session_backfill import (
            is_capture_enabled, set_session_capture,
        )
        assert is_capture_enabled(seeded_session) is True
        set_session_capture(seeded_session, "u_test", False)
        assert is_capture_enabled(seeded_session) is False
        set_session_capture(seeded_session, "u_test", True)
        assert is_capture_enabled(seeded_session) is True

    def test_capture_disabled_for_other_user_returns_default(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail.session_backfill import (
            is_capture_enabled, set_session_capture,
        )
        # Wrong user — update fails silently, capture stays default
        set_session_capture(seeded_session, "wrong_user", False)
        assert is_capture_enabled(seeded_session) is True


# ---------------------------------------------------------------------------
# Retention policy + redaction
# ---------------------------------------------------------------------------

class TestRetention:
    def test_default_retention_keep_raw(self, chat_db: Path, seeded_session: str) -> None:
        from apps.shail.session_backfill import get_session_meta
        meta = get_session_meta(seeded_session, "u_test")
        assert meta["retention_policy"] == "keep_raw"

    def test_set_retention_policy(self, chat_db: Path, seeded_session: str) -> None:
        from apps.shail.session_backfill import (
            get_session_meta, set_session_retention,
        )
        ok = set_session_retention(seeded_session, "u_test", "blueprint_only")
        assert ok
        meta = get_session_meta(seeded_session, "u_test")
        assert meta["retention_policy"] == "blueprint_only"

    def test_invalid_retention_raises(self, chat_db: Path, seeded_session: str) -> None:
        from apps.shail.session_backfill import set_session_retention
        with pytest.raises(ValueError):
            set_session_retention(seeded_session, "u_test", "bogus_policy")

    def test_redact_refused_without_blueprint(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail.session_backfill import redact_session_transcript
        result = redact_session_transcript(seeded_session, "u_test")
        assert result["ok"] is False
        assert result["reason"] == "no_blueprint_stored"

    def test_redact_succeeds_with_blueprint(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail.blueprints import save_blueprint
        from apps.shail.session_backfill import (
            _session_blueprint_memory_id, redact_session_transcript,
        )

        bp_id = _session_blueprint_memory_id(seeded_session)
        save_blueprint(
            bp_id,
            {"summary": "test", "decisions": [], "questions_answered": [],
             "open_questions": [], "next_actions": [], "key_entities": [],
             "reasoning_chains": [], "failed_attempts": [],
             "facts": [], "metrics": [], "tables": [], "extensions": {}},
            user_id="u_test", namespace="user_u_test", content_type="ai_conversation",
        )
        # Set the pointer on the session row
        from apps.shail.settings import get_settings
        with sqlite3.connect(get_settings().sqlite_path) as con:
            con.execute(
                "UPDATE chat_sessions SET blueprint_memory_id = ? WHERE id = ?",
                (bp_id, seeded_session),
            )

        result = redact_session_transcript(seeded_session, "u_test")
        assert result["ok"] is True
        assert result["messages_deleted"] == 6

        # Transcript gone; blueprint retained
        from apps.shail import chat_store
        from apps.shail.blueprints import get_blueprint
        assert chat_store.get_messages(seeded_session, "u_test") == []
        assert get_blueprint(bp_id) is not None

    def test_redact_session_not_found(self, chat_db: Path) -> None:
        from apps.shail.session_backfill import redact_session_transcript
        result = redact_session_transcript("ghost_id", "u_test")
        assert result["ok"] is False
        assert result["reason"] == "session_not_found"

    def test_timeline_after_redaction(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail.blueprints import save_blueprint
        from apps.shail.session_backfill import (
            _session_blueprint_memory_id, build_timeline, redact_session_transcript,
        )
        bp_id = _session_blueprint_memory_id(seeded_session)
        save_blueprint(
            bp_id,
            {"summary": "test", "decisions": [], "questions_answered": [],
             "open_questions": [], "next_actions": [], "key_entities": [],
             "reasoning_chains": [], "failed_attempts": [],
             "facts": [], "metrics": [], "tables": [], "extensions": {}},
            user_id="u_test", namespace="user_u_test", content_type="ai_conversation",
        )
        from apps.shail.settings import get_settings
        with sqlite3.connect(get_settings().sqlite_path) as con:
            con.execute(
                "UPDATE chat_sessions SET blueprint_memory_id = ? WHERE id = ?",
                (bp_id, seeded_session),
            )
        redact_session_transcript(seeded_session, "u_test")

        tl = build_timeline(seeded_session, "u_test")
        assert tl is not None
        assert tl["retention"]["policy"] == "transcript_deleted"
        assert tl["retention"]["raw_available"] is False
        assert tl["turns"] == []
        assert tl["blueprint"] is not None


# ---------------------------------------------------------------------------
# Sprint 1 — Degraded mode + FTS5 fallback
# ---------------------------------------------------------------------------

class TestDegradedMode:
    def test_backfill_degraded_when_ingest_returns_zero(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        """If ingest returns 0 with N pairs (Ollama down), summary flags degraded."""
        from apps.shail import session_backfill

        def _fake_ingest_all_zero(records=None, **kwargs):
            return 0  # simulates Ollama down — all-zero vectors dropped by ingest()
        monkeypatch.setattr("shail.memory.rag.ingest", _fake_ingest_all_zero)
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )

        summary = _run(session_backfill.backfill_session(
            seeded_session, "u_test", include_blueprint=False,
        ))
        assert summary.degraded_mode is True
        assert summary.degraded_reason is not None
        assert "embedder_unavailable" in summary.degraded_reason
        assert summary.turns_indexed == 0
        assert any("degraded" in e for e in summary.errors)

    def test_backfill_degraded_when_ingest_raises(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        """If ingest raises (e.g. connection refused), backfill marks degraded."""
        from apps.shail import session_backfill

        def _fake_ingest_raises(records=None, **kwargs):
            raise ConnectionError("ollama unreachable")
        monkeypatch.setattr("shail.memory.rag.ingest", _fake_ingest_raises)
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )

        summary = _run(session_backfill.backfill_session(
            seeded_session, "u_test", include_blueprint=False,
        ))
        assert summary.degraded_mode is True
        assert "ingest_exception" in (summary.degraded_reason or "")


class TestFTSFallback:
    def test_fts_table_created_and_seeded(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        """ensure_chat_fts_schema creates virtual table and seeds existing rows."""
        from apps.shail import chat_store
        from apps.shail.settings import get_settings

        chat_store.ensure_chat_fts_schema()
        assert chat_store.fts_available() is True
        with sqlite3.connect(get_settings().sqlite_path) as con:
            row = con.execute(
                "SELECT COUNT(*) FROM chat_messages_fts WHERE session_id = ?",
                (seeded_session,),
            ).fetchone()
        # seeded_session inserted 6 messages
        assert row[0] == 6

    def test_fts_search_returns_matches(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail import chat_store
        chat_store.ensure_chat_fts_schema()
        hits = chat_store.search_chat_fts("u_test", "gradient", limit=10)
        assert len(hits) >= 1
        assert any("gradient" in h["content"].lower() for h in hits)
        assert all(h["session_id"] == seeded_session for h in hits)

    def test_fts_isolates_by_user(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail import chat_store
        chat_store.ensure_chat_fts_schema()
        # other user sees nothing
        hits = chat_store.search_chat_fts("u_other", "gradient", limit=10)
        assert hits == []

    def test_fts_populated_by_trigger_on_new_message(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        """AFTER INSERT trigger should populate FTS for new messages."""
        from apps.shail import chat_store
        chat_store.ensure_chat_fts_schema()
        chat_store.append_message(
            seeded_session, "u_test", "user", "What about Lion optimizer?",
        )
        hits = chat_store.search_chat_fts("u_test", "Lion", limit=10)
        assert len(hits) >= 1

    def test_idempotent_schema_init(self, chat_db: Path) -> None:
        from apps.shail import chat_store
        chat_store.ensure_chat_fts_schema()
        chat_store.ensure_chat_fts_schema()  # second call must not raise
        chat_store.ensure_chat_fts_schema()
        assert chat_store.fts_available() is True


class TestPaginatedReader:
    def test_paginated_reader_returns_window(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail import chat_store
        page1 = chat_store.get_messages_paginated(
            seeded_session, "u_test", offset=0, limit=2,
        )
        page2 = chat_store.get_messages_paginated(
            seeded_session, "u_test", offset=2, limit=2,
        )
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0]["id"] != page2[0]["id"]

    def test_paginated_reader_owner_check(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail import chat_store
        assert chat_store.get_messages_paginated(
            seeded_session, "wrong_user", offset=0, limit=10,
        ) == []


# ---------------------------------------------------------------------------
# Sprint 2 — Cursor + state machine + resumption
# ---------------------------------------------------------------------------

class TestBackfillStateMachine:
    def test_state_starts_idle(self, chat_db: Path, seeded_session: str) -> None:
        from apps.shail.session_backfill import get_backfill_status
        status = get_backfill_status(seeded_session, "u_test")
        assert status is not None
        assert status["state"] == "idle"
        assert status["cursor"] == 0
        assert status["total_messages"] == 6

    def test_state_transitions_to_done(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        from apps.shail import session_backfill
        monkeypatch.setattr(
            "shail.memory.rag.ingest", lambda records=None, **k: len(records or []),
        )
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )
        _run(session_backfill.backfill_session(
            seeded_session, "u_test", include_blueprint=False,
        ))
        status = session_backfill.get_backfill_status(seeded_session, "u_test")
        assert status["state"] == "done"
        assert status["cursor"] == 6
        assert status["progress_pct"] == 100.0

    def test_state_transitions_to_degraded(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        from apps.shail import session_backfill
        monkeypatch.setattr("shail.memory.rag.ingest", lambda **k: 0)
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )
        _run(session_backfill.backfill_session(
            seeded_session, "u_test", include_blueprint=False,
        ))
        status = session_backfill.get_backfill_status(seeded_session, "u_test")
        assert status["state"] == "degraded"

    def test_state_transitions_to_failed_on_exception(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        from apps.shail import session_backfill

        # Make _reindex_turns_batch raise unhandled by patching chat_store
        # to raise mid-loop after first page.
        def _boom(*args, **kwargs):
            raise RuntimeError("disk full")
        monkeypatch.setattr(
            "apps.shail.chat_store.get_messages_paginated", _boom,
        )
        _run(session_backfill.backfill_session(
            seeded_session, "u_test", include_blueprint=False,
        ))
        status = session_backfill.get_backfill_status(seeded_session, "u_test")
        assert status["state"] == "failed"
        assert "disk full" in (status["error"] or "")

    def test_resumes_from_cursor(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        """Mid-run crash → cursor persists → re-run continues, skips done pairs."""
        from apps.shail import session_backfill, chat_store
        from apps.shail.settings import get_settings

        # Simulate prior partial run: stamp cursor at message 2
        session_backfill._set_backfill_state(
            seeded_session, state="failed", cursor=2, error="crashed",
        )

        record_calls: list[list[dict]] = []
        def _capture(records=None, **k):
            record_calls.append(list(records or []))
            return len(records or [])
        monkeypatch.setattr("shail.memory.rag.ingest", _capture)
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )

        _run(session_backfill.backfill_session(
            seeded_session, "u_test", include_blueprint=False, resume=True,
        ))
        status = session_backfill.get_backfill_status(seeded_session, "u_test")
        assert status["state"] == "done"
        assert status["cursor"] == 6
        # Should have skipped first 2 messages — fewer pairs indexed than full run
        indexed_pairs = sum(len(c) for c in record_calls)
        assert indexed_pairs <= 2  # at most 2 of 3 pairs remained

    def test_resume_false_starts_from_zero(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        from apps.shail import session_backfill
        session_backfill._set_backfill_state(seeded_session, cursor=4)
        record_calls: list[list[dict]] = []
        monkeypatch.setattr(
            "shail.memory.rag.ingest",
            lambda records=None, **k: (record_calls.append(list(records or [])), len(records or []))[1],
        )
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )
        _run(session_backfill.backfill_session(
            seeded_session, "u_test", include_blueprint=False, resume=False,
        ))
        # Full set of 3 pairs re-indexed despite cursor=4 hint
        indexed_pairs = sum(len(c) for c in record_calls)
        assert indexed_pairs == 3

    def test_chunked_driver_processes_in_pages(
        self, chat_db: Path, monkeypatch
    ) -> None:
        """50-message batch size — large session triggers multiple ingest calls."""
        from apps.shail import session_backfill, chat_store
        # Seed 120 messages = 60 pairs in one new session
        sess = chat_store.create_session("u_test", title="Large session")
        sid = sess["id"]
        for i in range(60):
            chat_store.append_message(sid, "u_test", "user", f"Q{i}")
            chat_store.append_message(sid, "u_test", "assistant", f"A{i}")

        ingest_calls = {"n": 0, "total": 0}
        def _capture(records=None, **k):
            ingest_calls["n"] += 1
            ingest_calls["total"] += len(records or [])
            return len(records or [])
        monkeypatch.setattr("shail.memory.rag.ingest", _capture)
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )

        _run(session_backfill.backfill_session(
            sid, "u_test", include_blueprint=False,
        ))
        # 120 messages / 50 per page = at least 3 pages → 3 ingest calls
        assert ingest_calls["n"] >= 3
        assert ingest_calls["total"] == 60
        status = session_backfill.get_backfill_status(sid, "u_test")
        assert status["state"] == "done"
        assert status["cursor"] == 120


# ---------------------------------------------------------------------------
# Sprint 3 — Sliding-window blueprint
# ---------------------------------------------------------------------------

class TestSlidingWindowBlueprint:
    def test_short_session_uses_single_window(self) -> None:
        from apps.shail.session_backfill import _slice_transcript_windows
        windows = _slice_transcript_windows("short text", 8000, 2000)
        assert windows == ["short text"]

    def test_long_transcript_sliced_with_overlap(self) -> None:
        from apps.shail.session_backfill import _slice_transcript_windows
        text = "x" * 20_000
        windows = _slice_transcript_windows(text, 8_000, 2_000)
        # 20k / (8k step=6k) → windows at 0, 6000, 12000 = 3 windows
        assert len(windows) == 3
        # All except possibly last are window_size long
        assert len(windows[0]) == 8_000
        assert len(windows[1]) == 8_000
        # Overlap: window[1] starts at pos 6000, so chars 6000–8000 of window[0]
        # appear at chars 0–2000 of window[1]
        assert windows[0][6_000:] == windows[1][:2_000]

    def test_sliding_window_covers_tail(
        self, chat_db: Path, monkeypatch
    ) -> None:
        """Entity present only in the FINAL turn of a 50k-char session must
        appear in the merged blueprint's key_entities."""
        from apps.shail import session_backfill, chat_store, blueprints as bp_mod
        import apps.shail.settings as S

        # Force a small budget so we chunk into multiple windows
        s = S.get_settings()
        monkeypatch.setattr(s, "blueprint_context_tokens", 2048)

        sess = chat_store.create_session("u_test", title="Long ML chat")
        sid = sess["id"]
        # Pad with bulk Q&A until total transcript > 24k chars (old single
        # blueprint cap). Then append a final pair containing a UNIQUE entity.
        for i in range(50):
            chat_store.append_message(sid, "u_test", "user", "Tell me about gradient descent " + "x" * 100)
            chat_store.append_message(sid, "u_test", "assistant", "It is iterative optimization " + "y" * 200)
        # Final turn — the canary entity must reach the merged blueprint
        chat_store.append_message(sid, "u_test", "user", "What about RAREENTITYZZ optimizer?")
        chat_store.append_message(sid, "u_test", "assistant", "RAREENTITYZZ uses adaptive moments.")

        # Capture which content slices each extract_blueprint call sees
        seen_windows: list[str] = []
        async def _fake_extract(*, content, content_type, user_id, prior=None, **kwargs):
            seen_windows.append(content)
            # If RAREENTITYZZ is in this window, extract it
            entities = []
            if "RAREENTITYZZ" in content:
                entities.append("RAREENTITYZZ")
            if "gradient" in content.lower():
                entities.append("gradient descent")
            bp = {
                "summary": f"window covering {len(content)} chars",
                "decisions": [], "questions_answered": [], "open_questions": [],
                "next_actions": [], "key_entities": entities,
                "reasoning_chains": [], "failed_attempts": [],
                "facts": [], "metrics": [], "tables": [], "extensions": {},
            }
            return bp
        monkeypatch.setattr(bp_mod, "extract_blueprint", _fake_extract)
        monkeypatch.setattr(
            "shail.memory.rag.ingest", lambda records=None, **k: len(records or []),
        )

        summary = _run(session_backfill.backfill_session(
            sid, "u_test", include_blueprint=True,
            char_cap=24_000,  # legacy cap — full transcript must still cover tail
        ))
        # Multiple windows generated (proof tail was visited)
        assert len(seen_windows) >= 3
        # Last window must contain the canary entity
        assert any("RAREENTITYZZ" in w for w in seen_windows)
        # Merged blueprint persisted with the canary
        bp = bp_mod.get_blueprint(f"session_{sid}")
        assert bp is not None
        assert "RAREENTITYZZ" in bp["key_entities"]
        # Earlier entity preserved through merge
        assert any("gradient" in e.lower() for e in bp["key_entities"])
        assert summary.blueprint_generated is True

    def test_short_session_still_single_call(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        """6-message seeded session is < 8k chars → single blueprint call."""
        from apps.shail import session_backfill
        call_count = {"n": 0}
        async def _fake_gen(memory_id, *, content, content_type, user_id, namespace, **kwargs):
            call_count["n"] += 1
            return {
                "summary": "x", "decisions": [], "questions_answered": [],
                "open_questions": [], "next_actions": [], "key_entities": [],
                "reasoning_chains": [], "failed_attempts": [],
                "facts": [], "metrics": [], "tables": [], "extensions": {},
            }
        monkeypatch.setattr(session_backfill, "generate_blueprint", _fake_gen)
        monkeypatch.setattr(
            "shail.memory.rag.ingest", lambda records=None, **k: len(records or []),
        )
        _run(session_backfill.backfill_session(
            seeded_session, "u_test", include_blueprint=True,
        ))
        assert call_count["n"] == 1  # short session → single call, not N windows


# ---------------------------------------------------------------------------
# Sprint 4 — External importers
# ---------------------------------------------------------------------------

class TestChatGPTImporter:
    def test_parse_basic_export(self) -> None:
        from apps.shail.importers import chatgpt
        sample = [{
            "title": "ML basics",
            "id": "conv_1",
            "create_time": 1700000000.0,
            "mapping": {
                "root": {"id": "root", "message": None, "parent": None, "children": ["a"]},
                "a": {
                    "id": "a",
                    "message": {
                        "id": "m_a",
                        "author": {"role": "user"},
                        "content": {"parts": ["What is SGD?"]},
                        "create_time": 1700000010.0,
                    },
                    "parent": "root",
                    "children": ["b"],
                },
                "b": {
                    "id": "b",
                    "message": {
                        "id": "m_b",
                        "author": {"role": "assistant"},
                        "content": {"parts": ["Stochastic gradient descent."]},
                        "create_time": 1700000020.0,
                    },
                    "parent": "a",
                    "children": [],
                },
            },
        }]
        convs = chatgpt.parse(json.dumps(sample))
        assert len(convs) == 1
        assert convs[0]["title"] == "ML basics"
        assert convs[0]["source_id"] == "conv_1"
        assert convs[0]["pairs"] == [("What is SGD?", "Stochastic gradient descent.")]

    def test_skips_system_and_tool_messages(self) -> None:
        from apps.shail.importers import chatgpt
        sample = [{
            "title": "with system",
            "id": "c2",
            "mapping": {
                "r": {"message": None, "parent": None, "children": ["s"]},
                "s": {
                    "message": {
                        "author": {"role": "system"},
                        "content": {"parts": ["sys"]},
                        "create_time": 1,
                    },
                    "parent": "r", "children": ["u1"],
                },
                "u1": {
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["hi"]},
                        "create_time": 2,
                    },
                    "parent": "s", "children": ["a1"],
                },
                "a1": {
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"parts": ["hello"]},
                        "create_time": 3,
                    },
                    "parent": "u1", "children": [],
                },
            },
        }]
        convs = chatgpt.parse(json.dumps(sample))
        assert convs[0]["pairs"] == [("hi", "hello")]

    def test_consecutive_user_messages_produce_orphan_pair(self) -> None:
        from apps.shail.importers import chatgpt
        sample = [{
            "title": "consec",
            "id": "c3",
            "mapping": {
                "r": {"message": None, "parent": None, "children": ["u1"]},
                "u1": {
                    "message": {"author": {"role": "user"}, "content": {"parts": ["q1"]}, "create_time": 1},
                    "parent": "r", "children": ["u2"],
                },
                "u2": {
                    "message": {"author": {"role": "user"}, "content": {"parts": ["q2"]}, "create_time": 2},
                    "parent": "u1", "children": ["a1"],
                },
                "a1": {
                    "message": {"author": {"role": "assistant"}, "content": {"parts": ["a"]}, "create_time": 3},
                    "parent": "u2", "children": [],
                },
            },
        }]
        convs = chatgpt.parse(json.dumps(sample))
        assert convs[0]["pairs"] == [("q1", ""), ("q2", "a")]


class TestClaudeImporter:
    def test_parse_basic_export(self) -> None:
        from apps.shail.importers import claude
        sample = [{
            "uuid": "u1",
            "name": "Adam vs SGD",
            "created_at": "2025-01-01T00:00:00Z",
            "chat_messages": [
                {"sender": "human", "text": "Compare Adam and SGD", "created_at": "2025-01-01T00:00:01Z"},
                {"sender": "assistant", "text": "Adam uses momentum + adaptive LR.", "created_at": "2025-01-01T00:00:02Z"},
            ],
        }]
        convs = claude.parse(json.dumps(sample))
        assert convs[0]["title"] == "Adam vs SGD"
        assert convs[0]["pairs"] == [
            ("Compare Adam and SGD", "Adam uses momentum + adaptive LR."),
        ]

    def test_newer_multipart_content_array(self) -> None:
        from apps.shail.importers import claude
        sample = [{
            "uuid": "u2",
            "name": "multipart",
            "chat_messages": [
                {"sender": "human", "content": [{"type": "text", "text": "Hi"}]},
                {"sender": "assistant", "content": [{"type": "text", "text": "Hello!"}]},
            ],
        }]
        convs = claude.parse(json.dumps(sample))
        assert convs[0]["pairs"] == [("Hi", "Hello!")]


class TestCursorImporter:
    def test_parse_flat_message_list(self) -> None:
        from apps.shail.importers import cursor
        sample = [
            {"role": "user", "content": "Refactor this function"},
            {"role": "assistant", "content": "Here's a cleaner version..."},
        ]
        convs = cursor.parse(json.dumps(sample))
        assert len(convs) == 1
        assert convs[0]["pairs"] == [
            ("Refactor this function", "Here's a cleaner version..."),
        ]

    def test_parse_tabs_structure(self) -> None:
        from apps.shail.importers import cursor
        sample = {
            "tabs": [{
                "tabId": "t1",
                "chats": [{
                    "id": "c1", "title": "Debug session",
                    "messages": [
                        {"role": "user", "content": "Why TypeError?"},
                        {"role": "assistant", "content": "Check the arg."},
                    ],
                }],
            }],
        }
        convs = cursor.parse(json.dumps(sample))
        assert convs[0]["title"] == "Debug session"
        assert convs[0]["pairs"] == [("Why TypeError?", "Check the arg.")]

    def test_derives_title_from_first_user_message(self) -> None:
        from apps.shail.importers import cursor
        sample = [
            {"role": "user", "content": "Implement a binary search in Rust"},
            {"role": "assistant", "content": "Sure."},
        ]
        convs = cursor.parse(json.dumps(sample))
        assert "binary search" in convs[0]["title"].lower()


class TestImportPipeline:
    def test_import_roundtrip_creates_sessions_and_messages(
        self, chat_db: Path
    ) -> None:
        from apps.shail.importers import (
            chatgpt,
            import_conversation_payload,
        )
        sample = [{
            "title": "Topic A",
            "id": "ca",
            "mapping": {
                "r": {"message": None, "parent": None, "children": ["u"]},
                "u": {
                    "message": {"author": {"role": "user"}, "content": {"parts": ["qA"]}, "create_time": 1},
                    "parent": "r", "children": ["a"],
                },
                "a": {
                    "message": {"author": {"role": "assistant"}, "content": {"parts": ["aA"]}, "create_time": 2},
                    "parent": "u", "children": [],
                },
            },
        }, {
            "title": "Topic B",
            "id": "cb",
            "mapping": {
                "r": {"message": None, "parent": None, "children": ["u"]},
                "u": {
                    "message": {"author": {"role": "user"}, "content": {"parts": ["qB"]}, "create_time": 1},
                    "parent": "r", "children": ["a"],
                },
                "a": {
                    "message": {"author": {"role": "assistant"}, "content": {"parts": ["aB"]}, "create_time": 2},
                    "parent": "u", "children": [],
                },
            },
        }]
        convs = chatgpt.parse(json.dumps(sample))
        result = import_conversation_payload(
            user_id="u_test", source="chatgpt", conversations=convs,
        )
        assert result.conversations_seen == 2
        assert result.sessions_created == 2
        assert result.messages_inserted == 4  # 2 conversations × 2 messages
        # Each created session is readable + carries source prefix in title
        from apps.shail import chat_store
        for sid in result.session_ids:
            sess = chat_store.get_session(sid, "u_test")
            assert sess is not None
            # Sprint 6: source on the row, not title prefix
            assert sess.get("source") == "chatgpt"
            assert not sess["title"].startswith("[chatgpt]")
            msgs = chat_store.get_messages(sid, "u_test")
            assert len(msgs) == 2
            assert msgs[0]["provider"] == "chatgpt"


# ---------------------------------------------------------------------------
# Sprint 6 — Hybrid retrieval (FTS fallback in chat search)
# ---------------------------------------------------------------------------

class TestHybridChatRetrieval:
    def test_search_returns_tuples_not_dicts(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        """Caller unpacks (content, score, meta); regression for prior
        chat_api.py:556 unpack-vs-dict mismatch."""
        from apps.shail import chat_api

        # Force vector path: return one fake hit
        class _FakeStore:
            def query(self, *, query_embedding, namespace, filters, k):
                return [{
                    "id": "asst_1",
                    "content": "Q: foo\n\nA: bar",
                    "metadata": {"assistant_message_id": "asst_1", "session_id": "s1"},
                    "score": 0.42,
                }]
        monkeypatch.setattr(chat_api, "_get_store", lambda: _FakeStore())
        monkeypatch.setattr(chat_api, "emb_q", lambda q: [0.1] * 8)

        hits = chat_api._search_past_chats("u_test", "anything", k=5)
        assert len(hits) == 1
        # Tuple shape: (content, score, meta)
        content, score, meta = hits[0]
        assert "bar" in content
        assert score == 0.42
        assert meta["source"] == "vector"
        assert meta["assistant_message_id"] == "asst_1"

    def test_search_falls_back_to_fts_when_embedder_zero(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        """Ollama down (zero vector probe) → FTS fallback hits returned."""
        from apps.shail import chat_api, chat_store
        chat_store.ensure_chat_fts_schema()

        # Vector path: returns zero vector → degraded
        class _FakeStore:
            def query(self, *, query_embedding, namespace, filters, k):
                return []  # would not be called when zero vector detected
        monkeypatch.setattr(chat_api, "_get_store", lambda: _FakeStore())
        monkeypatch.setattr(chat_api, "emb_q", lambda q: [0.0] * 8)  # zero vec

        hits = chat_api._search_past_chats("u_test", "gradient", k=5)
        assert len(hits) >= 1
        content, score, meta = hits[0]
        assert meta["source"] == "fts"
        assert meta["session_id"] == seeded_session
        assert "gradient" in content.lower()

    def test_search_falls_back_to_fts_when_vector_empty(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        """Embedder works but vector returns 0 hits (e.g. cold index) →
        FTS fallback fills the gap."""
        from apps.shail import chat_api, chat_store
        chat_store.ensure_chat_fts_schema()

        class _FakeEmptyStore:
            def query(self, *, query_embedding, namespace, filters, k):
                return []
        monkeypatch.setattr(chat_api, "_get_store", lambda: _FakeEmptyStore())
        monkeypatch.setattr(chat_api, "emb_q", lambda q: [0.5] * 8)  # non-zero

        hits = chat_api._search_past_chats("u_test", "gradient", k=5)
        assert len(hits) >= 1
        assert all(meta["source"] == "fts" for _, _, meta in hits)

    def test_search_prefers_vector_when_both_available(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        """Vector hits take precedence over FTS when both available."""
        from apps.shail import chat_api, chat_store
        chat_store.ensure_chat_fts_schema()

        class _FakeStore:
            def query(self, *, query_embedding, namespace, filters, k):
                return [{
                    "id": "asst_v1",
                    "content": "vector content",
                    "metadata": {"assistant_message_id": "asst_v1", "session_id": "s1"},
                    "score": 0.1,
                }]
        monkeypatch.setattr(chat_api, "_get_store", lambda: _FakeStore())
        monkeypatch.setattr(chat_api, "emb_q", lambda q: [0.5] * 8)

        hits = chat_api._search_past_chats("u_test", "gradient", k=5)
        assert hits[0][2]["source"] == "vector"

    def test_search_returns_empty_when_no_match_anywhere(
        self, chat_db: Path, seeded_session: str, monkeypatch
    ) -> None:
        from apps.shail import chat_api, chat_store
        chat_store.ensure_chat_fts_schema()

        class _FakeStore:
            def query(self, *, query_embedding, namespace, filters, k):
                return []
        monkeypatch.setattr(chat_api, "_get_store", lambda: _FakeStore())
        monkeypatch.setattr(chat_api, "emb_q", lambda q: [0.5] * 8)

        hits = chat_api._search_past_chats("u_test", "totallyunrelatedunicornsxyz", k=5)
        assert hits == []


# ---------------------------------------------------------------------------
# Sprint 7 — Bulk backfill + stats + embedding cache
# ---------------------------------------------------------------------------

class TestBackfillStats:
    def test_stats_empty_user_returns_zeros(self, chat_db: Path) -> None:
        from apps.shail.session_backfill import get_backfill_stats
        stats = get_backfill_stats("u_test")
        assert stats["total_sessions"] == 0
        assert stats["by_state"] == {
            "idle": 0, "running": 0, "done": 0, "failed": 0, "degraded": 0,
        }
        assert stats["degraded_sessions_pct"] == 0.0

    def test_stats_aggregates_states(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail import chat_store, session_backfill
        # Seed two more sessions in different states
        s2 = chat_store.create_session("u_test", title="done one")
        s3 = chat_store.create_session("u_test", title="failed one")
        session_backfill._set_backfill_state(s2["id"], state="done", cursor=10)
        session_backfill._set_backfill_state(s3["id"], state="failed", cursor=5)

        stats = session_backfill.get_backfill_stats("u_test")
        assert stats["total_sessions"] == 3
        assert stats["by_state"]["done"] == 1
        assert stats["by_state"]["failed"] == 1
        assert stats["by_state"]["idle"] == 1

    def test_stats_counts_by_source(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail import chat_store, session_backfill
        chat_store.create_session("u_test", title="imported", source="chatgpt")
        stats = session_backfill.get_backfill_stats("u_test")
        assert stats["by_source"].get("native", 0) >= 1
        assert stats["by_source"].get("chatgpt", 0) == 1


class TestListBackfillable:
    def test_lists_idle_and_failed_skips_running(
        self, chat_db: Path, seeded_session: str
    ) -> None:
        from apps.shail import chat_store, session_backfill
        s_running = chat_store.create_session("u_test", title="busy")
        session_backfill._set_backfill_state(s_running["id"], state="running")
        s_failed = chat_store.create_session("u_test", title="bad")
        session_backfill._set_backfill_state(s_failed["id"], state="failed")

        eligible = session_backfill.list_backfillable_sessions("u_test")
        eligible_ids = {s["id"] for s in eligible}
        assert seeded_session in eligible_ids
        assert s_failed["id"] in eligible_ids
        assert s_running["id"] not in eligible_ids


class TestEmbeddingCache:
    def test_cache_hit_skips_http_call(self, monkeypatch) -> None:
        from shail.memory import embeddings
        embeddings.clear_embedding_cache()

        call_count = {"n": 0}
        class _FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"embeddings": [[0.1] * 4 for _ in range(self._n)]}
        def _fake_post(*args, **kwargs):
            call_count["n"] += 1
            resp = _FakeResp()
            resp._n = len(kwargs["json"]["input"])
            return resp
        monkeypatch.setattr(embeddings.httpx, "post", _fake_post)

        # First call: all misses
        v1 = embeddings.embed_texts(["alpha", "beta", "gamma"])
        assert call_count["n"] == 1
        # Second call: all hits — no http
        v2 = embeddings.embed_texts(["alpha", "beta", "gamma"])
        assert call_count["n"] == 1  # unchanged
        assert v1 == v2

    def test_cache_partial_miss_only_sends_misses(self, monkeypatch) -> None:
        from shail.memory import embeddings
        embeddings.clear_embedding_cache()

        sent_inputs: list[list[str]] = []
        class _FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"embeddings": [[0.2] * 4 for _ in range(self._n)]}
        def _fake_post(*args, **kwargs):
            sent_inputs.append(list(kwargs["json"]["input"]))
            resp = _FakeResp()
            resp._n = len(kwargs["json"]["input"])
            return resp
        monkeypatch.setattr(embeddings.httpx, "post", _fake_post)

        embeddings.embed_texts(["a", "b"])
        embeddings.embed_texts(["a", "b", "c"])  # only 'c' should hit Ollama
        assert sent_inputs == [["a", "b"], ["c"]]

    def test_zero_vectors_not_cached(self, monkeypatch) -> None:
        from shail.memory import embeddings
        embeddings.clear_embedding_cache()

        # Simulate Ollama down — zero vectors returned
        import httpx as _httpx
        def _connect_err(*a, **k):
            raise _httpx.ConnectError("down")
        monkeypatch.setattr(embeddings.httpx, "post", _connect_err)

        v1 = embeddings.embed_texts(["text1"])
        assert embeddings.is_zero_vector(v1[0])
        stats = embeddings.embedding_cache_stats()
        assert stats["size"] == 0  # zero vec not cached

    def test_lru_eviction(self, monkeypatch) -> None:
        from shail.memory import embeddings
        embeddings.clear_embedding_cache()
        # Shrink cache for test
        embeddings._embed_cache._max = 3

        class _FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"embeddings": [[0.3] * 4 for _ in range(self._n)]}
        def _fake_post(*args, **kwargs):
            resp = _FakeResp()
            resp._n = len(kwargs["json"]["input"])
            return resp
        monkeypatch.setattr(embeddings.httpx, "post", _fake_post)

        for t in ["a", "b", "c", "d"]:
            embeddings.embed_texts([t])
        # Oldest ('a') evicted
        assert embeddings._embed_cache.get("a") is None
        assert embeddings._embed_cache.get("d") is not None
        embeddings._embed_cache._max = embeddings._EMBED_CACHE_MAX  # restore

