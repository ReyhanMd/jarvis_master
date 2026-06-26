"""Symmetric encryption for tokens at rest.

Wraps every value with a versioned prefix (`gcm1:`) so we can:
  - detect plaintext or legacy values (`fer1:`) and migrate/decrypt them transparently
  - decrypt using AES-256-GCM

Key resolution order:
  1. SHAIL_TOKEN_KEY env var (raw key string) — preferred
  2. macOS Keychain — stored under service 'shail_system' and account 'shail_master_key'
  3. Last resort: ephemeral in-process key (logs a loud warning — values
     encrypted with this key are lost on restart)

Public API:
    encrypt(plaintext: str | None) -> str | None
    decrypt(ciphertext: str | None) -> str | None
    is_encrypted(value: str | None) -> bool
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PREFIX = "gcm1:"
_LEGACY_PREFIX = "fer1:"
_master_key: Optional[str] = None


def _get_keychain_key() -> Optional[str]:
    """Retrieve the master key from the macOS Keychain using /usr/bin/security."""
    if sys.platform != "darwin":
        return None
    try:
        res = subprocess.run(
            ["security", "find-generic-password", "-a", "shail_master_key", "-s", "shail_system", "-w"],
            capture_output=True,
            text=True,
            check=True
        )
        key = res.stdout.strip()
        if key:
            return key
    except Exception as e:
        logger.debug("Keychain key retrieval failed: %s", e)
    return None


def _set_keychain_key(key: str) -> bool:
    """Store the master key in the macOS Keychain using /usr/bin/security."""
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(
            ["security", "add-generic-password", "-a", "shail_master_key", "-s", "shail_system", "-w", key, "-U"],
            check=True,
            capture_output=True
        )
        return True
    except Exception as e:
        logger.error("Failed to write key to Keychain: %s", e)
    return False


def _is_testing() -> bool:
    return "pytest" in sys.modules or bool(os.getenv("PYTEST_CURRENT_TEST"))


def _load_master_key() -> str:
    """Resolve the master key. First checks environment, then macOS Keychain, then generates an ephemeral one."""
    global _master_key
    if _master_key is not None:
        return _master_key

    # 1. Environment Variable
    env_key = os.getenv("SHAIL_TOKEN_KEY", "").strip()
    if env_key:
        _master_key = env_key
        return _master_key

    # If we are testing, use the mock/test file in HOME to persist keys across reloads
    if _is_testing():
        p = Path.home() / ".shail" / "token.key"
        if p.exists():
            try:
                _master_key = p.read_text(encoding="utf-8").strip()
                return _master_key
            except Exception:
                pass
        # Generate new test key and save to file
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        new_key = base64.b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(new_key, encoding="utf-8")
        except Exception:
            pass
        _master_key = new_key
        return _master_key

    # 2. macOS Keychain
    keychain_key = _get_keychain_key()
    if keychain_key:
        _master_key = keychain_key
        return _master_key

    # 3. Ephemeral/Generation
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    # Generate 32-byte key base64-encoded string
    new_key = base64.b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")
    if _set_keychain_key(new_key):
        logger.info("Generated new master key and saved to macOS Keychain")
        _master_key = new_key
    else:
        logger.warning(
            "Could not persist key to macOS Keychain — using ephemeral key. "
            "Tokens encrypted this run will NOT decrypt after a restart."
        )
        _master_key = new_key

    return _master_key


def is_encrypted(value: Optional[str]) -> bool:
    return bool(value) and isinstance(value, str) and value.startswith(_PREFIX)


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a string using AES-256-GCM. Already-encrypted or legacy-encrypted values pass through."""
    if not plaintext:
        return plaintext
    if is_encrypted(plaintext):
        return plaintext
    if plaintext.startswith(_LEGACY_PREFIX):
        return plaintext

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        master_key = _load_master_key()
        key_bytes = hashlib.sha256(master_key.encode("utf-8")).digest()
        aesgcm = AESGCM(key_bytes)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        payload = nonce + ct
        encoded = base64.b64encode(payload).decode("ascii")
        return _PREFIX + encoded
    except Exception as exc:
        logger.error("encrypt failed: %s — storing plaintext as a fallback", exc)
        return plaintext


def _decrypt_legacy_fernet(ciphertext: str) -> Optional[str]:
    """Decrypt a legacy fer1: ciphertext using the old token.key or env var."""
    legacy_key = None
    env_key = os.getenv("SHAIL_TOKEN_KEY", "").strip()
    if env_key:
        legacy_key = env_key.encode("utf-8")
    else:
        p = Path.home() / ".shail" / "token.key"
        if p.exists():
            try:
                legacy_key = p.read_bytes().strip()
            except Exception:
                pass

    if not legacy_key:
        try:
            current = _load_master_key()
            legacy_key = current.encode("utf-8")
        except Exception:
            return None

    try:
        from cryptography.fernet import Fernet
        f = Fernet(legacy_key)
        raw_cipher = ciphertext[len(_LEGACY_PREFIX):]
        return f.decrypt(raw_cipher.encode("ascii")).decode("utf-8")
    except Exception as exc:
        logger.error("Legacy Fernet decrypt failed: %s", exc)
        return None


def decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a string. Supports gcm1: (GCM) and fer1: (Legacy Fernet) transparently."""
    if not ciphertext:
        return ciphertext
    if ciphertext.startswith(_PREFIX):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            master_key = _load_master_key()
            key_bytes = hashlib.sha256(master_key.encode("utf-8")).digest()
            aesgcm = AESGCM(key_bytes)
            encoded = ciphertext[len(_PREFIX):]
            payload = base64.b64decode(encoded.encode("ascii"))
            nonce = payload[:12]
            ct = payload[12:]
            pt = aesgcm.decrypt(nonce, ct, None)
            return pt.decode("utf-8")
        except Exception as exc:
            logger.error("decrypt GCM failed: %s", exc)
            return ""
    if ciphertext.startswith(_LEGACY_PREFIX):
        pt = _decrypt_legacy_fernet(ciphertext)
        if pt is not None:
            return pt
        return ""
    return ciphertext  # legacy plaintext


def run_migrations() -> None:
    """Migrate all encrypted columns in metadata.db from fer1: or plaintext to gcm1: AES-256-GCM.
    Then, clean up the legacy ~/.shail/token.key file.
    """
    from apps.shail.settings import get_settings
    db_path = get_settings().sqlite_path
    if not os.path.exists(db_path):
        return

    logger.info("Starting database migration to AES-256-GCM...")
    try:
        # We must make sure parent folder exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Check if tables exist first
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        # 1. Migrate user_settings (openai_api_key, anthropic_api_key, external_api_key)
        if "user_settings" in tables:
            rows = conn.execute("SELECT user_id, openai_api_key, anthropic_api_key, external_api_key FROM user_settings").fetchall()
            for row in rows:
                updates = {}
                for col in ("openai_api_key", "anthropic_api_key", "external_api_key"):
                    val = row[col]
                    if val and not is_encrypted(val):
                        decrypted = decrypt(val)
                        if decrypted:
                            updates[col] = encrypt(decrypted)
                if updates:
                    set_clause = ", ".join(f"{col} = ?" for col in updates)
                    conn.execute(
                        f"UPDATE user_settings SET {set_clause} WHERE user_id = ?",
                        (*updates.values(), row["user_id"])
                    )

        # 2. Migrate mcp_connections (access_token, refresh_token)
        if "mcp_connections" in tables:
            rows = conn.execute("SELECT user_id, provider, access_token, refresh_token FROM mcp_connections").fetchall()
            for row in rows:
                updates = {}
                for col in ("access_token", "refresh_token"):
                    val = row[col]
                    if val and not is_encrypted(val):
                        decrypted = decrypt(val)
                        if decrypted:
                            updates[col] = encrypt(decrypted)
                if updates:
                    set_clause = ", ".join(f"{col} = ?" for col in updates)
                    conn.execute(
                        f"UPDATE mcp_connections SET {set_clause} WHERE user_id = ? AND provider = ?",
                        (*updates.values(), row["user_id"], row["provider"])
                    )

        conn.commit()
        conn.close()
        logger.info("Database migration to AES-256-GCM completed successfully.")

        # 3. Clean up the legacy token.key file
        legacy_key_p = Path.home() / ".shail" / "token.key"
        if legacy_key_p.exists():
            try:
                legacy_key_p.unlink()
                logger.info("Successfully removed legacy key file at %s", legacy_key_p)
            except Exception as e:
                logger.warning("Failed to remove legacy key file: %s", e)

    except Exception as e:
        logger.error("AES-256-GCM migration failed: %s", e)
