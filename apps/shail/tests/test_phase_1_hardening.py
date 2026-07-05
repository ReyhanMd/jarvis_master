import os
import sys
import json
import pytest
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from apps.shail.main import app
from apps.shail.db import close_db_pool
import apps.shail.crypto as crypto
import apps.shail.llm as llm
from shail.integrations.mcp.provider import get_provider, reset_provider

@pytest.fixture
def anyio_backend():
    return "asyncio"

# ── 1. Database & Crypto Migrations ──────────────────────────────────────────

def test_aes_256_gcm_migration(isolated_db, monkeypatch, tmp_path):
    # Set the temporary directory as HOME so .shail/token.key is isolated
    monkeypatch.setenv("HOME", str(tmp_path))

    # Initialize a legacy key file with Fernet
    from cryptography.fernet import Fernet
    legacy_key = Fernet.generate_key()
    legacy_key_dir = tmp_path / ".shail"
    legacy_key_dir.mkdir(parents=True, exist_ok=True)
    legacy_key_file = legacy_key_dir / "token.key"
    legacy_key_file.write_bytes(legacy_key)

    # Force crypto module to reload and use our isolated HOME environment
    import importlib
    importlib.reload(crypto)

    # Encrypt a value with Fernet
    f = Fernet(legacy_key)
    openai_key_plain = "sk-proj-12345"
    openai_key_fernet = "fer1:" + f.encrypt(openai_key_plain.encode()).decode()

    # Pre-populate database with plaintext, Fernet-encrypted, and already GCM-encrypted values
    from apps.shail.auth_store import init_auth_db
    init_auth_db()

    with sqlite3.connect(str(isolated_db)) as conn:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, created_at) VALUES ('user1', 'u1@test.com', 'hash', '2026-06-20')"
        )
        # OpenAI is Fernet-encrypted; Anthropic is plaintext; External is already GCM-encrypted (will bypass)
        conn.execute(
            "INSERT INTO user_settings (user_id, openai_api_key, anthropic_api_key, external_api_key) "
            "VALUES ('user1', ?, ?, ?)",
            (openai_key_fernet, "plain-anthropic-key", "gcm1:dummy-gcm-already")
        )
        # access_token is plaintext; refresh_token is Fernet-encrypted
        conn.execute(
            "INSERT INTO mcp_connections (user_id, provider, access_token, refresh_token, connected_at) "
            "VALUES ('user1', 'github', ?, ?, '2026-06-20')",
            ("plain-github-access", "fer1:" + f.encrypt(b"refresh-tok").decode())
        )

    # Execute migrations
    crypto.run_migrations()

    # Verify migration results
    with sqlite3.connect(str(isolated_db)) as conn:
        conn.row_factory = sqlite3.Row
        settings = conn.execute("SELECT * FROM user_settings WHERE user_id = 'user1'").fetchone()
        mcp = conn.execute("SELECT * FROM mcp_connections WHERE user_id = 'user1' AND provider = 'github'").fetchone()

    # Check user_settings
    assert settings["openai_api_key"].startswith("gcm1:")
    assert crypto.decrypt(settings["openai_api_key"]) == openai_key_plain

    assert settings["anthropic_api_key"].startswith("gcm1:")
    assert crypto.decrypt(settings["anthropic_api_key"]) == "plain-anthropic-key"

    assert settings["external_api_key"] == "gcm1:dummy-gcm-already"

    # Check mcp_connections
    assert mcp["access_token"].startswith("gcm1:")
    assert crypto.decrypt(mcp["access_token"]) == "plain-github-access"

    assert mcp["refresh_token"].startswith("gcm1:")
    assert crypto.decrypt(mcp["refresh_token"]) == "refresh-tok"

    # Assert that the legacy token.key file was deleted
    assert not legacy_key_file.exists()


# ── 2. Keychain Subprocess Bridge ───────────────────────────────────────────

def test_keychain_subprocess_calls():
    # Test _get_keychain_key calls the security utility correctly
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["security"], returncode=0, stdout="retrieved_secret_key\n", stderr=""
        )
        with patch("sys.platform", "darwin"):
            key = crypto._get_keychain_key()
            assert key == "retrieved_secret_key"
            mock_run.assert_called_once_with(
                ["security", "find-generic-password", "-a", "shail_master_key", "-s", "shail_system", "-w"],
                capture_output=True,
                text=True,
                check=True
            )

    # Test _set_keychain_key calls the security utility correctly
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=["security"], returncode=0)
        with patch("sys.platform", "darwin"):
            res = crypto._set_keychain_key("new_secret_key")
            assert res is True
            mock_run.assert_called_once_with(
                ["security", "add-generic-password", "-a", "shail_master_key", "-s", "shail_system", "-w", "new_secret_key", "-U"],
                check=True,
                capture_output=True
            )


# ── 3. Standardized LLM Router Streaming ────────────────────────────────────

@pytest.mark.anyio
async def test_stream_llm_standardized_format():
    # Mock the internal _dispatch call in llm module to yield raw test chunks
    async def mock_generator():
        yield {"text": "chunk1", "done": False}
        yield {"text": "chunk2", "done": True}

    with patch("apps.shail.llm._dispatch", return_value=mock_generator()) as mock_dispatch:
        messages = [{"role": "user", "content": "hello"}]
        results = []
        async for payload, meta in llm.stream_llm(messages, user_id="local"):
            results.append(payload)

        # Assert output payload complies with unified format: {"text": str, "done": bool}
        assert len(results) == 2
        assert results[0] == {"text": "chunk1", "done": False}
        assert results[1] == {"text": "chunk2", "done": True}


# ── 4. Core MCP JSON-RPC Gateway Endpoint ───────────────────────────────────

def test_mcp_jsonrpc_endpoints(isolated_db):
    client = TestClient(app)

    # Set up user settings & user in the isolated DB to satisfy verification
    from apps.shail.auth_store import init_auth_db, create_user, create_api_key
    init_auth_db()
    user = create_user("mcp_test@x.com", "pass12345")
    api_key = create_api_key(user["id"], label="test-key")

    headers = {"Authorization": f"Bearer {api_key}"}

    # 4.1 Test Ping Method
    payload = {
        "jsonrpc": "2.0",
        "method": "ping",
        "id": 100
    }
    resp = client.post("/mcp/rpc", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "jsonrpc": "2.0",
        "result": "pong",
        "error": None,
        "id": 100
    }

    # 4.2 Test mcp.ping Method
    payload = {
        "jsonrpc": "2.0",
        "method": "mcp.ping",
        "id": 101
    }
    resp = client.post("/mcp/rpc", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "jsonrpc": "2.0",
        "result": {"status": "ok"},
        "error": None,
        "id": 101
    }

    # 4.3 Test mcp.list_tools Method
    reset_provider()
    mcp_provider = get_provider()

    # Register a dummy test tool
    def add_nums(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    mcp_provider.register_tool(add_nums, name="add_nums", description="Adds two numbers")

    payload = {
        "jsonrpc": "2.0",
        "method": "mcp.list_tools",
        "id": 102
    }
    resp = client.post("/mcp/rpc", json=payload, headers=headers)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["jsonrpc"] == "2.0"
    assert res_data["error"] is None
    assert res_data["id"] == 102
    
    # Check that our registered tool is listed
    tools = res_data["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "add_nums" in tool_names

    # 4.4 Test mcp.call_tool Method
    payload = {
        "jsonrpc": "2.0",
        "method": "mcp.call_tool",
        "params": {
            "name": "add_nums",
            "arguments": {"a": 10, "b": 20}
        },
        "id": 103
    }
    resp = client.post("/mcp/rpc", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "jsonrpc": "2.0",
        "result": {
            "content": [{"type": "text", "text": "30"}]
        },
        "error": None,
        "id": 103
    }

    # 4.5 Test Invalid jsonrpc Version Handling
    payload = {
        "jsonrpc": "1.0",
        "method": "ping",
        "id": 104
    }
    resp = client.post("/mcp/rpc", json=payload, headers=headers)
    assert resp.status_code == 200
    res_json = resp.json()
    assert res_json["error"] is not None
    assert res_json["error"]["code"] == -32600
    assert "Invalid Request" in res_json["error"]["message"]

    # 4.6 Test Non-Existent Method Handling
    payload = {
        "jsonrpc": "2.0",
        "method": "non_existent_method_xyz",
        "id": 105
    }
    resp = client.post("/mcp/rpc", json=payload, headers=headers)
    assert resp.status_code == 200
    res_json = resp.json()
    assert res_json["error"] is not None
    assert res_json["error"]["code"] == -32601
    assert "Method not found" in res_json["error"]["message"]
