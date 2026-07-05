"""Pytest fixtures for SHAIL retrieval-evolution test suite.

Local-first: no real Chroma, no real Ollama. SQLite uses tmp_path.
Embeddings/LLM mocked at httpx layer for deterministic runs.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure repo root on path when invoked as bare `pytest apps/shail/tests`.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Pre-import memory.rag so pytest monkeypatch can resolve its attributes
import shail.memory.rag


FIXTURES = Path(__file__).parent / "fixtures"
CAPTURES_DIR = FIXTURES / "captures"
GOLDEN_DIR = FIXTURES / "golden"


@pytest.fixture
def tmp_sqlite(tmp_path: Path) -> Path:
    """Per-test SQLite path. Disposed at teardown by tmp_path."""
    return tmp_path / "test.db"


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch):
    """Point sqlite_path at a tmp file via a patched Settings singleton.

    Pydantic Field(default=os.getenv(...)) captures env at class-def time, so
    setting SHAIL_SQLITE post-import has no effect. Override the cached
    Settings instance directly. Auto-restored on teardown.
    """
    db = tmp_path / "test.db"
    import apps.shail.settings as s
    fake = s.Settings(sqlite_path=str(db))
    monkeypatch.setattr(s, "_settings", fake)
    yield db
    monkeypatch.setattr(s, "_settings", None)


@pytest.fixture
def captures() -> dict:
    """Load all capture fixtures keyed by filename stem."""
    out = {}
    for f in sorted(CAPTURES_DIR.glob("*.json")):
        out[f.stem] = json.loads(f.read_text())
    return out


@pytest.fixture
def golden_snapshot(request):
    """Compare a value to its golden snapshot or write the snapshot if missing.

    Set SHAIL_REFRESH_GOLDEN=1 to regenerate. Defaults to strict diff.
    """
    test_name = request.node.name
    path = GOLDEN_DIR / f"{test_name}.json"

    def _check(value):
        serialized = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
        refresh = os.getenv("SHAIL_REFRESH_GOLDEN", "0") == "1"
        if not path.exists() or refresh:
            path.write_text(serialized)
            if not refresh:
                pytest.skip(f"Golden written: {path.name}. Re-run to verify.")
            return
        expected = path.read_text()
        assert serialized == expected, (
            f"Golden snapshot mismatch for {test_name}. "
            f"Set SHAIL_REFRESH_GOLDEN=1 to update. Path: {path}"
        )

    return _check


@pytest.fixture(autouse=True)
def reset_telemetry():
    """Clean counters between tests so order does not matter."""
    from apps.shail import telemetry
    telemetry.reset()
    yield
    telemetry.reset()


@pytest.fixture(autouse=True)
def clean_db_pool():
    """Reset the global database connection pool between tests to avoid stale tmp paths."""
    from apps.shail.db import close_db_pool
    close_db_pool()
    yield
    close_db_pool()
