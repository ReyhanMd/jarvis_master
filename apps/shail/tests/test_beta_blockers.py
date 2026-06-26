"""Tests for the 5 beta-blocker fixes:
1. Filesystem watcher (start/stop/list/persisted restart, debounce)
2. Crypto (Fernet encrypt/decrypt, idempotency, plaintext-safe)
3. MCP token encryption-at-rest (transparent round-trip)
4. user_settings API key encryption-at-rest
5. Empty-context prompt guard
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, "/Users/reyhan/shail workspace /shail_master/jarvis_master")


# ── Crypto ───────────────────────────────────────────────────────────────────

class TestCrypto:
    def test_encrypt_decrypt_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))  # isolate key file
        import importlib, apps.shail.crypto as c
        importlib.reload(c)
        token = "ya29.a0AfH6SMC_secret_garbage_here"
        ct = c.encrypt(token)
        assert ct.startswith("gcm1:")
        assert ct != token
        assert c.decrypt(ct) == token

    def test_encrypt_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        import importlib, apps.shail.crypto as c
        importlib.reload(c)
        once  = c.encrypt("abc")
        twice = c.encrypt(once)
        assert once == twice  # already-encrypted → no re-wrap

    def test_decrypt_plaintext_passes_through(self, tmp_path, monkeypatch):
        """Legacy plaintext rows must still be readable post-migration."""
        monkeypatch.setenv("HOME", str(tmp_path))
        import importlib, apps.shail.crypto as c
        importlib.reload(c)
        assert c.decrypt("legacy_plaintext_token") == "legacy_plaintext_token"

    def test_none_and_empty_pass_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        import importlib, apps.shail.crypto as c
        importlib.reload(c)
        assert c.encrypt(None) is None
        assert c.encrypt("") == ""
        assert c.decrypt(None) is None
        assert c.decrypt("") == ""

    def test_is_encrypted_helper(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        import importlib, apps.shail.crypto as c
        importlib.reload(c)
        assert not c.is_encrypted("plain")
        assert not c.is_encrypted(None)
        assert c.is_encrypted(c.encrypt("hello"))

    def test_key_persists_across_reload(self, tmp_path, monkeypatch):
        """A token encrypted now must decrypt after a process restart simulation."""
        monkeypatch.setenv("HOME", str(tmp_path))
        import importlib, apps.shail.crypto as c
        importlib.reload(c)
        ct = c.encrypt("durable")
        importlib.reload(c)  # simulate process restart — key reread from disk
        assert c.decrypt(ct) == "durable"


# ── MCP token encryption-at-rest ─────────────────────────────────────────────

class TestMcpStoreEncryption:
    def _user(self, isolated_db):
        from apps.shail.auth_store import init_auth_db, create_user
        init_auth_db()
        u = create_user("enc_test@x.com", "password123")
        return u["id"]

    def test_save_then_read_decrypts_transparently(self, isolated_db, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        import importlib, apps.shail.crypto as c
        importlib.reload(c)
        import apps.shail.mcp_store as ms
        importlib.reload(ms)

        user_id = self._user(isolated_db)
        ms.save_connection(user_id, "github",
                           access_token="ghp_secret", refresh_token="rt_secret")
        conn = ms.get_connection(user_id, "github")
        # Caller sees plaintext — encryption is transparent
        assert conn["access_token"] == "ghp_secret"
        assert conn["refresh_token"] == "rt_secret"

    def test_db_row_actually_encrypted(self, isolated_db, monkeypatch, tmp_path):
        """Inspect raw row — ciphertext must be unrecognisable."""
        monkeypatch.setenv("HOME", str(tmp_path))
        import importlib, apps.shail.crypto as c
        importlib.reload(c)
        import apps.shail.mcp_store as ms
        importlib.reload(ms)

        user_id = self._user(isolated_db)
        ms.save_connection(user_id, "drive", access_token="VERY_SECRET_TOK_xyz")
        # Direct DB peek — bypass _row_to_conn
        import sqlite3
        from apps.shail.settings import get_settings
        with sqlite3.connect(get_settings().sqlite_path) as con:
            row = con.execute(
                "SELECT access_token FROM mcp_connections WHERE user_id=? AND provider=?",
                (user_id, "drive"),
            ).fetchone()
        assert row is not None
        stored = row[0]
        assert "VERY_SECRET_TOK_xyz" not in stored, "plaintext leaked to disk!"
        assert stored.startswith("gcm1:")

    def test_legacy_plaintext_row_still_readable(self, isolated_db, monkeypatch, tmp_path):
        """If a pre-encryption row exists, _row_to_conn must return it as-is."""
        monkeypatch.setenv("HOME", str(tmp_path))
        import importlib, apps.shail.crypto as c
        importlib.reload(c)
        import apps.shail.mcp_store as ms
        importlib.reload(ms)

        user_id = self._user(isolated_db)
        # Inject a legacy plaintext row directly (simulating pre-migration state)
        import sqlite3
        from apps.shail.settings import get_settings
        from datetime import datetime, timezone
        with sqlite3.connect(get_settings().sqlite_path) as con:
            con.execute(
                "INSERT INTO mcp_connections (user_id, provider, access_token, refresh_token, "
                "metadata, connected_at, indexed_count, index_status) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, 'idle')",
                (user_id, "notion", "legacy_plain", None, "{}",
                 datetime.now(timezone.utc).isoformat()),
            )
        conn = ms.get_connection(user_id, "notion")
        assert conn["access_token"] == "legacy_plain"


# ── user_settings API key encryption ─────────────────────────────────────────

class TestUserSettingsEncryption:
    def test_openai_key_encrypted_at_rest(self, isolated_db, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        import importlib, apps.shail.crypto as c
        importlib.reload(c)
        # Reload auth_store so its lazy `from apps.shail.crypto import ...` picks
        # up the freshly-keyed crypto module.
        import apps.shail.auth_store as a
        importlib.reload(a)
        a.init_auth_db()
        user = a.create_user("k@x.com", "p"*8)
        a.update_user_settings(user["id"], openai_api_key="sk-LIVE-secret-key-abc")

        # Direct DB read — must be ciphertext
        import sqlite3
        from apps.shail.settings import get_settings
        with sqlite3.connect(get_settings().sqlite_path) as con:
            row = con.execute(
                "SELECT openai_api_key FROM user_settings WHERE user_id=?",
                (user["id"],),
            ).fetchone()
        assert row and row[0].startswith("gcm1:")
        assert "sk-LIVE-secret-key-abc" not in row[0]

        # API read — decrypted transparently
        s = a.get_user_settings(user["id"])
        assert s["openai_api_key"] == "sk-LIVE-secret-key-abc"


# ── Filesystem watcher ───────────────────────────────────────────────────────

class TestFilesystemWatcher:
    def test_supported_extension_filter(self, monkeypatch, tmp_path):
        from shail.integrations.local.filesystem.adapter import _is_supported
        assert _is_supported("/x/notes.md")
        assert _is_supported("/x/code.py")
        assert _is_supported("/x/data.json")
        assert not _is_supported("/x/binary.bin")
        assert not _is_supported("/x/photo.jpg")

    def test_junk_dirs_filtered(self):
        from shail.integrations.local.filesystem.adapter import _is_supported
        assert not _is_supported("/proj/node_modules/lodash.js")
        assert not _is_supported("/proj/.git/HEAD")
        assert not _is_supported("/proj/__pycache__/x.py")
        assert not _is_supported("/proj/.venv/bin/python")

    def test_watch_row_crud(self, isolated_db):
        from shail.integrations.local.filesystem.adapter import (
            add_watch_row, list_watch_rows, remove_watch_row,
        )
        add_watch_row("u1", "/tmp/x")
        add_watch_row("u1", "/tmp/y")
        rows = list_watch_rows("u1")
        paths = {r["path"] for r in rows}
        assert "/tmp/x" in paths and "/tmp/y" in paths
        # Idempotent — duplicate add doesn't error
        add_watch_row("u1", "/tmp/x")
        assert len([r for r in list_watch_rows("u1") if r["path"] == "/tmp/x"]) == 1
        # Remove works
        n = remove_watch_row("u1", "/tmp/x")
        assert n == 1
        paths = {r["path"] for r in list_watch_rows("u1")}
        assert "/tmp/x" not in paths

    def test_watch_isolation_between_users(self, isolated_db):
        from shail.integrations.local.filesystem.adapter import (
            add_watch_row, list_watch_rows,
        )
        add_watch_row("alice", "/tmp/a")
        add_watch_row("bob",   "/tmp/b")
        a_rows = list_watch_rows("alice")
        b_rows = list_watch_rows("bob")
        assert {r["path"] for r in a_rows} == {"/tmp/a"}
        assert {r["path"] for r in b_rows} == {"/tmp/b"}

    def test_start_and_stop_watch_real_dir(self, isolated_db, tmp_path):
        """End-to-end: start observer on real dir, list, stop."""
        from shail.integrations.local.filesystem.adapter import FileSystemAdapter
        adapter = FileSystemAdapter()
        res = adapter.start_watch("u_real", str(tmp_path))
        assert res["ok"] is True
        # list_watches reads from DB
        rows = adapter.list_watches("u_real")
        assert any(r["path"] == str(tmp_path.resolve()) for r in rows)
        # Stop
        stop = adapter.stop_watch("u_real", str(tmp_path))
        assert stop["ok"] is True
        rows = adapter.list_watches("u_real")
        assert not any(r["path"] == str(tmp_path.resolve()) for r in rows)

    def test_start_watch_on_nonexistent_path_fails(self, isolated_db):
        from shail.integrations.local.filesystem.adapter import FileSystemAdapter
        adapter = FileSystemAdapter()
        res = adapter.start_watch("u", "/nonexistent/xyz/qwerty")
        assert res["ok"] is False
        assert "not a directory" in res["error"]

    def test_debouncer_coalesces_events(self):
        """Multiple events for the same key within debounce window → single flush."""
        from shail.integrations.local.filesystem.adapter import _DebouncedIngest
        import threading, time as _time

        flushes = []
        d = _DebouncedIngest()
        # Monkeypatch the flush handler to record what would be ingested
        original_flush = d._flush
        def _record(key):
            with d._lock:
                paths = list(d._pending.pop(key, set()))
                d._timers.pop(key, None)
            flushes.append((key, paths))
        d._flush = _record

        # Patch the debounce window short for testing
        import shail.integrations.local.filesystem.adapter as adapter_mod
        original_window = adapter_mod._DEBOUNCE_SECONDS
        adapter_mod._DEBOUNCE_SECONDS = 0.3
        try:
            # Recreate the debouncer with patched window
            d2 = _DebouncedIngest()
            d2._flush = lambda key: flushes.append(
                (key, list(d2._pending.pop(key, set())))
            )
            for fname in ["/tmp/a.md", "/tmp/b.py", "/tmp/c.txt"]:
                d2.schedule("u_x", "/tmp", fname)
            _time.sleep(0.6)
        finally:
            adapter_mod._DEBOUNCE_SECONDS = original_window

        assert len(flushes) == 1
        _key, paths = flushes[0]
        assert set(paths) == {"/tmp/a.md", "/tmp/b.py", "/tmp/c.txt"}


# ── Empty-context guard in prompt ────────────────────────────────────────────

class TestEmptyContextGuard:
    def test_grounding_policy_mentions_empty_context(self):
        from apps.shail.chat_api import GROUNDING_POLICY_PROMPT
        assert "EMPTY CONTEXT" in GROUNDING_POLICY_PROMPT
        assert "Do not emit any citation token" in GROUNDING_POLICY_PROMPT or \
               "no retrieved memory" in GROUNDING_POLICY_PROMPT.lower()
