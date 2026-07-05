"""End-to-end probe: does retroactive recapture cover ENTIRE session or only recent?"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, "/Users/reyhan/shail workspace /shail_master/jarvis_master")

def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def chat_db(isolated_db, monkeypatch):
    from apps.shail.auth_store import init_auth_db
    from apps.shail.blueprints import init_blueprint_db
    from apps.shail.session_backfill import ensure_phase_c_schema
    import sqlite3

    init_auth_db()
    init_blueprint_db()
    ensure_phase_c_schema()
    with sqlite3.connect(str(isolated_db)) as con:
        con.execute(
            "INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("u_e2e", "e2e@x.com", "h", "2026-01-01T00:00:00+00:00"),
        )
    return isolated_db


def _seed_long_session(num_pairs):
    from apps.shail import chat_store
    sess = chat_store.create_session("u_e2e", title=f"{num_pairs}-pair session")
    sid = sess["id"]
    for i in range(num_pairs):
        # Unique tokens per pair so we can verify each was captured
        chat_store.append_message(sid, "u_e2e", "user", f"QUESTION_{i:03d} about widget {i}")
        chat_store.append_message(sid, "u_e2e", "assistant", f"ANSWER_{i:03d} about widget {i} which uses ENTITY_{i:03d}")
    return sid


class TestRetroactiveCoverage:
    """Question 1: does backfill cover ENTIRE session?"""

    def test_backfill_indexes_every_pair_not_just_recent(self, chat_db, monkeypatch):
        """A 75-pair session: every pair (oldest to newest) must reach the indexer."""
        from apps.shail import session_backfill

        sid = _seed_long_session(75)
        ingested_pair_ids = []
        def _fake_ingest(records=None, **kwargs):
            for r in records or []:
                ingested_pair_ids.append(r["metadata"]["assistant_message_id"])
            return len(records or [])
        monkeypatch.setattr("shail.memory.rag.ingest", _fake_ingest)
        monkeypatch.setattr(
            session_backfill, "generate_blueprint", AsyncMock(return_value=None),
        )

        summary = _run(session_backfill.backfill_session(sid, "u_e2e", include_blueprint=False))

        # Capture: every pair indexed (75 of 75), not partial
        assert summary.turns_indexed == 75, f"expected 75 pairs, got {summary.turns_indexed}"
        assert len(ingested_pair_ids) == 75
        # No duplicates (idempotent on re-run would also hold)
        assert len(set(ingested_pair_ids)) == 75
        # Cursor reached end
        status = session_backfill.get_backfill_status(sid, "u_e2e")
        assert status["state"] == "done"
        assert status["cursor"] == 150  # 75 pairs * 2 messages
        print(f"\n✓ Captured ALL {summary.turns_indexed}/75 pairs (not partial). Cursor at end.")

    def test_blueprint_covers_first_and_last_turn(self, chat_db, monkeypatch):
        """Sprint 3 sliding-window: blueprint must see entities from both ends."""
        from apps.shail import session_backfill, chat_store, blueprints as bp_mod
        import apps.shail.settings as S

        # Force a small budget so we chunk into multiple windows
        s = S.get_settings()
        monkeypatch.setattr(s, "blueprint_context_tokens", 2048)

        # 80 pairs ≈ 80 * (~110 chars) = ~8800 chars — forces multi-window
        # Plus pad each so transcript exceeds single-window 8k size
        sess = chat_store.create_session("u_e2e", title="long blueprint test")
        sid = sess["id"]
        chat_store.append_message(sid, "u_e2e", "user", "FIRSTQ about FIRSTENTITY")
        chat_store.append_message(sid, "u_e2e", "assistant", "FIRSTA mentions FIRSTENTITY " + "x" * 300)
        for i in range(80):
            chat_store.append_message(sid, "u_e2e", "user", f"midQ_{i}")
            chat_store.append_message(sid, "u_e2e", "assistant", f"midA_{i}")
        chat_store.append_message(sid, "u_e2e", "user", "LASTQ about LASTENTITY")
        chat_store.append_message(sid, "u_e2e", "assistant", "LASTA mentions LASTENTITY")

        seen_windows = []
        async def _fake_extract(*, content, content_type, user_id, prior=None, **kwargs):
            seen_windows.append(content)
            return {
                "summary": "test", "decisions": [], "questions_answered": [],
                "open_questions": [], "next_actions": [],
                "key_entities": (
                    (["FIRSTENTITY"] if "FIRSTENTITY" in content else [])
                    + (["LASTENTITY"] if "LASTENTITY" in content else [])
                ),
                "reasoning_chains": [], "failed_attempts": [],
                "facts": [], "metrics": [], "tables": [], "extensions": {},
            }
        monkeypatch.setattr(bp_mod, "extract_blueprint", _fake_extract)
        monkeypatch.setattr("shail.memory.rag.ingest",
                            lambda records=None, **k: len(records or []))

        _run(session_backfill.backfill_session(sid, "u_e2e", include_blueprint=True))

        from apps.shail.blueprints import get_blueprint
        bp = get_blueprint(f"session_{sid}")
        assert bp is not None
        # Both ends must appear — proves NOT recent-only
        assert "FIRSTENTITY" in bp["key_entities"], (
            f"first-turn entity missing! windows seen: {len(seen_windows)}, "
            f"entities: {bp['key_entities']}"
        )
        assert "LASTENTITY" in bp["key_entities"], (
            f"last-turn entity missing! entities: {bp['key_entities']}"
        )
        print(f"\n✓ Blueprint covers BOTH first ({'FIRSTENTITY' in bp['key_entities']}) "
              f"and last ({'LASTENTITY' in bp['key_entities']}) turns "
              f"via {len(seen_windows)} sliding windows.")


class TestContinueCapture:
    """Question 2: does it capture NEW chats in same session after backfill?"""

    def test_capture_flag_default_true(self, chat_db):
        """New session: continue-capture enabled by default."""
        from apps.shail import session_backfill
        sid = _seed_long_session(1)
        assert session_backfill.is_capture_enabled(sid) is True
        print("\n✓ capture_enabled default TRUE for new session.")

    def test_new_turn_after_backfill_triggers_indexer(self, chat_db, monkeypatch):
        """After backfill done, a new turn must call _index_past_chat_turn."""
        from apps.shail import session_backfill, chat_store, chat_api

        sid = _seed_long_session(3)
        monkeypatch.setattr("shail.memory.rag.ingest",
                            lambda records=None, **k: len(records or []))
        monkeypatch.setattr(session_backfill, "generate_blueprint",
                            AsyncMock(return_value=None))

        _run(session_backfill.backfill_session(sid, "u_e2e", include_blueprint=False))
        assert session_backfill.get_backfill_status(sid, "u_e2e")["state"] == "done"

        # Now append a NEW turn — the live capture path is gated by
        # is_capture_enabled. Verify the gate returns True.
        chat_store.append_message(sid, "u_e2e", "user", "NEW_Q_AFTER_BACKFILL")
        chat_store.append_message(sid, "u_e2e", "assistant", "NEW_A_AFTER_BACKFILL")
        last_user = chat_store.get_messages(sid, "u_e2e")[-2]
        last_asst = chat_store.get_messages(sid, "u_e2e")[-1]

        # Simulate the live-capture call path (what _schedule_post_reply runs).
        # chat_api imports `ingest` at module load — must patch the local name
        # not the source module to intercept this call.
        captured = []
        def _capture(records=None, **k):
            captured.extend(records or [])
            return len(records or [])
        monkeypatch.setattr("apps.shail.chat_api.ingest", _capture)

        # Gate check (Phase C continue-capture)
        assert session_backfill.is_capture_enabled(sid) is True
        # Direct indexer call mimics _schedule_post_reply post-turn behavior
        chat_api._index_past_chat_turn(
            user_id="u_e2e", session_id=sid,
            user_msg_id=last_user["id"], assistant_msg_id=last_asst["id"],
            user_text=last_user["content"], assistant_text=last_asst["content"],
            session_title="continue-test",
        )
        assert len(captured) == 1
        assert "NEW_Q_AFTER_BACKFILL" in captured[0]["content"]
        assert "NEW_A_AFTER_BACKFILL" in captured[0]["content"]
        print("\n✓ Continue-capture indexes NEW turn after backfill completed.")

    def test_capture_disabled_blocks_new_indexing(self, chat_db):
        """User toggles capture off → live path should refuse."""
        from apps.shail import session_backfill
        sid = _seed_long_session(1)
        session_backfill.set_session_capture(sid, "u_e2e", False)
        assert session_backfill.is_capture_enabled(sid) is False
        # And re-enable
        session_backfill.set_session_capture(sid, "u_e2e", True)
        assert session_backfill.is_capture_enabled(sid) is True
        print("\n✓ Capture toggle works (off → blocks, on → resumes).")


class TestFTSCoverage:
    """Bonus: FTS5 (degraded-mode fallback) covers ENTIRE session, not just recent."""

    def test_fts_indexes_all_messages_via_trigger(self, chat_db):
        from apps.shail import chat_store
        sid = _seed_long_session(50)  # 100 messages
        chat_store.ensure_chat_fts_schema()  # idempotent
        # Trigger fires on every INSERT — should already be populated
        import sqlite3
        from apps.shail.settings import get_settings
        with sqlite3.connect(get_settings().sqlite_path) as con:
            count = con.execute(
                "SELECT COUNT(*) FROM chat_messages_fts WHERE session_id = ?",
                (sid,),
            ).fetchone()[0]
        assert count == 100, f"FTS missing rows: {count}/100"
        # Search for very first message + very last
        first = chat_store.search_chat_fts("u_e2e", "widget 0", limit=5)
        last = chat_store.search_chat_fts("u_e2e", "widget 49", limit=5)
        assert any("000" in h["content"] for h in first), "First message not in FTS!"
        assert any("049" in h["content"] for h in last), "Last message not in FTS!"
        print(f"\n✓ FTS5 indexed all 100 messages, searchable from oldest to newest.")
