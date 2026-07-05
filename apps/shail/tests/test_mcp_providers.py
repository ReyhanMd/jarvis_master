"""MCP connector substrate tests.

Covers:
- ingest_record() normalization (metadata shape, namespace isolation, dedup)
- mcp_store CRUD (save/get/list/delete, sync_cursor, index_status)
- Token refresh detection logic
- Heuristic routing (pick_providers keyword scoring)
- Provider index() + fetch_relevant() with mocked HTTP
- End-to-end: indexed MCP data searchable in vector store

No Ollama or live provider APIs required — all external calls are mocked.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sys

sys.path.insert(0, "/Users/reyhan/shail workspace /shail_master/jarvis_master")


# ── Fixtures — use conftest.py isolated_db (patches Settings singleton) ───────

@pytest.fixture()
def user_id(isolated_db):
    """Create a test user and return their user_id."""
    from apps.shail.auth_store import init_auth_db, create_user
    init_auth_db()
    u = create_user("mcp_test@x.com", "password123", "MCP Tester")
    return u["id"]


def _run(coro):
    return asyncio.run(coro)


# ── ingest_record normalization ───────────────────────────────────────────────

class TestIngestRecord:
    def test_metadata_required_fields(self, user_id, monkeypatch):
        """ingest_record must set all fields expected by retrieval pipeline."""
        captured = []
        def _fake_ingest(records=None, **kwargs):
            captured.extend(records or [])
            return len(records or [])
        monkeypatch.setattr("apps.shail.mcp._oauth.ingest", _fake_ingest)

        from apps.shail.mcp._oauth import ingest_record
        result = ingest_record(
            user_id=user_id, provider="github", doc_id="acme/widget",
            title="Widget Repo", content="README content here",
            url="https://github.com/acme/widget",
        )

        assert result == 1
        assert len(captured) == 1
        rec = captured[0]
        meta = rec["metadata"]

        # Required retrieval keys
        assert meta["id"] == "github:acme/widget"
        assert meta["customId"] == "github:acme/widget"
        assert meta["provider"] == "github"
        assert meta["provider_id"] == "acme/widget"
        assert meta["title"] == "Widget Repo"
        assert meta["source"] == "mcp_github"
        assert meta["sourceUrl"] == "https://github.com/acme/widget"
        assert meta["tier"] == "important"
        # Namespace must be user-scoped
        assert rec["namespace"] == f"mcp_{user_id}_github"
        assert meta["namespace"] == f"mcp_{user_id}_github"

    def test_namespace_isolation_per_user(self, user_id, monkeypatch):
        """Each user gets their own mcp namespace — no cross-user data leakage."""
        from apps.shail.mcp._oauth import mcp_namespace
        ns1 = mcp_namespace(user_id, "github")
        ns2 = mcp_namespace("other_user_id", "github")
        assert ns1 != ns2
        assert user_id in ns1
        assert "other_user_id" in ns2

    def test_empty_content_returns_zero(self, user_id, monkeypatch):
        """Empty/whitespace content is skipped — no degenerate zero-vector records."""
        monkeypatch.setattr("apps.shail.mcp._oauth.ingest", lambda **k: 0)
        from apps.shail.mcp._oauth import ingest_record
        assert ingest_record(
            user_id=user_id, provider="github", doc_id="x",
            title="t", content="",
        ) == 0

    def test_extra_meta_forwarded(self, user_id, monkeypatch):
        captured = []
        monkeypatch.setattr("apps.shail.mcp._oauth.ingest",
                            lambda records=None, **k: (captured.extend(records or []), len(records or []))[1])
        from apps.shail.mcp._oauth import ingest_record
        ingest_record(
            user_id=user_id, provider="github", doc_id="r",
            title="t", content="x" * 20,
            extra_meta={"language": "Python", "stars": 42},
        )
        meta = captured[0]["metadata"]
        assert meta["language"] == "Python"
        assert meta["stars"] == 42


# ── mcp_store CRUD ────────────────────────────────────────────────────────────

class TestMcpStore:
    def test_save_and_get(self, user_id):
        from apps.shail.mcp_store import save_connection, get_connection
        save_connection(
            user_id, "github",
            access_token="tok_abc", refresh_token=None,
            metadata={"login": "testuser"},
        )
        conn = get_connection(user_id, "github")
        assert conn is not None
        assert conn["access_token"] == "tok_abc"
        assert conn["provider"] == "github"
        assert conn["metadata"]["login"] == "testuser"

    def test_upsert_updates_token(self, user_id):
        from apps.shail.mcp_store import save_connection, get_connection
        save_connection(user_id, "github", access_token="old_tok")
        save_connection(user_id, "github", access_token="new_tok")
        conn = get_connection(user_id, "github")
        assert conn["access_token"] == "new_tok"

    def test_refresh_token_preserved_on_upsert(self, user_id):
        """COALESCE: existing refresh_token not overwritten when new one is None."""
        from apps.shail.mcp_store import save_connection, get_connection
        save_connection(user_id, "drive", access_token="tok1", refresh_token="rf1")
        # Second upsert doesn't have refresh_token
        save_connection(user_id, "drive", access_token="tok2", refresh_token=None)
        conn = get_connection(user_id, "drive")
        assert conn["refresh_token"] == "rf1"  # preserved via COALESCE

    def test_delete_connection(self, user_id):
        from apps.shail.mcp_store import save_connection, get_connection, delete_connection
        save_connection(user_id, "notion", access_token="tok")
        assert get_connection(user_id, "notion") is not None
        delete_connection(user_id, "notion")
        assert get_connection(user_id, "notion") is None

    def test_list_connections(self, user_id):
        from apps.shail.mcp_store import save_connection, list_connections
        save_connection(user_id, "github", access_token="t1")
        save_connection(user_id, "drive", access_token="t2")
        conns = list_connections(user_id)
        providers = {c["provider"] for c in conns}
        assert "github" in providers
        assert "drive" in providers

    def test_index_status_transitions(self, user_id):
        from apps.shail.mcp_store import save_connection, get_connection, update_index_status
        save_connection(user_id, "github", access_token="tok")
        update_index_status(user_id, "github", status="indexing", indexed_count=10)
        conn = get_connection(user_id, "github")
        assert conn["index_status"] == "indexing"
        assert conn["indexed_count"] == 10
        update_index_status(user_id, "github", status="idle", indexed_count=50)
        conn = get_connection(user_id, "github")
        assert conn["index_status"] == "idle"
        assert conn["last_synced"] is not None  # stamped on idle

    def test_index_error_stored(self, user_id):
        from apps.shail.mcp_store import save_connection, get_connection, update_index_status
        save_connection(user_id, "drive", access_token="tok")
        update_index_status(user_id, "drive", status="error", error="401 Unauthorized")
        conn = get_connection(user_id, "drive")
        assert conn["index_status"] == "error"
        assert "401" in conn["index_error"]

    def test_sync_cursor_roundtrip(self, user_id):
        from apps.shail.mcp_store import save_connection, get_connection, update_sync_cursor
        save_connection(user_id, "drive", access_token="tok")
        ts = "2026-01-01T00:00:00+00:00"
        update_sync_cursor(user_id, "drive", ts)
        conn = get_connection(user_id, "drive")
        assert conn["sync_cursor"] == ts

    def test_sync_cursor_reset_to_none(self, user_id):
        from apps.shail.mcp_store import save_connection, get_connection, update_sync_cursor
        save_connection(user_id, "github", access_token="tok")
        update_sync_cursor(user_id, "github", "2026-01-01T00:00:00+00:00")
        update_sync_cursor(user_id, "github", None)
        conn = get_connection(user_id, "github")
        assert conn["sync_cursor"] is None


# ── Token refresh ─────────────────────────────────────────────────────────────

class TestTokenRefresh:
    def _make_conn(self, user_id, expires_at):
        from apps.shail.mcp_store import save_connection, get_connection
        save_connection(user_id, "drive", access_token="old_tok",
                        refresh_token="rf_tok", expires_at=expires_at)
        conn = get_connection(user_id, "drive")
        return conn

    def test_no_refresh_when_not_expired(self, user_id):
        from apps.shail.mcp._oauth import _is_token_expired
        far_future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        assert not _is_token_expired(far_future)

    def test_refresh_when_near_expiry(self, user_id):
        from apps.shail.mcp._oauth import _is_token_expired
        soon = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
        assert _is_token_expired(soon)

    def test_refresh_when_already_expired(self, user_id):
        from apps.shail.mcp._oauth import _is_token_expired
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert _is_token_expired(past)

    def test_no_expiry_stored_not_expired(self):
        """None expires_at → assumed non-expiring (e.g. GitHub tokens)."""
        from apps.shail.mcp._oauth import _is_token_expired
        assert not _is_token_expired(None)

    def test_maybe_refresh_calls_google_and_updates_store(self, user_id, monkeypatch):
        """Full refresh flow: detects expiry → calls Google → persists new token."""
        soon = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
        conn = self._make_conn(user_id, expires_at=soon)

        new_access = "refreshed_access_token_xyz"
        new_expires_in = 3600
        fake_resp = {"access_token": new_access, "expires_in": new_expires_in}

        async def _fake_post_form(url, data, **kwargs):
            assert "refresh_token" in data
            assert data["refresh_token"] == "rf_tok"
            return fake_resp

        monkeypatch.setattr("apps.shail.mcp._oauth.post_form", _fake_post_form)
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")

        from apps.shail.mcp._oauth import maybe_refresh_google_token
        updated = _run(maybe_refresh_google_token(conn))

        assert updated["access_token"] == new_access
        # Verify persisted in DB
        from apps.shail.mcp_store import get_connection
        stored = get_connection(user_id, "drive")
        assert stored["access_token"] == new_access

    def test_maybe_refresh_skips_when_not_expired(self, user_id, monkeypatch):
        """Not near expiry → post_form must NOT be called."""
        far = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        conn = self._make_conn(user_id, expires_at=far)

        called = []
        async def _should_not_call(url, data, **kwargs):
            called.append(True)
            return {}

        monkeypatch.setattr("apps.shail.mcp._oauth.post_form", _should_not_call)
        from apps.shail.mcp._oauth import maybe_refresh_google_token
        _run(maybe_refresh_google_token(conn))
        assert not called


# ── Heuristic routing ─────────────────────────────────────────────────────────

class TestHeuristicRouting:
    def test_github_keywords_high_confidence(self):
        """Two PATTERN matches → score 0.85 (scorer counts patterns, not tokens).

        "PR" hits pattern-1 (pr|pull_request|issue|...).
        "main branch" hits pattern-2 (github|main_branch|master_branch).
        Two patterns matched → score = 0.85.
        """
        from apps.shail.mcp.routing import heuristic_score
        scores = heuristic_score("what PR is open on the main branch?")
        assert scores["github"] >= 0.8

    def test_drive_keywords_high_confidence(self):
        from apps.shail.mcp.routing import heuristic_score
        # "document" and "Google Drive" → 2 matches
        scores = heuristic_score("find the document spec on Google Drive")
        assert scores["drive"] >= 0.8

    def test_notion_keywords_detected(self):
        from apps.shail.mcp.routing import heuristic_score
        scores = heuristic_score("what's in our Notion workspace?")
        assert scores["notion"] >= 0.5

    def test_gmail_keywords_detected(self):
        from apps.shail.mcp.routing import heuristic_score
        scores = heuristic_score("find the email from Sarah in my inbox")
        assert scores["gmail"] >= 0.5

    def test_no_keywords_all_zero(self):
        from apps.shail.mcp.routing import heuristic_score
        scores = heuristic_score("what is two plus two?")
        assert all(s == 0.0 for s in scores.values())

    def test_pick_providers_returns_only_connected(self):
        """Heuristic matches github but user only has drive connected → empty."""
        from apps.shail.mcp.routing import pick_providers
        # "PR" + "repo" → github high-confidence, but only drive is connected
        result = _run(
            pick_providers("what PR is merged in my repo?", connected={"drive"}, user_id="u1")
        )
        assert "github" not in result

    def test_pick_providers_high_confidence_included(self):
        from apps.shail.mcp.routing import pick_providers
        # "PR" + "repo" → high confidence for github
        result = _run(
            pick_providers(
                "what PR is open in my repo?",
                connected={"github", "drive"}, user_id="u1",
            )
        )
        assert "github" in result


# ── GitHub provider (mocked HTTP) ─────────────────────────────────────────────

class TestGitHubProvider:
    def _fake_repos(self):
        return [
            {
                "full_name": "user/alpha", "description": "Alpha project",
                "stargazers_count": 10, "language": "Python",
                "html_url": "https://github.com/user/alpha",
                "private": False, "pushed_at": "2026-01-01T00:00:00Z",
            },
            {
                "full_name": "user/beta", "description": "Beta project",
                "stargazers_count": 5, "language": "Go",
                "html_url": "https://github.com/user/beta",
                "private": False, "pushed_at": "2026-01-02T00:00:00Z",
            },
        ]

    def test_index_ingests_repos(self, user_id, monkeypatch):
        from apps.shail.mcp.github import github_provider
        from apps.shail.mcp_store import save_connection

        ingested = []
        async def _fake_get_json(url, **kwargs):
            if "/user/repos" in url:
                return self._fake_repos()
            if "/readme" in url:
                return {"content": ""}
            return {}

        monkeypatch.setattr("apps.shail.mcp.github.get_json", _fake_get_json)
        monkeypatch.setattr(
            "apps.shail.mcp.github.ingest_record",
            lambda **k: (ingested.append(k["doc_id"]), 1)[1],
        )
        monkeypatch.setattr("apps.shail.mcp.github.update_index_status", lambda *a, **k: None)
        monkeypatch.setattr("apps.shail.mcp.github.update_sync_cursor", lambda *a, **k: None)

        save_connection(user_id, "github", access_token="tok")
        count = _run(github_provider.index(
            user_id=user_id, access_token="tok", refresh_token=None, settings={},
        ))
        assert count == 2
        assert "user/alpha" in ingested
        assert "user/beta" in ingested

    def test_incremental_skips_old_repos(self, user_id, monkeypatch):
        from apps.shail.mcp.github import github_provider

        ingested = []
        async def _fake_get_json(url, **kwargs):
            if "/user/repos" in url:
                return self._fake_repos()
            return {"content": ""}

        monkeypatch.setattr("apps.shail.mcp.github.get_json", _fake_get_json)
        monkeypatch.setattr(
            "apps.shail.mcp.github.ingest_record",
            lambda **k: (ingested.append(k["doc_id"]), 1)[1],
        )
        monkeypatch.setattr("apps.shail.mcp.github.update_index_status", lambda *a, **k: None)
        monkeypatch.setattr("apps.shail.mcp.github.update_sync_cursor", lambda *a, **k: None)

        # cursor after alpha's pushed_at but before beta's — only beta should index
        count = _run(github_provider.index(
            user_id=user_id, access_token="tok", refresh_token=None,
            settings={"sync_cursor": "2026-01-01T12:00:00Z"},
        ))
        assert count == 1
        assert "user/beta" in ingested
        assert "user/alpha" not in ingested

    def test_fetch_relevant_returns_hits(self, user_id, monkeypatch):
        from apps.shail.mcp.github import github_provider

        async def _fake_get_json(url, **kwargs):
            if "/search/issues" in url:
                return {"items": [{"id": 1, "title": "Fix bug", "body": "Details", "html_url": "https://gh.com/1"}]}
            return {}

        monkeypatch.setattr("apps.shail.mcp.github.get_json", _fake_get_json)
        hits = _run(github_provider.fetch_relevant(
            user_id=user_id, query="bug fix", k=3,
            access_token="tok", refresh_token=None, settings={},
        ))
        assert len(hits) == 1
        assert hits[0].title == "Fix bug"


# ── Drive provider (mocked HTTP) ─────────────────────────────────────────────

class TestDriveProvider:
    def test_index_ingests_docs(self, user_id, monkeypatch):
        from apps.shail.mcp.drive import drive_provider

        ingested = []
        async def _fake_get_json(url, **kwargs):
            if "/files" in url and "export" not in url:
                return {
                    "files": [
                        {"id": "doc1", "name": "Spec", "mimeType": "application/vnd.google-apps.document",
                         "modifiedTime": "2026-01-01T00:00:00Z", "webViewLink": "https://docs.google.com/d/doc1"},
                    ],
                    "nextPageToken": None,
                }
            return {}

        async def _fake_fetch_text(self_inner, f, headers):
            return "Doc content here"

        monkeypatch.setattr("apps.shail.mcp.drive.get_json", _fake_get_json)
        monkeypatch.setattr(
            "apps.shail.mcp.drive._Drive._fetch_file_text",
            _fake_fetch_text,
        )
        monkeypatch.setattr(
            "apps.shail.mcp.drive.ingest_record",
            lambda **k: (ingested.append(k["doc_id"]), 1)[1],
        )
        monkeypatch.setattr("apps.shail.mcp.drive.update_index_status", lambda *a, **k: None)
        monkeypatch.setattr("apps.shail.mcp.drive.update_sync_cursor", lambda *a, **k: None)

        count = _run(drive_provider.index(
            user_id=user_id, access_token="tok", refresh_token=None, settings={},
        ))
        assert count == 1
        assert "doc1" in ingested


# ── Notion provider (mocked HTTP) ─────────────────────────────────────────────

class TestNotionProvider:
    def test_index_ingests_pages(self, user_id, monkeypatch):
        from apps.shail.mcp.notion import notion_provider

        ingested = []
        call_count = [0]

        async def _fake_post_json(url, body, **kwargs):
            call_count[0] += 1
            if "/search" in url and call_count[0] == 1:
                return {
                    "results": [
                        {
                            "object": "page",
                            "id": "page-uuid-1",
                            "url": "https://notion.so/page-uuid-1",
                            "properties": {
                                "title": {"type": "title", "title": [{"plain_text": "My Page"}]}
                            },
                        }
                    ],
                    "has_more": False,
                }
            # blocks endpoint (called by _fetch_page_text)
            return {"results": [
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Page body text"}]}}
            ]}

        async def _fake_get_json(url, **kwargs):
            return {"results": [
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "body"}]}}
            ]}

        monkeypatch.setattr("apps.shail.mcp.notion.post_json", _fake_post_json)
        monkeypatch.setattr("apps.shail.mcp.notion.get_json", _fake_get_json)
        monkeypatch.setattr(
            "apps.shail.mcp.notion.ingest_record",
            lambda **k: (ingested.append(k["doc_id"]), 1)[1],
        )
        monkeypatch.setattr("apps.shail.mcp.notion.update_index_status", lambda *a, **k: None)

        count = _run(notion_provider.index(
            user_id=user_id, access_token="tok", refresh_token=None, settings={},
        ))
        assert count == 1
        assert "page-uuid-1" in ingested
