"""Immutable capture artifacts, materializations, and replay orchestration."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

from apps.shail.settings import get_settings
from shail.memory.rag import ingest
from shail.memory.vector_store import EmbeddingRecord

ARTIFACT_SCHEMA_VERSION = 1
DEFAULT_COMPLETENESS = "complete"
REPLAY_MODE_SHADOW = "shadow"
REPLAY_MODE_PROMOTE = "promote"
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_PROMOTED = "promoted"


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    memory_id: str
    artifact_seq: int
    artifact_kind: str
    event_type: str
    source_app: str
    source_url: str
    conversation_id: Optional[str]
    mime_type: Optional[str]
    schema_version: int
    sha256: str
    byte_size: int
    storage_uri: str
    completeness: str
    captured_at: str
    created_at: str
    metadata_json: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _settings():
    return get_settings()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_settings().sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def _ensure_parent_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _artifact_root() -> Path:
    root = Path(_settings().capture_artifact_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    (root / "materializations").mkdir(parents=True, exist_ok=True)
    return root


def _ensure_column(con: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_capture_store() -> None:
    from apps.shail.blueprints import init_blueprint_db

    path = _settings().sqlite_path
    _ensure_parent_dir(path)
    _artifact_root()
    init_blueprint_db()
    with _connect() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS capture_artifacts (
                artifact_id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                artifact_seq INTEGER NOT NULL,
                parent_artifact_id TEXT,
                source_app TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source_url TEXT NOT NULL,
                conversation_id TEXT,
                artifact_kind TEXT NOT NULL,
                mime_type TEXT,
                schema_version INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                storage_uri TEXT NOT NULL,
                completeness TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_capture_artifacts_memory_seq_kind
            ON capture_artifacts(memory_id, artifact_seq, artifact_kind);
            CREATE INDEX IF NOT EXISTS idx_capture_artifacts_memory_id
            ON capture_artifacts(memory_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS memory_materializations (
                materialization_id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                extractor_bundle_version TEXT NOT NULL,
                options_hash TEXT NOT NULL,
                content_type TEXT NOT NULL,
                normalized_text_uri TEXT,
                structured_uri TEXT,
                status TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                validation_json TEXT,
                created_at TEXT NOT NULL,
                promoted_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_materializations_identity
            ON memory_materializations(artifact_id, extractor_bundle_version, options_hash);
            CREATE INDEX IF NOT EXISTS idx_materializations_memory
            ON memory_materializations(memory_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS materialization_chunks (
                chunk_row_id TEXT PRIMARY KEY,
                materialization_id TEXT NOT NULL,
                memory_id TEXT NOT NULL,
                chunk_key TEXT NOT NULL,
                chunk_type TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                parent_chunk_key TEXT,
                group_key TEXT,
                never_split INTEGER NOT NULL DEFAULT 0,
                chunk_hash TEXT NOT NULL,
                vector_id TEXT,
                locator_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                text_uri TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_materialization_chunks_identity
            ON materialization_chunks(materialization_id, chunk_key);
            CREATE INDEX IF NOT EXISTS idx_materialization_chunks_memory
            ON materialization_chunks(memory_id, materialization_id, ordinal);

            CREATE TABLE IF NOT EXISTS replay_jobs (
                replay_job_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                scope_ref TEXT NOT NULL,
                bundle_version TEXT NOT NULL,
                options_hash TEXT NOT NULL,
                validation_json TEXT,
                prior_active_materialization_id TEXT,
                promoted_materialization_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS replay_job_items (
                replay_job_item_id TEXT PRIMARY KEY,
                replay_job_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                memory_id TEXT NOT NULL,
                status TEXT NOT NULL,
                materialization_id TEXT,
                validation_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_replay_job_items_job
            ON replay_job_items(replay_job_id, created_at);
            """
        )
        _ensure_column(con, "blueprints", "artifact_id", "artifact_id TEXT")
        _ensure_column(con, "blueprints", "materialization_id", "materialization_id TEXT")
        _ensure_column(con, "blueprints", "extractor_bundle_version", "extractor_bundle_version TEXT")
        _ensure_column(con, "blueprints", "updated_at", "updated_at TEXT")
        _ensure_column(con, "memory_facts", "artifact_id", "artifact_id TEXT")
        _ensure_column(con, "memory_facts", "materialization_id", "materialization_id TEXT")
        _ensure_column(con, "memory_facts", "extractor_bundle_version", "extractor_bundle_version TEXT")
        _ensure_column(con, "memory_facts", "fact_source_type", "fact_source_type TEXT")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_blob(subdir: str, stem: str, suffix: str, payload: bytes) -> str:
    root = _artifact_root()
    digest = _sha256_bytes(payload)
    path = root / subdir / digest[:2] / f"{stem}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return str(path)


def _artifact_kind_for(event_type: str, source_url: str, raw_payload: Optional[dict]) -> tuple[str, str, str]:
    url = (source_url or "").lower()
    payload = raw_payload or {}
    if event_type == "ai_conversation":
        return "normalized_text_capture", "application/json", DEFAULT_COMPLETENESS
    if event_type == "pdf_doc":
        if payload.get("pdf_bytes_b64"):
            return "pdf_document", "application/pdf", DEFAULT_COMPLETENESS
        return "pdf_stub", "application/json", "stub"
    if "github.com" in url and "/pull/" in url:
        return "github_diff_capture", "application/json", DEFAULT_COMPLETENESS
    if payload.get("artifact_kind"):
        return str(payload["artifact_kind"]), str(payload.get("mime_type") or "application/json"), str(payload.get("completeness") or DEFAULT_COMPLETENESS)
    if payload.get("html_tables"):
        return "html_table_capture", "application/json", DEFAULT_COMPLETENESS
    if payload.get("dashboard_cards"):
        return "dashboard_capture", "application/json", DEFAULT_COMPLETENESS
    if payload.get("svg_charts"):
        return "chart_capture", "application/json", DEFAULT_COMPLETENESS
    return "legacy_text_snapshot", "application/json", DEFAULT_COMPLETENESS


def _extract_transcript_turns(text: str, latest_user: str = "") -> list[dict]:
    raw = (text or "").strip()
    if not raw:
        return [{"user": latest_user or "", "assistant": ""}]
    chunks = [part.strip() for part in raw.split("\n\n---\n\n") if part.strip()]
    turns: list[dict] = []
    for idx, part in enumerate(chunks):
        if part.startswith("User: ") and "\n\nAssistant: " in part:
            user, assistant = part.split("\n\nAssistant: ", 1)
            turns.append({
                "user": user.removeprefix("User: ").strip(),
                "assistant": assistant.strip(),
            })
        else:
            turns.append({
                "user": latest_user.strip() if idx == len(chunks) - 1 else "",
                "assistant": part.strip(),
            })
    if not turns:
        turns.append({"user": latest_user or "", "assistant": raw})
    return turns


def build_capture_payload(
    req: Any,
    *,
    content: str,
    summary: str,
    raw_payload: Optional[dict] = None,
) -> dict:
    raw_payload = dict(raw_payload or {})
    if getattr(req, "eventType", "") == "ai_conversation":
        turns = raw_payload.get("turns")
        if not isinstance(turns, list) or not turns:
            turns = _extract_transcript_turns(getattr(req, "assistantText", "") or "", getattr(req, "userText", "") or "")
        return {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "memory_id": req.customId,
            "source_app": req.sourceApp,
            "event_type": req.eventType,
            "conversation_id": getattr(req, "conversationId", None),
            "selector_version": raw_payload.get("selector_version"),
            "latest_user_text": getattr(req, "userText", "") or "",
            "rendered_transcript": getattr(req, "assistantText", "") or "",
            "normalized_text": content,
            "summary": summary,
            "turns": turns,
        }
    if getattr(req, "eventType", "") == "pdf_doc":
        return {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "memory_id": req.customId,
            "source_app": req.sourceApp,
            "event_type": req.eventType,
            "normalized_text": content,
            "summary": summary,
            "source_url": req.sourceUrl,
            "pdf_bytes_b64": raw_payload.get("pdf_bytes_b64"),
            "content_stub": getattr(req, "pageContent", "") or "",
        }
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "memory_id": req.customId,
        "source_app": req.sourceApp,
        "event_type": req.eventType,
        "normalized_text": content,
        "summary": summary,
        "title": getattr(req, "title", None),
        "source_url": req.sourceUrl,
        "page_content": getattr(req, "pageContent", None),
        "html_snapshot": raw_payload.get("html_snapshot"),
        "visible_text_checksum": raw_payload.get("visible_text_checksum"),
        "capture_hints": raw_payload.get("capture_hints") or {},
        "dom_language": raw_payload.get("dom_language"),
        "github_diff": raw_payload.get("github_diff"),
        "html_tables": raw_payload.get("html_tables"),
        "dashboard_cards": raw_payload.get("dashboard_cards"),
        "svg_charts": raw_payload.get("svg_charts"),
    }


def create_capture_artifact(
    req: Any,
    *,
    content: str,
    summary: str,
    raw_payload: Optional[dict] = None,
) -> ArtifactRecord:
    init_capture_store()
    payload = build_capture_payload(req, content=content, summary=summary, raw_payload=raw_payload)
    artifact_kind, mime_type, completeness = _artifact_kind_for(req.eventType, req.sourceUrl, raw_payload)
    if artifact_kind == "pdf_document" and payload.get("pdf_bytes_b64"):
        binary = base64.b64decode(payload["pdf_bytes_b64"])
        storage_uri = _write_blob("artifacts", req.customId, ".pdf", binary)
        payload["storage_ref"] = storage_uri
        payload_bytes = json.dumps({k: v for k, v in payload.items() if k != "pdf_bytes_b64"}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    else:
        payload_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        storage_uri = _write_blob("artifacts", req.customId, ".json", payload_bytes)

    artifact_id = str(uuid.uuid4())
    now = _utc_now()
    with _connect() as con:
        row = con.execute(
            "SELECT artifact_id, artifact_seq FROM capture_artifacts WHERE memory_id = ? ORDER BY artifact_seq DESC LIMIT 1",
            (req.customId,),
        ).fetchone()
        parent_artifact_id = row["artifact_id"] if row else None
        artifact_seq = int(row["artifact_seq"]) + 1 if row else 1
        metadata = {
            "title": getattr(req, "title", None),
            "timestamp": getattr(req, "timestamp", now),
            "summary": summary,
            "namespace": raw_payload.get("namespace") if raw_payload else None,
        }
        con.execute(
            """
            INSERT INTO capture_artifacts (
                artifact_id, memory_id, artifact_seq, parent_artifact_id,
                source_app, event_type, source_url, conversation_id,
                artifact_kind, mime_type, schema_version, sha256, byte_size,
                storage_uri, completeness, captured_at, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                req.customId,
                artifact_seq,
                parent_artifact_id,
                req.sourceApp,
                req.eventType,
                req.sourceUrl,
                getattr(req, "conversationId", None),
                artifact_kind,
                mime_type,
                ARTIFACT_SCHEMA_VERSION,
                _sha256_bytes(payload_bytes),
                len(payload_bytes),
                storage_uri,
                completeness,
                getattr(req, "timestamp", now),
                now,
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
    return ArtifactRecord(
        artifact_id=artifact_id,
        memory_id=req.customId,
        artifact_seq=artifact_seq,
        artifact_kind=artifact_kind,
        event_type=req.eventType,
        source_app=req.sourceApp,
        source_url=req.sourceUrl,
        conversation_id=getattr(req, "conversationId", None),
        mime_type=mime_type,
        schema_version=ARTIFACT_SCHEMA_VERSION,
        sha256=_sha256_bytes(payload_bytes),
        byte_size=len(payload_bytes),
        storage_uri=storage_uri,
        completeness=completeness,
        captured_at=getattr(req, "timestamp", now),
        created_at=now,
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )


def load_artifact(artifact_id: str) -> Optional[dict]:
    init_capture_store()
    with _connect() as con:
        row = con.execute("SELECT * FROM capture_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
    if not row:
        return None
    storage_uri = row["storage_uri"]
    payload: dict[str, Any] = {}
    if storage_uri.endswith(".json") and os.path.exists(storage_uri):
        raw_bytes = Path(storage_uri).read_bytes()
        actual_hash = hashlib.sha256(raw_bytes).hexdigest()
        if actual_hash != row["sha256"]:
            logger.warning(
                "Artifact %s integrity check failed: stored sha256=%s actual=%s path=%s",
                artifact_id, row["sha256"], actual_hash, storage_uri,
            )
        payload = json.loads(raw_bytes.decode("utf-8"))
    elif storage_uri.endswith(".pdf"):
        payload = {"pdf_path": storage_uri}
    return {
        **dict(row),
        "payload": payload,
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def list_artifacts(memory_id: str) -> list[dict]:
    init_capture_store()
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM capture_artifacts WHERE memory_id = ? ORDER BY artifact_seq DESC",
            (memory_id,),
        ).fetchall()
    out = []
    for row in rows:
        out.append({
            "artifact_id": row["artifact_id"],
            "artifact_seq": row["artifact_seq"],
            "artifact_kind": row["artifact_kind"],
            "completeness": row["completeness"],
            "captured_at": row["captured_at"],
            "created_at": row["created_at"],
            "byte_size": row["byte_size"],
            "event_type": row["event_type"],
            "source_app": row["source_app"],
            "source_url": row["source_url"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        })
    return out


def list_materializations(memory_id: str) -> list[dict]:
    init_capture_store()
    with _connect() as con:
        rows = con.execute(
            """
            SELECT materialization_id, memory_id, artifact_id, extractor_bundle_version,
                   content_type, status, is_active, validation_json, created_at, promoted_at
            FROM memory_materializations
            WHERE memory_id = ?
            ORDER BY created_at DESC
            """,
            (memory_id,),
        ).fetchall()
    return [
        {
            "materialization_id": row["materialization_id"],
            "memory_id": row["memory_id"],
            "artifact_id": row["artifact_id"],
            "extractor_bundle_version": row["extractor_bundle_version"],
            "content_type": row["content_type"],
            "status": row["status"],
            "is_active": bool(row["is_active"]),
            "validation": json.loads(row["validation_json"] or "{}"),
            "created_at": row["created_at"],
            "promoted_at": row["promoted_at"],
        }
        for row in rows
    ]


def get_active_materialization(memory_id: str) -> Optional[dict]:
    init_capture_store()
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM memory_materializations WHERE memory_id = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
            (memory_id,),
        ).fetchone()
    if not row:
        return None
    return load_materialization(row["materialization_id"])


def _hash_chunk(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _slug_key(text: str, default: str) -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in (text or "").strip())
    raw = "_".join(part for part in raw.split("_") if part)[:48]
    return raw or default


def _chunk_text_fallback(text: str) -> list[dict]:
    from shail.memory.rag import _chunk_text

    s = _settings()
    chunks = _chunk_text(text or "", s.rag_chunk_size, s.rag_chunk_overlap)
    if not chunks:
        chunks = [text or ""]
    out = []
    for idx, chunk in enumerate(chunks):
        out.append({
            "chunk_key": f"text:{idx:04d}",
            "chunk_type": "text",
            "text": chunk,
            "group_key": "text",
            "locator": {"offset_index": idx},
            "metadata": {},
            "never_split": False,
        })
    return out


def _chunks_for_transcript(payload: dict) -> list[dict]:
    turns = payload.get("turns") or _extract_transcript_turns(payload.get("rendered_transcript", ""), payload.get("latest_user_text", ""))
    out = []
    for idx, turn in enumerate(turns):
        text = f"User: {turn.get('user', '').strip()}\n\nAssistant: {turn.get('assistant', '').strip()}".strip()
        out.append({
            "chunk_key": f"turn:{idx + 1:04d}",
            "chunk_type": "transcript_turn",
            "text": text,
            "group_key": "transcript",
            "locator": {"turn_index": idx + 1},
            "metadata": {"user": turn.get("user"), "assistant": turn.get("assistant")},
            "never_split": True,
        })
    return out or _chunk_text_fallback(payload.get("normalized_text", ""))


def _chunks_for_pdf(payload: dict, normalized_text: str) -> list[dict]:
    text = normalized_text or payload.get("content_stub") or payload.get("normalized_text") or ""
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    out = []
    for idx, block in enumerate(blocks):
        key = f"page:01:block:{idx + 1:02d}"
        out.append({
            "chunk_key": key,
            "chunk_type": "pdf_block",
            "text": block,
            "group_key": "pdf",
            "locator": {"page_number": 1, "block_index": idx + 1},
            "metadata": {"section_title": None},
            "never_split": True,
        })
    return out or _chunk_text_fallback(text)


def _chunks_for_github_diff(payload: dict, normalized_text: str) -> list[dict]:
    diff = payload.get("github_diff")
    if isinstance(diff, dict) and isinstance(diff.get("files"), list):
        out = []
        for file_idx, file_row in enumerate(diff["files"]):
            path = str(file_row.get("path") or f"file_{file_idx}")
            hunks = file_row.get("hunks") or []
            if not hunks:
                text = str(file_row.get("patch_text") or file_row.get("summary") or "").strip()
                if text:
                    out.append({
                        "chunk_key": f"file:{path}:summary",
                        "chunk_type": "code_diff_file",
                        "text": text,
                        "group_key": f"file:{path}",
                        "locator": {"path": path},
                        "metadata": {"repo": diff.get("repo"), "pr_number": diff.get("pr_number")},
                        "never_split": True,
                    })
                continue
            for hunk_idx, hunk in enumerate(hunks):
                header = str(hunk.get("header") or "")
                lines = hunk.get("lines") or []
                rendered = "\n".join([header] + [str(line) for line in lines]).strip()
                out.append({
                    "chunk_key": f"file:{path}:hunk:{hunk_idx + 1:03d}",
                    "chunk_type": "code_diff_hunk",
                    "text": rendered,
                    "group_key": f"file:{path}",
                    "locator": {"path": path, "hunk_index": hunk_idx + 1},
                    "metadata": {
                        "repo": diff.get("repo"),
                        "pr_number": diff.get("pr_number"),
                        "base_sha": diff.get("base_sha"),
                        "head_sha": diff.get("head_sha"),
                    },
                    "never_split": True,
                })
        return out or _chunk_text_fallback(normalized_text)
    return _chunk_text_fallback(normalized_text)


def _chunks_for_tables(payload: dict, normalized_text: str) -> list[dict]:
    tables = payload.get("html_tables") or []
    out: list[dict] = []
    for idx, table in enumerate(tables):
        if not isinstance(table, dict):
            continue
        title = str(table.get("title") or f"table_{idx + 1}")
        slug = _slug_key(title, f"table_{idx + 1}")
        columns = table.get("columns") or []
        rows = table.get("rows") or []
        rendered_lines = []
        if columns:
            rendered_lines.append(" | ".join(str(c) for c in columns))
        for row in rows:
            if isinstance(row, list):
                rendered_lines.append(" | ".join(str(cell) for cell in row))
        rendered = (str(table.get("title") or "") + "\n" + "\n".join(rendered_lines)).strip()
        out.append({
            "chunk_key": f"table:{slug}:{idx + 1:03d}",
            "chunk_type": "table",
            "text": rendered or normalized_text,
            "group_key": f"table:{slug}",
            "locator": {
                "source_locator": table.get("source_locator"),
                "header_depth": table.get("header_depth"),
            },
            "metadata": {
                "title": title,
                "columns": columns,
                "column_types": table.get("column_types") or [],
                "units": table.get("units"),
                "row_count": len(rows),
            },
            "never_split": True,
        })
    return out or _chunk_text_fallback(normalized_text)


def _chunks_for_dashboard(payload: dict, normalized_text: str) -> list[dict]:
    cards = payload.get("dashboard_cards") or []
    out: list[dict] = []
    for idx, card in enumerate(cards):
        if not isinstance(card, dict):
            continue
        title = str(card.get("card_title") or f"card_{idx + 1}")
        slug = _slug_key(title, f"card_{idx + 1}")
        rendered = "\n".join(
            str(part)
            for part in [
                card.get("section_title"),
                card.get("card_title"),
                card.get("primary_value"),
                card.get("subtitle"),
                card.get("delta_value"),
                card.get("time_window"),
            ]
            if part
        ).strip()
        out.append({
            "chunk_key": f"card:{slug}:{idx + 1:03d}",
            "chunk_type": "dashboard_card",
            "text": rendered or normalized_text,
            "group_key": f"section:{_slug_key(str(card.get('section_title') or 'dashboard'), 'dashboard')}",
            "locator": {"source_locator": card.get("source_locator")},
            "metadata": {
                "section_title": card.get("section_title"),
                "card_title": card.get("card_title"),
                "primary_value": card.get("primary_value"),
                "value_num": card.get("value_num"),
                "unit": card.get("unit"),
                "delta_value": card.get("delta_value"),
                "delta_unit": card.get("delta_unit"),
                "time_window": card.get("time_window"),
            },
            "never_split": True,
        })
    return out or _chunk_text_fallback(normalized_text)


def _chunks_for_chart(payload: dict, normalized_text: str) -> list[dict]:
    charts = payload.get("svg_charts") or []
    out: list[dict] = []
    for idx, chart in enumerate(charts):
        if not isinstance(chart, dict):
            continue
        title = str(chart.get("title") or f"chart_{idx + 1}")
        slug = _slug_key(title, f"chart_{idx + 1}")
        rendered_parts = [
            str(chart.get("title") or ""),
            str(chart.get("subtitle") or ""),
            "x_axis: " + str(chart.get("x_axis") or ""),
            "y_axis: " + str(chart.get("y_axis") or ""),
            "legend: " + ", ".join(str(item) for item in (chart.get("legend") or [])),
        ]
        for series in chart.get("series") or []:
            if isinstance(series, dict):
                rendered_parts.append(f"series {series.get('name', '')}: {series.get('values', '')}")
        rendered = "\n".join(part for part in rendered_parts if part).strip()
        out.append({
            "chunk_key": f"chart:{slug}:{idx + 1:03d}",
            "chunk_type": "chart",
            "text": rendered or normalized_text,
            "group_key": f"chart:{slug}",
            "locator": {"source_locator": chart.get("source_locator")},
            "metadata": {
                "title": title,
                "subtitle": chart.get("subtitle"),
                "chart_type": chart.get("chart_type"),
                "time_window": chart.get("time_window"),
                "capture_confidence": chart.get("capture_confidence"),
            },
            "never_split": True,
        })
    return out or _chunk_text_fallback(normalized_text)


def _build_chunks(artifact: dict, normalized_text: str) -> list[dict]:
    kind = artifact["artifact_kind"]
    payload = artifact.get("payload") or {}
    if artifact["event_type"] == "ai_conversation":
        return _chunks_for_transcript(payload)
    if kind in {"pdf_document", "pdf_stub"}:
        return _chunks_for_pdf(payload, normalized_text)
    if kind == "github_diff_capture":
        return _chunks_for_github_diff(payload, normalized_text)
    if kind == "html_table_capture":
        return _chunks_for_tables(payload, normalized_text)
    if kind == "dashboard_capture":
        return _chunks_for_dashboard(payload, normalized_text)
    if kind == "chart_capture":
        return _chunks_for_chart(payload, normalized_text)
    return _chunk_text_fallback(normalized_text)


def _normalized_text_from_artifact(artifact: dict) -> str:
    payload = artifact.get("payload") or {}
    if payload.get("normalized_text"):
        return str(payload["normalized_text"])
    if artifact["event_type"] == "ai_conversation":
        turns = payload.get("turns") or []
        if turns:
            return "\n\n---\n\n".join(
                f"User: {turn.get('user', '').strip()}\n\nAssistant: {turn.get('assistant', '').strip()}".strip()
                for turn in turns
            )
        return str(payload.get("rendered_transcript") or "")
    if artifact["artifact_kind"] == "pdf_stub":
        return str(payload.get("content_stub") or payload.get("normalized_text") or "")
    return str(payload.get("page_content") or "")


def _options_hash(options: dict) -> str:
    return hashlib.sha256(json.dumps(options or {}, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def load_materialization(materialization_id: str) -> Optional[dict]:
    init_capture_store()
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM memory_materializations WHERE materialization_id = ?",
            (materialization_id,),
        ).fetchone()
        chunk_rows = con.execute(
            """
            SELECT chunk_key, chunk_type, ordinal, parent_chunk_key, group_key, never_split,
                   chunk_hash, vector_id, locator_json, metadata_json, text_uri
            FROM materialization_chunks
            WHERE materialization_id = ?
            ORDER BY ordinal ASC
            """,
            (materialization_id,),
        ).fetchall()
    if not row:
        return None
    normalized_text = ""
    if row["normalized_text_uri"] and os.path.exists(row["normalized_text_uri"]):
        normalized_text = Path(row["normalized_text_uri"]).read_text(encoding="utf-8")
    structured = {}
    if row["structured_uri"] and os.path.exists(row["structured_uri"]):
        structured = json.loads(Path(row["structured_uri"]).read_text(encoding="utf-8"))
    chunks = []
    for chunk_row in chunk_rows:
        text = Path(chunk_row["text_uri"]).read_text(encoding="utf-8")
        chunks.append({
            "chunk_key": chunk_row["chunk_key"],
            "chunk_type": chunk_row["chunk_type"],
            "ordinal": chunk_row["ordinal"],
            "parent_chunk_key": chunk_row["parent_chunk_key"],
            "group_key": chunk_row["group_key"],
            "never_split": bool(chunk_row["never_split"]),
            "chunk_hash": chunk_row["chunk_hash"],
            "vector_id": chunk_row["vector_id"],
            "locator": json.loads(chunk_row["locator_json"] or "{}"),
            "metadata": json.loads(chunk_row["metadata_json"] or "{}"),
            "text": text,
        })
    return {
        **dict(row),
        "normalized_text": normalized_text,
        "structured": structured,
        "chunks": chunks,
    }


def _extract_pdf_text(payload: dict) -> tuple[str, dict]:
    pdf_path = payload.get("pdf_path")
    if pdf_path and os.path.exists(pdf_path):
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(pdf_path)
            page_blocks = []
            for idx, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                if text:
                    page_blocks.append({"page_number": idx, "text": text})
            normalized_text = "\n\n".join(block["text"] for block in page_blocks)
            return normalized_text, {"page_blocks": page_blocks}
        except Exception:
            pass
    stub = str(payload.get("content_stub") or payload.get("normalized_text") or "")
    return stub, {"page_blocks": [{"page_number": 1, "text": stub}] if stub else []}


async def create_materialization(
    artifact_id: str,
    *,
    user_id: Optional[str],
    namespace: str,
    promote: bool = False,
    extractor_bundle_version: Optional[str] = None,
    options: Optional[dict] = None,
) -> Optional[dict]:
    from apps.shail.blueprints import extract_blueprint

    init_capture_store()
    artifact = load_artifact(artifact_id)
    if not artifact:
        return None
    bundle_version = extractor_bundle_version or _settings().capture_bundle_version
    options = dict(options or {})
    options_hash = _options_hash(options)
    memory_id = artifact["memory_id"]
    with _connect() as con:
        existing = con.execute(
            "SELECT materialization_id FROM memory_materializations WHERE artifact_id = ? AND extractor_bundle_version = ? AND options_hash = ?",
            (artifact_id, bundle_version, options_hash),
        ).fetchone()
    if existing:
        result = load_materialization(existing["materialization_id"])
        if promote and result:
            promote_materialization(existing["materialization_id"], namespace=namespace, user_id=user_id)
            result = load_materialization(existing["materialization_id"])
        return result
    normalized_text = _normalized_text_from_artifact(artifact)
    structured: dict[str, Any] = {
        "artifact_kind": artifact["artifact_kind"],
        "completeness": artifact["completeness"],
        "extractor_bundle_version": bundle_version,
    }
    if artifact["artifact_kind"] in {"pdf_document", "pdf_stub"}:
        normalized_text, pdf_struct = _extract_pdf_text(artifact.get("payload") or {})
        structured.update(pdf_struct)
    blueprint = await extract_blueprint(
        content=normalized_text,
        content_type=artifact["event_type"],
        user_id=user_id,
    )
    if blueprint:
        structured["blueprint"] = blueprint

    chunks = _build_chunks(artifact, normalized_text)
    materialization_id = str(uuid.uuid4())
    root = _artifact_root() / "materializations" / materialization_id
    root.mkdir(parents=True, exist_ok=True)
    normalized_text_uri = str(root / "normalized_text.txt")
    Path(normalized_text_uri).write_text(normalized_text, encoding="utf-8")
    structured_uri = str(root / "structured.json")
    Path(structured_uri).write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")

    now = _utc_now()
    with _connect() as con:
        con.execute(
            """
            INSERT INTO memory_materializations (
                materialization_id, memory_id, artifact_id, extractor_bundle_version,
                options_hash, content_type, normalized_text_uri, structured_uri,
                status, is_active, validation_json, created_at, promoted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, NULL)
            """,
            (
                materialization_id,
                memory_id,
                artifact_id,
                bundle_version,
                options_hash,
                artifact["event_type"],
                normalized_text_uri,
                structured_uri,
                STATUS_READY,
                json.dumps({"chunk_count": len(chunks), "normalized_text_chars": len(normalized_text)}),
                now,
            ),
        )
        for ordinal, chunk in enumerate(chunks):
            text_uri = str(root / f"chunk_{ordinal:04d}.txt")
            Path(text_uri).write_text(chunk["text"], encoding="utf-8")
            con.execute(
                """
                INSERT INTO materialization_chunks (
                    chunk_row_id, materialization_id, memory_id, chunk_key, chunk_type,
                    ordinal, parent_chunk_key, group_key, never_split, chunk_hash,
                    vector_id, locator_json, metadata_json, text_uri
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    materialization_id,
                    memory_id,
                    chunk["chunk_key"],
                    chunk["chunk_type"],
                    ordinal,
                    chunk.get("parent_chunk_key"),
                    chunk.get("group_key"),
                    1 if chunk.get("never_split") else 0,
                    _hash_chunk(chunk["text"]),
                    f"{memory_id}#{chunk['chunk_key']}",
                    json.dumps(chunk.get("locator") or {}),
                    json.dumps(chunk.get("metadata") or {}),
                    text_uri,
                ),
            )
    if promote:
        promote_materialization(
            materialization_id,
            namespace=namespace,
            user_id=user_id,
        )
    return load_materialization(materialization_id)


def _artifact_metadata(memory_id: str) -> dict:
    with _connect() as con:
        row = con.execute(
            "SELECT metadata_json, source_app, source_url, event_type, conversation_id FROM capture_artifacts WHERE memory_id = ? ORDER BY artifact_seq DESC LIMIT 1",
            (memory_id,),
        ).fetchone()
    if not row:
        return {}
    meta = json.loads(row["metadata_json"] or "{}")
    meta.setdefault("sourceApp", row["source_app"])
    meta.setdefault("sourceUrl", row["source_url"])
    meta.setdefault("eventType", row["event_type"])
    meta.setdefault("conversationId", row["conversation_id"] or "")
    return meta


def _delete_vector_ids(ids: Iterable[str]) -> None:
    ids = [rid for rid in ids if rid]
    if not ids:
        return
    from shail.memory.rag import _get_store

    _get_store().delete_ids(ids)


def _legacy_vector_ids(memory_id: str) -> list[str]:
    from shail.memory.rag import _get_store

    try:
        store = _get_store()
    except Exception:
        return []
    if hasattr(store, "collection"):
        ids: set[str] = set()
        for where in ({"customId": memory_id}, {"parent_memory_id": memory_id}):
            try:
                result = store.collection.get(where=where, include=[])
                ids.update(result.get("ids", []))
            except Exception:
                continue
        return sorted(ids)
    return []


def promote_materialization(
    materialization_id: str,
    *,
    namespace: str,
    user_id: Optional[str],
) -> Optional[dict]:
    from apps.shail.blueprints import save_blueprint

    materialization = load_materialization(materialization_id)
    if not materialization:
        return None
    memory_id = materialization["memory_id"]
    active = get_active_materialization(memory_id)
    stale_ids: list[str] = []
    if active and active["materialization_id"] != materialization_id:
        stale_ids.extend(
            chunk["vector_id"]
            for chunk in active["chunks"]
            if chunk.get("vector_id")
        )
    records: list[dict[str, Any]] = []
    meta = _artifact_metadata(memory_id)
    summary = meta.get("summary") or materialization["normalized_text"][:400]
    common_meta = {
        "customId": memory_id,
        "conversationId": meta.get("conversationId", ""),
        "eventType": meta.get("eventType", materialization["content_type"]),
        "sourceApp": meta.get("sourceApp", "web"),
        "source": f"browser_{meta.get('sourceApp', 'web')}",
        "tier": "important",
        "sourceUrl": meta.get("sourceUrl", ""),
        "title": meta.get("title") or "",
        "summary": summary,
        "timestamp": meta.get("timestamp") or _utc_now(),
        "captured_ts": str(datetime.now(timezone.utc).timestamp()),
        "pinned": "false",
        "tags": "[]",
        "namespace": namespace,
        "artifact_id": materialization["artifact_id"],
        "materialization_id": materialization_id,
        "extractor_bundle_version": materialization["extractor_bundle_version"],
    }
    records.append({
        "id": memory_id,
        "namespace": namespace,
        "content": materialization["normalized_text"],
        "metadata": {**common_meta, "id": memory_id},
    })
    active_ids = {memory_id}
    for idx, chunk in enumerate(materialization["chunks"]):
        vector_id = chunk["vector_id"] or f"{memory_id}#{chunk['chunk_key']}"
        active_ids.add(vector_id)
        records.append({
            "id": vector_id,
            "namespace": namespace,
            "content": chunk["text"],
            "metadata": {
                **common_meta,
                "id": vector_id,
                "parent_memory_id": memory_id,
                "chunk_index": idx,
                "chunk_total": len(materialization["chunks"]),
                "chunk_hash": chunk["chunk_hash"],
                "chunk_key": chunk["chunk_key"],
                "chunk_type": chunk["chunk_type"],
                "locator_json": json.dumps(chunk["locator"]),
                **chunk["metadata"],
            },
        })
    stale_ids = [rid for rid in stale_ids if rid not in active_ids]
    if not active:
        stale_ids.extend(rid for rid in _legacy_vector_ids(memory_id) if rid not in active_ids)
    stale_ids = sorted(set(stale_ids))
    _delete_vector_ids(stale_ids)
    ingest(records=records)
    blueprint = materialization["structured"].get("blueprint")
    if blueprint:
        save_blueprint(
            memory_id,
            blueprint,
            user_id=user_id,
            namespace=namespace,
            content_type=materialization["content_type"],
            artifact_id=materialization["artifact_id"],
            materialization_id=materialization_id,
            extractor_bundle_version=materialization["extractor_bundle_version"],
            fact_source_type="materialization",
        )
    now = _utc_now()
    with _connect() as con:
        con.execute(
            "UPDATE memory_materializations SET is_active = 0 WHERE memory_id = ?",
            (memory_id,),
        )
        con.execute(
            "UPDATE memory_materializations SET is_active = 1, promoted_at = ?, status = ? WHERE materialization_id = ?",
            (now, STATUS_PROMOTED, materialization_id),
        )
    return load_materialization(materialization_id)


def create_replay_job(
    *,
    mode: str,
    scope_type: str,
    scope_ref: str,
    bundle_version: Optional[str] = None,
    options: Optional[dict] = None,
) -> str:
    init_capture_store()
    replay_job_id = str(uuid.uuid4())
    now = _utc_now()
    options = options or {}
    with _connect() as con:
        con.execute(
            """
            INSERT INTO replay_jobs (
                replay_job_id, mode, status, scope_type, scope_ref, bundle_version,
                options_hash, validation_json, prior_active_materialization_id,
                promoted_materialization_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                replay_job_id,
                mode,
                STATUS_PENDING,
                scope_type,
                scope_ref,
                bundle_version or _settings().capture_bundle_version,
                _options_hash(options),
                json.dumps({"options": options}),
                now,
                now,
            ),
        )
    return replay_job_id


def _resolve_replay_artifacts(
    scope_type: str,
    scope_ref: str,
    *,
    since: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    with _connect() as con:
        if scope_type == "artifact_id":
            rows = con.execute(
                "SELECT artifact_id FROM capture_artifacts WHERE artifact_id = ?",
                (scope_ref,),
            ).fetchall()
        elif scope_type == "memory_id":
            rows = con.execute(
                "SELECT artifact_id FROM capture_artifacts WHERE memory_id = ? ORDER BY artifact_seq DESC LIMIT 1",
                (scope_ref,),
            ).fetchall()
        else:
            params: list[Any] = [scope_ref]
            sql = "SELECT artifact_id FROM capture_artifacts WHERE artifact_kind = ?"
            if since:
                sql += " AND created_at >= ?"
                params.append(since)
            sql += " ORDER BY created_at DESC"
            if isinstance(limit, int) and limit > 0:
                sql += " LIMIT ?"
                params.append(limit)
            rows = con.execute(sql, params).fetchall()
    return [load_artifact(row["artifact_id"]) for row in rows if load_artifact(row["artifact_id"])]


def get_replay_job(replay_job_id: str) -> Optional[dict]:
    init_capture_store()
    with _connect() as con:
        job = con.execute("SELECT * FROM replay_jobs WHERE replay_job_id = ?", (replay_job_id,)).fetchone()
        items = con.execute(
            "SELECT * FROM replay_job_items WHERE replay_job_id = ? ORDER BY created_at ASC",
            (replay_job_id,),
        ).fetchall()
    if not job:
        return None
    return {
        **dict(job),
        "validation": json.loads(job["validation_json"] or "{}"),
        "items": [
            {
                **dict(item),
                "validation": json.loads(item["validation_json"] or "{}"),
            }
            for item in items
        ],
    }


async def run_replay_job(
    replay_job_id: str,
    *,
    user_id: Optional[str],
    namespace: str,
) -> Optional[dict]:
    init_capture_store()
    with _connect() as con:
        job = con.execute("SELECT * FROM replay_jobs WHERE replay_job_id = ?", (replay_job_id,)).fetchone()
        if not job:
            return None
        con.execute(
            "UPDATE replay_jobs SET status = ?, updated_at = ? WHERE replay_job_id = ?",
            (STATUS_RUNNING, _utc_now(), replay_job_id),
        )
    job_options: dict[str, Any] = {}
    try:
        job_options = json.loads(job["validation_json"] or "{}").get("options") or {}
    except Exception:
        job_options = {}
    artifacts = _resolve_replay_artifacts(
        job["scope_type"],
        job["scope_ref"],
        since=job_options.get("since"),
        limit=job_options.get("limit"),
    )
    promoted_id = None
    prior_active_id = None
    for artifact in artifacts:
        item_id = str(uuid.uuid4())
        now = _utc_now()
        with _connect() as con:
            active = con.execute(
                "SELECT materialization_id FROM memory_materializations WHERE memory_id = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
                (artifact["memory_id"],),
            ).fetchone()
            prior_active_id = active["materialization_id"] if active else prior_active_id
            con.execute(
                """
                INSERT INTO replay_job_items (
                    replay_job_item_id, replay_job_id, artifact_id, memory_id, status,
                    materialization_id, validation_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?)
                """,
                (item_id, replay_job_id, artifact["artifact_id"], artifact["memory_id"], STATUS_RUNNING, json.dumps({}), now, now),
            )
        try:
            materialization = await create_materialization(
                artifact["artifact_id"],
                user_id=user_id,
                namespace=namespace,
                promote=job["mode"] == REPLAY_MODE_PROMOTE,
                extractor_bundle_version=job["bundle_version"],
                options={"replay_job_id": replay_job_id},
            )
            validation = {
                "memory_id_unchanged": bool(materialization and materialization["memory_id"] == artifact["memory_id"]),
                "chunk_count": len(materialization["chunks"]) if materialization else 0,
            }
            promoted_id = materialization["materialization_id"] if materialization and materialization["is_active"] else promoted_id
            with _connect() as con:
                con.execute(
                    """
                    UPDATE replay_job_items
                    SET status = ?, materialization_id = ?, validation_json = ?, updated_at = ?
                    WHERE replay_job_item_id = ?
                    """,
                    (STATUS_PROMOTED if job["mode"] == REPLAY_MODE_PROMOTE else STATUS_READY, materialization["materialization_id"] if materialization else None, json.dumps(validation), _utc_now(), item_id),
                )
        except Exception as exc:
            with _connect() as con:
                con.execute(
                    """
                    UPDATE replay_job_items
                    SET status = ?, error = ?, updated_at = ?
                    WHERE replay_job_item_id = ?
                    """,
                    (STATUS_FAILED, str(exc), _utc_now(), item_id),
                )
            with _connect() as con:
                con.execute(
                    """
                    UPDATE replay_jobs
                    SET status = ?, validation_json = ?, prior_active_materialization_id = ?, updated_at = ?
                    WHERE replay_job_id = ?
                    """,
                    (STATUS_FAILED, json.dumps({"error": str(exc)}), prior_active_id, _utc_now(), replay_job_id),
                )
            return get_replay_job(replay_job_id)

    with _connect() as con:
        con.execute(
            """
            UPDATE replay_jobs
            SET status = ?, validation_json = ?, prior_active_materialization_id = ?,
                promoted_materialization_id = ?, updated_at = ?
            WHERE replay_job_id = ?
            """,
            (
                STATUS_PROMOTED if job["mode"] == REPLAY_MODE_PROMOTE else STATUS_READY,
                json.dumps({"items": len(artifacts)}),
                prior_active_id,
                promoted_id,
                _utc_now(),
                replay_job_id,
            ),
        )
    return get_replay_job(replay_job_id)


def capture_health(memory_id: str) -> dict:
    artifacts = list_artifacts(memory_id)
    materializations = list_materializations(memory_id)
    completeness = artifacts[0]["completeness"] if artifacts else "missing"
    active_id: Optional[str] = None
    prior_id: Optional[str] = None
    for m in materializations:
        if m["is_active"] and active_id is None:
            active_id = m["materialization_id"]
        elif active_id and prior_id is None:
            prior_id = m["materialization_id"]
            break
    artifact_ids = [a["artifact_id"] for a in artifacts] if artifacts else []
    replay_jobs: list[dict] = []
    if artifact_ids:
        with _connect() as con:
            placeholders = ",".join("?" * len(artifact_ids))
            rows = con.execute(
                f"""
                SELECT DISTINCT j.replay_job_id, j.mode, j.status, j.bundle_version,
                                j.created_at, j.updated_at
                FROM replay_jobs j
                JOIN replay_job_items i ON i.replay_job_id = j.replay_job_id
                WHERE i.memory_id = ? OR i.artifact_id IN ({placeholders})
                ORDER BY j.created_at DESC
                LIMIT 20
                """,
                (memory_id, *artifact_ids),
            ).fetchall()
            replay_jobs = [dict(row) for row in rows]
    return {
        "memory_id": memory_id,
        "artifact_count": len(artifacts),
        "materialization_count": len(materializations),
        "completeness": completeness,
        "has_active_materialization": any(m["is_active"] for m in materializations),
        "active_materialization_id": active_id,
        "prior_materialization_id": prior_id,
        "latest_artifact_kind": artifacts[0]["artifact_kind"] if artifacts else None,
        "latest_bundle_version": materializations[0]["extractor_bundle_version"] if materializations else None,
        "extractor_bundle_version": materializations[0]["extractor_bundle_version"] if materializations else None,
        "replay_jobs": replay_jobs,
    }


def backfill_legacy_memory(
    *,
    memory_id: str,
    content: str,
    metadata: dict,
) -> Optional[str]:
    class _Req:
        customId = memory_id
        sourceApp = metadata.get("sourceApp", "web")
        eventType = metadata.get("eventType", "page_visit")
        sourceUrl = metadata.get("sourceUrl", "")
        conversationId = metadata.get("conversationId") or None
        title = metadata.get("title") or ""
        timestamp = metadata.get("timestamp") or _utc_now()
        userText = ""
        assistantText = content
        pageContent = content

    req = _Req()
    existing = list_artifacts(memory_id)
    if existing:
        return existing[0]["artifact_id"]
    artifact = create_capture_artifact(
        req,
        content=content,
        summary=metadata.get("summary") or content[:400],
        raw_payload={"artifact_kind": "legacy_text_snapshot", "completeness": "legacy_partial"},
    )
    return artifact.artifact_id


def delete_memory_state(memory_id: str) -> None:
    init_capture_store()
    materializations = list_materializations(memory_id)
    vector_ids = [memory_id]
    for materialization in materializations:
        loaded = load_materialization(materialization["materialization_id"])
        if loaded:
            vector_ids.extend(
                chunk["vector_id"]
                for chunk in loaded["chunks"]
                if chunk.get("vector_id")
            )
    _delete_vector_ids(vector_ids)
    with _connect() as con:
        con.execute("DELETE FROM materialization_chunks WHERE memory_id = ?", (memory_id,))
        con.execute("DELETE FROM memory_materializations WHERE memory_id = ?", (memory_id,))
        con.execute("DELETE FROM capture_artifacts WHERE memory_id = ?", (memory_id,))
