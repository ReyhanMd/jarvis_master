"""Persistent local semantic enrichment jobs.

Phase 5 keeps local-file understanding pointer-first. Jobs read only approved
path-index rows, run deterministic extraction first, and optionally enrich with
Ollama when the user has opted in.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
import uuid
from typing import Any, Optional

import httpx

from apps.shail import local_semantics
from apps.shail.settings import get_settings
from shail.memory import path_index

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "local_semantics_ollama_v1"
JOB_STATES = {"pending", "running", "done", "failed", "skipped", "cancelled"}
MODES = {"deterministic", "llm", "hybrid"}
_POLL_SECONDS = 2.0
_WORKER_STARTED = False


def _conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    return local_semantics._conn(db_path)


def init_schema(db_path: Optional[str] = None) -> None:
    with _conn(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS local_file_semantic_jobs (
                job_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                model TEXT,
                limit_files INTEGER NOT NULL,
                force INTEGER DEFAULT 0,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                files_seen INTEGER DEFAULT 0,
                files_processed INTEGER DEFAULT 0,
                files_skipped INTEGER DEFAULT 0,
                files_failed INTEGER DEFAULT 0,
                chunks_processed INTEGER DEFAULT 0,
                entities INTEGER DEFAULT 0,
                facts INTEGER DEFAULT 0,
                tasks INTEGER DEFAULT 0,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                last_error TEXT,
                cancel_requested INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_local_sem_jobs_state
                ON local_file_semantic_jobs(status, updated_at);

            CREATE TABLE IF NOT EXISTS local_file_semantic_chunks (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                path TEXT NOT NULL,
                content_hash TEXT,
                chunk_index INTEGER NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                error TEXT,
                entities INTEGER DEFAULT 0,
                facts INTEGER DEFAULT 0,
                tasks INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_local_sem_chunks_job
                ON local_file_semantic_chunks(job_id, status);
            CREATE INDEX IF NOT EXISTS idx_local_sem_chunks_file_hash
                ON local_file_semantic_chunks(file_id, content_hash);
            """
        )
        con.commit()


def enqueue_job(
    *,
    mode: str = "hybrid",
    limit: int = 500,
    force: bool = False,
    model: Optional[str] = None,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    init_schema(db_path)
    mode = mode if mode in MODES else "hybrid"
    settings = get_settings()
    model = model or settings.shail_local_semantic_model or settings.ollama_chat_model
    now = time.time()
    with _conn(db_path) as con:
        row = con.execute(
            """SELECT * FROM local_file_semantic_jobs
               WHERE status IN ('pending', 'running') AND mode = ? AND model = ? AND force = ?
               ORDER BY created_at DESC LIMIT 1""",
            (mode, model, 1 if force else 0),
        ).fetchone()
        if row:
            return _job_row(row)
        job_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO local_file_semantic_jobs
               (job_id, mode, status, model, limit_files, force, max_attempts, created_at, updated_at)
               VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                mode,
                model,
                int(limit),
                1 if force else 0,
                max(1, settings.shail_local_semantic_max_attempts),
                now,
                now,
            ),
        )
        con.commit()
    return get_job(job_id, db_path=db_path) or {"job_id": job_id, "status": "pending"}


def get_job(job_id: str, *, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    init_schema(db_path)
    with _conn(db_path) as con:
        row = con.execute("SELECT * FROM local_file_semantic_jobs WHERE job_id = ?", (job_id,)).fetchone()
    return _job_row(row) if row else None


def cancel_job(job_id: str, *, db_path: Optional[str] = None) -> dict[str, Any]:
    init_schema(db_path)
    now = time.time()
    with _conn(db_path) as con:
        row = con.execute("SELECT status FROM local_file_semantic_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return {"job_id": job_id, "status": "missing"}
        if row["status"] in {"done", "failed", "skipped", "cancelled"}:
            return get_job(job_id, db_path=db_path) or {"job_id": job_id, "status": row["status"]}
        con.execute(
            "UPDATE local_file_semantic_jobs SET cancel_requested = 1, status = 'cancelled', updated_at = ?, completed_at = ? WHERE job_id = ?",
            (now, now, job_id),
        )
        con.commit()
    return get_job(job_id, db_path=db_path) or {"job_id": job_id, "status": "cancelled"}


def queue_stats(*, db_path: Optional[str] = None) -> dict[str, Any]:
    init_schema(db_path)
    settings = get_settings()
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT status, COUNT(*) AS n FROM local_file_semantic_jobs GROUP BY status"
        ).fetchall()
        latest = con.execute(
            "SELECT MAX(completed_at) FROM local_file_semantic_jobs WHERE status = 'done'"
        ).fetchone()[0]
        active = con.execute(
            "SELECT * FROM local_file_semantic_jobs WHERE status IN ('pending', 'running') ORDER BY created_at LIMIT 1"
        ).fetchone()
    counts = {r["status"]: r["n"] for r in rows}
    return {
        "pending": int(counts.get("pending", 0)),
        "running": int(counts.get("running", 0)),
        "failed": int(counts.get("failed", 0)),
        "done": int(counts.get("done", 0)),
        "cancelled": int(counts.get("cancelled", 0)),
        "latest_llm_enriched_at": latest,
        "active_model": settings.shail_local_semantic_model or settings.ollama_chat_model,
        "llm_enabled": bool(settings.shail_local_semantic_llm),
        "active_job": _job_row(active) if active else None,
    }


async def process_next_pending(*, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    init_schema(db_path)
    with _conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM local_file_semantic_jobs WHERE status = 'pending' ORDER BY created_at LIMIT 1"
        ).fetchone()
    if not row:
        return None
    job = _job_row(row)
    await process_job(job["job_id"], db_path=db_path)
    return get_job(job["job_id"], db_path=db_path)


async def process_job(job_id: str, *, db_path: Optional[str] = None) -> dict[str, Any]:
    init_schema(db_path)
    job = get_job(job_id, db_path=db_path)
    if not job:
        return {"job_id": job_id, "status": "missing"}
    if job["status"] in {"done", "failed", "skipped", "cancelled"}:
        return job

    _mark_job(job_id, "running", db_path=db_path)
    settings = get_settings()
    path_db = settings.path_index_db
    semantics_db = db_path or local_semantics._db_path()
    rows = local_semantics._allowed_rows(path_db, limit=int(job["limit"]))
    _update_job(job_id, {"files_seen": len(rows)}, db_path=db_path)
    warnings: list[str] = []
    totals = {"files_processed": 0, "files_skipped": 0, "files_failed": 0, "chunks_processed": 0, "entities": 0, "facts": 0, "tasks": 0}

    if not rows:
        warnings.append("No approved local files were available for semantic extraction.")
        _finish_job(job_id, "skipped", totals, warnings, db_path=db_path)
        return get_job(job_id, db_path=db_path) or {"job_id": job_id, "status": "skipped"}

    for row in rows:
        if _cancel_requested(job_id, db_path=db_path):
            _finish_job(job_id, "cancelled", totals, warnings, db_path=db_path)
            return get_job(job_id, db_path=db_path) or {"job_id": job_id, "status": "cancelled"}
        try:
            result = await _process_file(job, row, semantics_db=semantics_db)
            for key in totals:
                totals[key] += int(result.get(key, 0))
            warnings.extend(result.get("warnings") or [])
            _update_job(job_id, totals, warnings=warnings, db_path=db_path)
        except Exception as exc:
            totals["files_failed"] += 1
            warnings.append(f"{row.get('path')}: {exc}")
            local_semantics.mark_llm_error(
                row,
                model=job["model"],
                extractor_version=EXTRACTOR_VERSION,
                error=str(exc),
                semantics_db=semantics_db,
            )
            _update_job(job_id, totals, warnings=warnings, last_error=str(exc), db_path=db_path)

    final = "done" if totals["files_processed"] or totals["files_skipped"] else "failed"
    _finish_job(job_id, final, totals, warnings, db_path=db_path)
    return get_job(job_id, db_path=db_path) or {"job_id": job_id, "status": final}


async def _process_file(job: dict[str, Any], row: dict[str, Any], *, semantics_db: str) -> dict[str, Any]:
    settings = get_settings()
    out = {"files_processed": 0, "files_skipped": 0, "files_failed": 0, "chunks_processed": 0, "entities": 0, "facts": 0, "tasks": 0, "warnings": []}
    file_id = row.get("id") or row.get("path")
    current = path_index.get_by_id(settings.path_index_db, file_id) if row.get("id") else path_index.get_by_path(settings.path_index_db, row.get("path") or "")
    if not current or current.get("deleted_at") or path_index.is_denied(settings.path_index_db, current.get("path") or ""):
        out["files_skipped"] = 1
        out["warnings"].append(f"Skipped denied or deleted file: {row.get('path')}")
        return out

    text, source = local_semantics._read_text(row, read_cap_bytes=settings.shail_local_files_read_cap_bytes)
    if not text.strip():
        out["files_skipped"] = 1
        out["warnings"].append(f"Skipped empty or unreadable file: {row.get('path')}")
        return out

    mode = job["mode"]
    if mode in {"deterministic", "hybrid"}:
        extracted = local_semantics.extract_text_semantics(
            file_id=file_id,
            path=row.get("path") or "",
            content_hash=row.get("content_hash"),
            text=text,
        )
        with local_semantics._conn(semantics_db) as con:
            local_semantics._persist(con, row, extracted, status="complete", error=None, source=source)
            con.commit()
        out["entities"] += len(extracted["entities"])
        out["facts"] += len(extracted["facts"])
        out["tasks"] += len(extracted["tasks"])

    if mode in {"llm", "hybrid"}:
        if not settings.shail_local_semantic_llm:
            out["warnings"].append("Ollama semantic enrichment is not enabled.")
            if mode == "llm":
                out["files_skipped"] = 1
                return out
        else:
            llm = await _enrich_with_ollama(job, row, text, semantics_db=semantics_db)
            for key in ("chunks_processed", "entities", "facts", "tasks"):
                out[key] += int(llm.get(key, 0))
            out["warnings"].extend(llm.get("warnings") or [])

    out["files_processed"] = 1
    return out


async def _enrich_with_ollama(job: dict[str, Any], row: dict[str, Any], text: str, *, semantics_db: str) -> dict[str, Any]:
    settings = get_settings()
    file_id = row.get("id") or row.get("path")
    max_chars = max(1000, int(settings.shail_local_semantic_max_file_chars))
    text = text[:max_chars]
    chunks = _chunk_text(
        text,
        max_chars=_chunk_char_budget(settings.shail_local_semantic_context_tokens),
        overlap=max(0, int(settings.shail_local_semantic_chunk_overlap_chars)),
    )
    merged = {"entities": [], "facts": [], "tasks": []}
    warnings: list[str] = []
    processed = 0
    for idx, chunk in enumerate(chunks):
        current = path_index.get_by_id(settings.path_index_db, file_id) if row.get("id") else path_index.get_by_path(settings.path_index_db, row.get("path") or "")
        if not current or current.get("content_hash") != row.get("content_hash"):
            warnings.append(f"Skipped stale file while enriching: {row.get('path')}")
            break
        if current.get("deleted_at") or path_index.is_denied(settings.path_index_db, current.get("path") or ""):
            warnings.append(f"Stopped enrichment for denied or deleted file: {row.get('path')}")
            break
        chunk_id = _chunk_id(job["job_id"], file_id, idx)
        _record_chunk(chunk_id, job, row, idx, "running", db_path=semantics_db)
        try:
            payload = await _call_ollama_json(chunk, row=row, model=job["model"])
            normalized = _normalize_payload(payload, row=row, chunk_index=idx, model=job["model"])
            for key in merged:
                merged[key].extend(normalized[key])
            processed += 1
            _record_chunk(chunk_id, job, row, idx, "done", counts={k: len(normalized[k]) for k in merged}, db_path=semantics_db)
        except Exception as exc:
            warnings.append(f"Ollama chunk failed for {row.get('path')}: {exc}")
            _record_chunk(chunk_id, job, row, idx, "failed", error=str(exc), db_path=semantics_db)

    if processed:
        counts = local_semantics.persist_llm_extracted(
            row,
            merged,
            model=job["model"],
            extractor_version=EXTRACTOR_VERSION,
            chunk_count=processed,
            semantics_db=semantics_db,
        )
    else:
        counts = {"entities": 0, "facts": 0, "tasks": 0}
        if warnings:
            local_semantics.mark_llm_error(
                row,
                model=job["model"],
                extractor_version=EXTRACTOR_VERSION,
                error="; ".join(warnings)[:500],
                semantics_db=semantics_db,
            )
    return {"chunks_processed": processed, **counts, "warnings": warnings}


async def _call_ollama_json(chunk: str, *, row: dict[str, Any], model: str) -> dict[str, Any]:
    settings = get_settings()
    prompt = _prompt(chunk, path=row.get("path") or "")
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "num_ctx": int(settings.shail_local_semantic_context_tokens),
            "num_thread": int(settings.ollama_num_thread),
        },
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(f"{settings.ollama_base_url.rstrip('/')}/api/generate", json=body)
        resp.raise_for_status()
        raw = resp.json().get("response") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            raise ValueError("Ollama returned invalid JSON")
        return json.loads(match.group(0))


def _prompt(chunk: str, *, path: str) -> str:
    return (
        "Extract structured semantic objects from this approved local file chunk.\n"
        "Return strict JSON only with keys: entities, facts, tasks.\n"
        "Do not include raw full text. Use short source_span excerpts only.\n"
        "Entity item: {\"label\":\"...\",\"entity_type\":\"person|organization|date|metric|other\",\"source_span\":\"...\",\"confidence\":\"EXTRACTED|INFERRED|AMBIGUOUS\"}\n"
        "Fact item: {\"entity\":\"...\",\"attribute\":\"...\",\"value\":\"...\",\"value_num\":null,\"unit\":null,\"period\":null,\"source_span\":\"...\",\"confidence\":\"EXTRACTED|INFERRED|AMBIGUOUS\"}\n"
        "Task item: {\"text\":\"...\",\"status\":\"open|done|unknown\",\"due_date\":null,\"source_span\":\"...\",\"confidence\":\"EXTRACTED|INFERRED|AMBIGUOUS\"}\n"
        f"File path: {path}\n"
        "Chunk:\n"
        f"{chunk}"
    )


def _normalize_payload(payload: dict[str, Any], *, row: dict[str, Any], chunk_index: int, model: str) -> dict[str, list[dict[str, Any]]]:
    file_id = row.get("id") or row.get("path")
    path = row.get("path") or ""
    content_hash = row.get("content_hash")
    meta = {
        "extractor": "ollama",
        "model": model,
        "chunk_index": chunk_index,
        "content_hash": content_hash,
        "source": "approved_local_file",
    }
    out = {"entities": [], "facts": [], "tasks": []}
    for item in _items(payload.get("entities")):
        label = local_semantics._clean(str(item.get("label") or ""), limit=120)
        if not label:
            continue
        etype = str(item.get("entity_type") or "other").lower()
        out["entities"].append({
            "id": local_semantics._stable_id("entity", "ollama", file_id, etype, label.lower(), chunk_index),
            "file_id": file_id,
            "path": path,
            "entity_type": etype if etype in {"person", "organization", "date", "metric", "other"} else "other",
            "label": label,
            "source_span": local_semantics._clean(str(item.get("source_span") or label), limit=220),
            "confidence": _confidence(item.get("confidence")),
            "metadata": meta,
        })
    for item in _items(payload.get("facts")):
        value = local_semantics._clean(str(item.get("value") or ""), limit=160)
        attr = local_semantics._clean(str(item.get("attribute") or "fact").lower(), limit=80)
        entity = local_semantics._clean(str(item.get("entity") or "Document"), limit=120)
        if not value and not attr:
            continue
        out["facts"].append({
            "id": local_semantics._stable_id("fact", "ollama", file_id, entity.lower(), attr, value, item.get("period"), chunk_index),
            "file_id": file_id,
            "path": path,
            "entity": entity,
            "attribute": attr,
            "value": value,
            "value_num": _number_or_none(item.get("value_num")),
            "unit": item.get("unit") if isinstance(item.get("unit"), str) else None,
            "period": item.get("period") if isinstance(item.get("period"), str) else None,
            "source_span": local_semantics._clean(str(item.get("source_span") or value), limit=220),
            "confidence": _confidence(item.get("confidence")),
            "metadata": meta,
        })
    for item in _items(payload.get("tasks")):
        text = local_semantics._clean(str(item.get("text") or ""), limit=260)
        if not text:
            continue
        out["tasks"].append({
            "id": local_semantics._stable_id("task", "ollama", file_id, text.lower(), chunk_index),
            "file_id": file_id,
            "path": path,
            "text": text,
            "status": str(item.get("status") or "unknown").lower(),
            "due_date": item.get("due_date") if isinstance(item.get("due_date"), str) else None,
            "source_span": local_semantics._clean(str(item.get("source_span") or text), limit=220),
            "confidence": _confidence(item.get("confidence")),
            "metadata": meta,
        })
    return out


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in (value or []) if isinstance(item, dict)]


def _confidence(value: Any) -> str:
    value = str(value or "").upper()
    return value if value in {"EXTRACTED", "INFERRED", "AMBIGUOUS"} else "INFERRED"


def _number_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _chunk_char_budget(context_tokens: int) -> int:
    # Conservative budget: reserve prompt/JSON room and avoid full 128k windows
    # by default. Approx 3.5 chars/token.
    return max(4000, min(60000, int(context_tokens * 3.5 * 0.45)))


def _chunk_text(text: str, *, max_chars: int, overlap: int) -> list[str]:
    text = text or ""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _chunk_id(job_id: str, file_id: str, chunk_index: int) -> str:
    return f"{job_id}:{file_id}:{chunk_index}"


def _record_chunk(
    chunk_id: str,
    job: dict[str, Any],
    row: dict[str, Any],
    chunk_index: int,
    status: str,
    *,
    counts: Optional[dict[str, int]] = None,
    error: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    init_schema(db_path)
    now = time.time()
    counts = counts or {}
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO local_file_semantic_chunks
               (id, job_id, file_id, path, content_hash, chunk_index, status, attempts, error,
                entities, facts, tasks, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 status = excluded.status,
                 attempts = local_file_semantic_chunks.attempts + 1,
                 error = excluded.error,
                 entities = excluded.entities,
                 facts = excluded.facts,
                 tasks = excluded.tasks,
                 updated_at = excluded.updated_at""",
            (
                chunk_id,
                job["job_id"],
                row.get("id") or row.get("path"),
                row.get("path") or "",
                row.get("content_hash"),
                chunk_index,
                status,
                (error or "")[:500] if error else None,
                int(counts.get("entities", 0)),
                int(counts.get("facts", 0)),
                int(counts.get("tasks", 0)),
                now,
                now,
            ),
        )
        con.commit()


def _mark_job(job_id: str, status: str, *, db_path: Optional[str] = None) -> None:
    _update_job(job_id, {"status": status, "attempts": "attempts + 1"}, db_path=db_path)


def _update_job(
    job_id: str,
    values: dict[str, Any],
    *,
    warnings: Optional[list[str]] = None,
    last_error: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    init_schema(db_path)
    sets = []
    params: list[Any] = []
    for key, value in values.items():
        if key == "attempts" and value == "attempts + 1":
            sets.append("attempts = attempts + 1")
            continue
        sets.append(f"{key} = ?")
        params.append(value)
    if warnings is not None:
        sets.append("warnings_json = ?")
        params.append(json.dumps(_dedupe(warnings))[:12000])
    if last_error is not None:
        sets.append("last_error = ?")
        params.append(last_error[:500])
    sets.append("updated_at = ?")
    params.append(time.time())
    params.append(job_id)
    with _conn(db_path) as con:
        con.execute(f"UPDATE local_file_semantic_jobs SET {', '.join(sets)} WHERE job_id = ?", params)
        con.commit()


def _finish_job(job_id: str, status: str, totals: dict[str, int], warnings: list[str], *, db_path: Optional[str] = None) -> None:
    values = {"status": status, "completed_at": time.time(), **totals}
    _update_job(job_id, values, warnings=warnings, db_path=db_path)


def _cancel_requested(job_id: str, *, db_path: Optional[str] = None) -> bool:
    with _conn(db_path) as con:
        row = con.execute("SELECT cancel_requested, status FROM local_file_semantic_jobs WHERE job_id = ?", (job_id,)).fetchone()
    return bool(row and (row["cancel_requested"] or row["status"] == "cancelled"))


def _job_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["job_id"] = data.get("job_id")
    data["limit"] = data.get("limit_files")
    data["force"] = bool(data.get("force"))
    data["warnings"] = json.loads(data.get("warnings_json") or "[]")
    return data


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


async def worker_loop(poll_interval_seconds: float = _POLL_SECONDS) -> None:
    logger.info("local semantic enrichment worker started")
    while True:
        try:
            await process_next_pending()
            await asyncio.sleep(poll_interval_seconds)
        except asyncio.CancelledError:
            logger.info("local semantic enrichment worker stopping")
            raise
        except Exception as exc:
            logger.exception("local semantic enrichment worker error: %s", exc)
            await asyncio.sleep(poll_interval_seconds)


def start_worker() -> Optional[asyncio.Task]:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return None
    _WORKER_STARTED = True
    init_schema()
    return asyncio.create_task(worker_loop())
