from __future__ import annotations

from pathlib import Path
import asyncio
import sys
import types


def _setup(tmp_path: Path, monkeypatch):
    from apps.shail.settings import get_settings

    db_path = str(tmp_path / "sem_jobs.sqlite3")
    root = tmp_path / "approved"
    root.mkdir()
    settings = get_settings()
    monkeypatch.setattr(settings, "path_index_db", db_path, raising=False)
    monkeypatch.setattr(settings, "sqlite_path", db_path, raising=False)
    monkeypatch.setattr(settings, "scan_roots", [str(root)], raising=False)
    monkeypatch.setattr(settings, "shail_local_files_read_cap_bytes", 100_000, raising=False)
    monkeypatch.setattr(settings, "shail_local_semantic_llm", True, raising=False)
    monkeypatch.setattr(settings, "shail_local_semantic_model", "test-gemma", raising=False)
    monkeypatch.setattr(settings, "shail_local_semantic_context_tokens", 8192, raising=False)
    monkeypatch.setattr(settings, "shail_local_semantic_max_file_chars", 50_000, raising=False)
    monkeypatch.setattr(settings, "shail_local_semantic_chunk_overlap_chars", 100, raising=False)
    monkeypatch.setattr(settings, "shail_local_semantic_max_attempts", 2, raising=False)
    return db_path, root


def _scan(db_path: str, root: Path):
    from shail.memory import path_index

    path_index.scan(db_path, roots=[str(root)])


async def _fake_ollama(chunk: str, *, row: dict, model: str):
    return {
        "entities": [
            {"label": "Alpha Labs", "entity_type": "organization", "source_span": "Alpha Labs", "confidence": "EXTRACTED"}
        ],
        "facts": [
            {
                "entity": "Alpha Labs",
                "attribute": "revenue",
                "value": "$7M",
                "value_num": 7000000,
                "unit": "USD",
                "period": "2026",
                "source_span": "revenue is $7M",
                "confidence": "EXTRACTED",
            }
        ],
        "tasks": [
            {"text": "Send final deck", "status": "open", "due_date": "2026-07-01", "source_span": "Send final deck", "confidence": "INFERRED"}
        ],
    }


def test_semantic_job_hybrid_enriches_with_ollama_atoms(tmp_path, monkeypatch):
    from apps.shail import local_semantics, local_semantics_jobs

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "alpha.md").write_text("Alpha Labs revenue is $7M. TODO: Send final deck.", encoding="utf-8")
    _scan(db_path, root)
    monkeypatch.setattr(local_semantics_jobs, "_call_ollama_json", _fake_ollama)

    job = local_semantics_jobs.enqueue_job(mode="hybrid", limit=10, force=False, db_path=db_path)
    done = asyncio.run(local_semantics_jobs.process_job(job["job_id"], db_path=db_path))
    found = local_semantics.search("Alpha", semantics_db=db_path, limit=50)

    assert done["status"] == "done"
    assert done["chunks_processed"] == 1
    assert any(f["metadata"].get("extractor") == "ollama" for f in found["facts"])
    assert any(t["metadata"].get("model") == "test-gemma" for t in found["tasks"])


def test_semantic_job_skips_denied_and_deleted_files(tmp_path, monkeypatch):
    from apps.shail import local_semantics, local_semantics_jobs
    from shail.memory import path_index

    db_path, root = _setup(tmp_path, monkeypatch)
    blocked = root / "private"
    blocked.mkdir()
    allowed = root / "allowed.md"
    denied = blocked / "secret.md"
    gone = root / "gone.md"
    allowed.write_text("Allowed Revenue is $1M.", encoding="utf-8")
    denied.write_text("Secret Revenue is $99M.", encoding="utf-8")
    gone.write_text("Gone Revenue is $5M.", encoding="utf-8")
    path_index.add_deny_path(db_path, str(blocked), reason="private")
    _scan(db_path, root)
    gone.unlink()
    _scan(db_path, root)
    monkeypatch.setattr(local_semantics_jobs, "_call_ollama_json", _fake_ollama)

    job = local_semantics_jobs.enqueue_job(mode="hybrid", limit=50, force=True, db_path=db_path)
    asyncio.run(local_semantics_jobs.process_job(job["job_id"], db_path=db_path))
    found = local_semantics.search("Revenue", semantics_db=db_path, limit=50)
    paths = {item["path"] for item in [*found["facts"], *found["entities"], *found["tasks"]]}

    assert str(allowed) in paths
    assert str(denied) not in paths
    assert str(gone) not in paths


def test_semantic_job_llm_disabled_skips_without_breaking_deterministic(tmp_path, monkeypatch):
    from apps.shail import local_semantics, local_semantics_jobs
    from apps.shail.settings import get_settings

    db_path, root = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(get_settings(), "shail_local_semantic_llm", False, raising=False)
    (root / "memo.md").write_text("Revenue is $2M.", encoding="utf-8")
    _scan(db_path, root)

    job = local_semantics_jobs.enqueue_job(mode="hybrid", limit=10, force=False, db_path=db_path)
    done = asyncio.run(local_semantics_jobs.process_job(job["job_id"], db_path=db_path))
    found = local_semantics.search("$2M", semantics_db=db_path, limit=50)

    assert done["status"] == "done"
    assert any("not enabled" in w for w in done["warnings"])
    assert any(f["value"] == "$2M" for f in found["facts"])


def test_semantic_job_invalid_ollama_json_marks_failure_without_corrupting_rows(tmp_path, monkeypatch):
    from apps.shail import local_semantics, local_semantics_jobs

    async def bad_ollama(chunk: str, *, row: dict, model: str):
        raise ValueError("invalid json")

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "memo.md").write_text("Revenue is $3M.", encoding="utf-8")
    _scan(db_path, root)
    monkeypatch.setattr(local_semantics_jobs, "_call_ollama_json", bad_ollama)

    job = local_semantics_jobs.enqueue_job(mode="hybrid", limit=10, force=True, db_path=db_path)
    done = asyncio.run(local_semantics_jobs.process_job(job["job_id"], db_path=db_path))
    found = local_semantics.search("$3M", semantics_db=db_path, limit=50)

    assert done["status"] == "done"
    assert done["chunks_processed"] == 0
    assert any("invalid json" in w for w in done["warnings"])
    assert any(f["value"] == "$3M" for f in found["facts"])


def test_semantic_job_cancel_endpoint_shape(tmp_path, monkeypatch):
    auth_api = types.ModuleType("apps.shail.auth_api")
    auth_api.get_current_user = lambda: "test-user"
    monkeypatch.setitem(sys.modules, "apps.shail.auth_api", auth_api)

    from apps.shail.local_rag_api import (
        LocalSemanticsJobRequest,
        local_rag_semantics_job_cancel,
        local_rag_semantics_job_create,
        local_rag_semantics_job_get,
    )

    db_path, root = _setup(tmp_path, monkeypatch)
    (root / "api.md").write_text("Revenue is $4M.", encoding="utf-8")
    _scan(db_path, root)

    created = asyncio.run(local_rag_semantics_job_create(
        LocalSemanticsJobRequest(mode="hybrid", limit=10, force=False, model="test-gemma"),
        user_id="test-user",
    ))
    fetched = asyncio.run(local_rag_semantics_job_get(created.job_id, user_id="test-user"))
    cancelled = asyncio.run(local_rag_semantics_job_cancel(created.job_id, user_id="test-user"))

    assert fetched.job_id == created.job_id
    assert cancelled.status == "cancelled"
