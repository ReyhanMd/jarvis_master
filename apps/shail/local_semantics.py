"""Deterministic semantic extraction for approved local files.

This is derived, pointer-first state: it stores structured atoms with source
spans, not full local-file contents. Extraction is deterministic by default so
Phase 4 does not require an LLM/SLM.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from apps.shail.settings import get_settings
from shail.memory import path_index

EXTRACTOR_VERSION = "local_semantics_v1"
CONF_EXTRACTED = "EXTRACTED"
CONF_INFERRED = "INFERRED"
CONF_AMBIGUOUS = "AMBIGUOUS"

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_DOMAIN_RE = re.compile(r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
_MONEY_RE = re.compile(r"(?i)(?:[$€£₹]\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m|b|bn|million|billion|crore|lakh)?|\d[\d,]*(?:\.\d+)?\s?(?:usd|inr|aed|eur|gbp))")
_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%")
_DATE_RE = re.compile(
    r"(?i)\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}|"
    r"(?:q[1-4]\s+\d{4}|fy\s?\d{2,4}|\b20\d{2}\b))"
)
_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,3}\b")
_PERSON_VERB_RE = re.compile(r"\b([A-Z][a-z][A-Za-z.-]{1,40})\s+(?:met|owns|called|emailed|sent|asked|approved|joined|with|from|for|said|wrote|created|shared)\b")
_TASK_RE = re.compile(r"(?im)^\s*(?:[-*]\s+\[[ xX]\]|[-*]\s+|todo:|task:|action:|next:)\s*(.+)$")
_INLINE_TASK_RE = re.compile(r"(?i)(?:^|[\n.;])\s*(?:[-*]\s+\[[ xX]\]|todo:|task:|action:|next:)\s*([^\n.;]+)")
_DECISION_RE = re.compile(r"(?im)^\s*(?:decision:|decided to|we decided|chose to|approved:|final decision:)\s*(.+)$")
_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+)$")

_ORG_SUFFIXES = {
    "inc", "llc", "ltd", "limited", "corp", "corporation", "company",
    "technologies", "labs", "studio", "studios", "ai", "systems", "group",
}
_METRIC_WORDS = {
    "revenue", "pricing", "price", "cost", "budget", "profit", "margin",
    "growth", "churn", "sales", "valuation", "runway", "mrr", "arr",
    "conversion", "retention",
}
_STOP_ENTITIES = {
    "todo", "task", "action", "next", "decision", "draft", "final",
    "documents", "desktop", "downloads", "users", "private", "project",
}


def _db_path() -> str:
    return getattr(get_settings(), "sqlite_path", "") or get_settings().path_index_db


def _conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = Path(db_path or _db_path()).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    _ensure_schema(con)
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS local_file_semantics (
            file_id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            content_hash TEXT,
            extractor_version TEXT NOT NULL,
            status TEXT NOT NULL,
            extracted_at REAL NOT NULL,
            error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS local_file_entities (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            path TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            label TEXT NOT NULL,
            source_span TEXT,
            confidence TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS local_file_facts (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            path TEXT NOT NULL,
            entity TEXT,
            attribute TEXT,
            value TEXT,
            value_num REAL,
            unit TEXT,
            period TEXT,
            source_span TEXT,
            confidence TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS local_file_tasks (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            path TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT,
            due_date TEXT,
            source_span TEXT,
            confidence TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_local_sem_path ON local_file_semantics(path);
        CREATE INDEX IF NOT EXISTS idx_local_sem_hash ON local_file_semantics(content_hash);
        CREATE INDEX IF NOT EXISTS idx_local_entities_file ON local_file_entities(file_id);
        CREATE INDEX IF NOT EXISTS idx_local_entities_label ON local_file_entities(label);
        CREATE INDEX IF NOT EXISTS idx_local_facts_file ON local_file_facts(file_id);
        CREATE INDEX IF NOT EXISTS idx_local_facts_entity ON local_file_facts(entity);
        CREATE INDEX IF NOT EXISTS idx_local_tasks_file ON local_file_tasks(file_id);
        """
    )
    alters = [
        "ALTER TABLE local_file_semantics ADD COLUMN llm_extractor_version TEXT",
        "ALTER TABLE local_file_semantics ADD COLUMN llm_model TEXT",
        "ALTER TABLE local_file_semantics ADD COLUMN llm_chunk_count INTEGER DEFAULT 0",
        "ALTER TABLE local_file_semantics ADD COLUMN llm_error TEXT",
        "ALTER TABLE local_file_semantics ADD COLUMN llm_enriched_at REAL",
    ]
    for ddl in alters:
        try:
            con.execute(ddl)
        except sqlite3.OperationalError:
            pass
    con.commit()


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return prefix + ":" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _clean(value: str, *, limit: int = 240) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def _source_span(text: str, start: int, end: int, *, radius: int = 80) -> str:
    s = max(0, start - radius)
    e = min(len(text), end + radius)
    return _clean(text[s:e], limit=220)


def _allowed_rows(path_db: str, *, limit: int) -> list[dict[str, Any]]:
    with path_index._conn(path_db) as con:
        rows = con.execute(
            """
            SELECT * FROM path_index
            WHERE is_dir = 0 AND deleted_at IS NULL
            ORDER BY last_seen_at DESC, path
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        if path_index.is_denied(path_db, d.get("path") or ""):
            continue
        out.append(d)
    return out


def _is_visible_path(path: str) -> bool:
    if not path:
        return False
    db = get_settings().path_index_db
    if path_index.is_denied(db, path):
        return False
    row = path_index.get_by_path(db, path)
    if not row:
        return False
    return not bool(row.get("deleted_at"))


def _visible_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    return [r for r in rows if _is_visible_path(r["path"])]


def _read_text(row: dict[str, Any], *, read_cap_bytes: int = 1_500_000) -> tuple[str, str]:
    path = row.get("path") or ""
    if not path or not os.path.exists(path):
        return row.get("summary_snippet") or "", "snippet"
    try:
        size = os.path.getsize(path)
    except OSError:
        size = None
    if size is not None and size > read_cap_bytes:
        return row.get("summary_snippet") or "", "snippet"
    try:
        from shail.memory.rag import _extract_text_from_file
        text = _extract_text_from_file(path) or ""
        if text:
            return text[:read_cap_bytes], "extractor"
    except Exception:
        pass
    return row.get("summary_snippet") or "", "snippet"


def _numeric_value(raw: str) -> Optional[float]:
    value = raw.lower().replace(",", "").strip()
    match = re.search(r"\d+(?:\.\d+)?", value)
    if not match:
        return None
    num = float(match.group(0))
    if re.search(r"(?:\d\s*|\b)(b|bn|billion)\b", value):
        num *= 1_000_000_000
    elif re.search(r"(?:\d\s*|\b)(m|million)\b", value):
        num *= 1_000_000
    elif re.search(r"(?:\d\s*|\b)(k)\b", value):
        num *= 1_000
    elif "crore" in value:
        num *= 10_000_000
    elif "lakh" in value:
        num *= 100_000
    return num


def _unit(raw: str) -> Optional[str]:
    low = raw.lower()
    if "%" in raw:
        return "%"
    if "$" in raw or "usd" in low:
        return "USD"
    if "₹" in raw or "inr" in low:
        return "INR"
    if "aed" in low:
        return "AED"
    if "€" in raw or "eur" in low:
        return "EUR"
    if "£" in raw or "gbp" in low:
        return "GBP"
    return None


def _attribute_near(text: str, start: int, end: int, fallback: str) -> str:
    window = text[max(0, start - 80): min(len(text), end + 80)].lower()
    for word in _METRIC_WORDS:
        if word in window:
            return word
    return fallback


def _entity_near(text: str, start: int, path: str) -> str:
    before = text[max(0, start - 140):start]
    matches = _ENTITY_RE.findall(before)
    for value in reversed(matches):
        cleaned = _clean(value, limit=80)
        if cleaned and cleaned.lower() not in _STOP_ENTITIES:
            return cleaned
    return Path(path).stem.replace("_", " ").replace("-", " ").strip() or "Document"


def _classify_entity(label: str) -> str:
    low = label.lower().strip(".")
    parts = {p.strip(".,").lower() for p in low.split()}
    if "@" in label:
        return "person"
    if "." in label and " " not in label:
        return "organization"
    if parts & _ORG_SUFFIXES:
        return "organization"
    if len(label.split()) <= 3:
        return "person"
    return "organization"


def extract_text_semantics(
    *,
    file_id: str,
    path: str,
    content_hash: Optional[str],
    text: str,
) -> dict[str, list[dict[str, Any]]]:
    entities: dict[tuple[str, str], dict[str, Any]] = {}
    facts: dict[str, dict[str, Any]] = {}
    tasks: dict[str, dict[str, Any]] = {}

    def add_entity(label: str, entity_type: str, span: str, confidence: str = CONF_EXTRACTED) -> None:
        label = _clean(label, limit=120)
        if len(label) < 3 or label.lower() in _STOP_ENTITIES:
            return
        key = (entity_type, label.lower())
        entities[key] = {
            "id": _stable_id("entity", file_id, entity_type, label.lower()),
            "file_id": file_id,
            "path": path,
            "entity_type": entity_type,
            "label": label,
            "source_span": span,
            "confidence": confidence,
            "metadata": {"content_hash": content_hash},
        }

    def add_fact(entity: str, attribute: str, value: str, start: int, end: int, *, value_num: Optional[float], unit: Optional[str], period: Optional[str], confidence: str = CONF_EXTRACTED) -> None:
        value = _clean(value, limit=160)
        attribute = _clean(attribute.lower(), limit=80) or "value"
        entity = _clean(entity, limit=120) or "Document"
        fid = _stable_id("fact", file_id, entity.lower(), attribute, value, period)
        facts[fid] = {
            "id": fid,
            "file_id": file_id,
            "path": path,
            "entity": entity,
            "attribute": attribute,
            "value": value,
            "value_num": value_num,
            "unit": unit,
            "period": period,
            "source_span": _source_span(text, start, end),
            "confidence": confidence,
            "metadata": {"content_hash": content_hash},
        }

    for match in _EMAIL_RE.finditer(text):
        email = match.group(0)
        span = _source_span(text, match.start(), match.end())
        add_entity(email, "person", span)
        domain = email.split("@", 1)[-1]
        add_entity(domain, "organization", span, CONF_INFERRED)

    for match in _DOMAIN_RE.finditer(text):
        add_entity(match.group(0), "organization", _source_span(text, match.start(), match.end()))

    for match in _ENTITY_RE.finditer(text):
        label = match.group(0).strip()
        if label.lower() in _STOP_ENTITIES or label.isupper():
            continue
        add_entity(label, _classify_entity(label), _source_span(text, match.start(), match.end()), CONF_INFERRED)

    for match in _PERSON_VERB_RE.finditer(text):
        add_entity(match.group(1), "person", _source_span(text, match.start(1), match.end(1)), CONF_INFERRED)

    for match in _DATE_RE.finditer(text):
        value = match.group(0)
        add_fact(
            _entity_near(text, match.start(), path),
            "date",
            value,
            match.start(),
            match.end(),
            value_num=None,
            unit=None,
            period=value if re.fullmatch(r"\b20\d{2}\b", value) else None,
        )

    for pattern, fallback in ((_MONEY_RE, "money_value"), (_PERCENT_RE, "percent_value")):
        for match in pattern.finditer(text):
            value = match.group(0)
            add_fact(
                _entity_near(text, match.start(), path),
                _attribute_near(text, match.start(), match.end(), fallback),
                value,
                match.start(),
                match.end(),
                value_num=_numeric_value(value),
                unit=_unit(value),
                period=_period_near(text, match.start(), match.end()),
            )

    def add_task(raw: str, full_match: str, start: int, end: int) -> None:
        raw = _clean(raw, limit=260)
        if not raw:
            return
        status = "done" if "[x]" in full_match.lower() else "open"
        due = _first_date(raw)
        tid = _stable_id("task", file_id, raw.lower())
        tasks[tid] = {
            "id": tid,
            "file_id": file_id,
            "path": path,
            "text": raw,
            "status": status,
            "due_date": due,
            "source_span": _source_span(text, start, end),
            "confidence": CONF_EXTRACTED,
            "metadata": {"content_hash": content_hash},
        }

    for match in _TASK_RE.finditer(text):
        add_task(match.group(1), match.group(0), match.start(), match.end())

    for match in _INLINE_TASK_RE.finditer(text):
        add_task(match.group(1), match.group(0), match.start(), match.end())

    for match in _DECISION_RE.finditer(text):
        decision = _clean(match.group(1), limit=260)
        if decision:
            add_fact("Document", "decision", decision, match.start(), match.end(), value_num=None, unit=None, period=_period_near(text, match.start(), match.end()))

    for match in _HEADING_RE.finditer(text):
        title = _clean(match.group(2), limit=160)
        if title:
            add_fact("Document", "section", title, match.start(), match.end(), value_num=None, unit=None, period=None, confidence=CONF_INFERRED)

    return {
        "entities": list(entities.values()),
        "facts": list(facts.values()),
        "tasks": list(tasks.values()),
    }


def _first_date(text: str) -> Optional[str]:
    match = _DATE_RE.search(text or "")
    return match.group(0) if match else None


def _period_near(text: str, start: int, end: int) -> Optional[str]:
    window = text[max(0, start - 100): min(len(text), end + 100)]
    return _first_date(window)


def _clear_file(con: sqlite3.Connection, file_id: str) -> None:
    con.execute("DELETE FROM local_file_entities WHERE file_id = ?", (file_id,))
    con.execute("DELETE FROM local_file_facts WHERE file_id = ?", (file_id,))
    con.execute("DELETE FROM local_file_tasks WHERE file_id = ?", (file_id,))


def _persist(con: sqlite3.Connection, row: dict[str, Any], extracted: dict[str, list[dict[str, Any]]], *, status: str, error: Optional[str], source: str) -> None:
    file_id = row.get("id") or row.get("path")
    now = time.time()
    _clear_file(con, file_id)
    con.execute(
        """INSERT INTO local_file_semantics
           (file_id, path, content_hash, extractor_version, status, extracted_at, error, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(file_id) DO UPDATE SET
             path = excluded.path,
             content_hash = excluded.content_hash,
             extractor_version = excluded.extractor_version,
             status = excluded.status,
             extracted_at = excluded.extracted_at,
             error = excluded.error,
             metadata_json = excluded.metadata_json""",
        (
            file_id,
            row.get("path") or "",
            row.get("content_hash"),
            EXTRACTOR_VERSION,
            status,
            now,
            error,
            json.dumps({
                "source": source,
                "extractor": "deterministic",
                "entities": len(extracted.get("entities") or []),
                "facts": len(extracted.get("facts") or []),
                "tasks": len(extracted.get("tasks") or []),
            }),
        ),
    )
    for item in extracted.get("entities") or []:
        con.execute(
            """INSERT INTO local_file_entities
               (id, file_id, path, entity_type, label, source_span, confidence, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["id"], item["file_id"], item["path"], item["entity_type"], item["label"],
                item.get("source_span"), item.get("confidence", CONF_INFERRED),
                json.dumps(item.get("metadata") or {}),
            ),
        )
    for item in extracted.get("facts") or []:
        con.execute(
            """INSERT INTO local_file_facts
               (id, file_id, path, entity, attribute, value, value_num, unit, period, source_span, confidence, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["id"], item["file_id"], item["path"], item.get("entity"), item.get("attribute"),
                item.get("value"), item.get("value_num"), item.get("unit"), item.get("period"),
                item.get("source_span"), item.get("confidence", CONF_EXTRACTED),
                json.dumps(item.get("metadata") or {}),
            ),
        )
    for item in extracted.get("tasks") or []:
        con.execute(
            """INSERT INTO local_file_tasks
               (id, file_id, path, text, status, due_date, source_span, confidence, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["id"], item["file_id"], item["path"], item["text"], item.get("status"),
                item.get("due_date"), item.get("source_span"), item.get("confidence", CONF_EXTRACTED),
                json.dumps(item.get("metadata") or {}),
            ),
        )


def persist_llm_extracted(
    row: dict[str, Any],
    extracted: dict[str, list[dict[str, Any]]],
    *,
    model: str,
    extractor_version: str,
    chunk_count: int,
    semantics_db: Optional[str] = None,
) -> dict[str, int]:
    """Persist validated LLM semantic atoms as derived rows.

    This intentionally does not clear deterministic rows. Stable IDs include
    extractor/model/chunk metadata, so deterministic and LLM rows can coexist
    while search/graph/evidence remain pointer-first.
    """
    file_id = row.get("id") or row.get("path")
    path = row.get("path") or ""
    content_hash = row.get("content_hash")
    counts = {
        "entities": len(extracted.get("entities") or []),
        "facts": len(extracted.get("facts") or []),
        "tasks": len(extracted.get("tasks") or []),
    }
    now = time.time()
    with _conn(semantics_db) as con:
        con.execute(
            """INSERT INTO local_file_semantics
               (file_id, path, content_hash, extractor_version, status, extracted_at, error,
                metadata_json, llm_extractor_version, llm_model, llm_chunk_count, llm_error, llm_enriched_at)
               VALUES (?, ?, ?, ?, 'complete', ?, NULL, ?, ?, ?, ?, NULL, ?)
               ON CONFLICT(file_id) DO UPDATE SET
                 path = excluded.path,
                 content_hash = excluded.content_hash,
                 status = 'complete',
                 llm_extractor_version = excluded.llm_extractor_version,
                 llm_model = excluded.llm_model,
                 llm_chunk_count = excluded.llm_chunk_count,
                 llm_error = NULL,
                 llm_enriched_at = excluded.llm_enriched_at""",
            (
                file_id,
                path,
                content_hash,
                EXTRACTOR_VERSION,
                now,
                json.dumps({
                    "source": "extractor+ollama",
                    "extractor": "hybrid",
                    "entities": counts["entities"],
                    "facts": counts["facts"],
                    "tasks": counts["tasks"],
                }),
                extractor_version,
                model,
                int(chunk_count),
                now,
            ),
        )
        for item in extracted.get("entities") or []:
            con.execute(
                """INSERT OR REPLACE INTO local_file_entities
                   (id, file_id, path, entity_type, label, source_span, confidence, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["id"], file_id, path, item["entity_type"], item["label"],
                    item.get("source_span"), item.get("confidence", CONF_INFERRED),
                    json.dumps(item.get("metadata") or {}),
                ),
            )
        for item in extracted.get("facts") or []:
            con.execute(
                """INSERT OR REPLACE INTO local_file_facts
                   (id, file_id, path, entity, attribute, value, value_num, unit, period, source_span, confidence, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["id"], file_id, path, item.get("entity"), item.get("attribute"),
                    item.get("value"), item.get("value_num"), item.get("unit"), item.get("period"),
                    item.get("source_span"), item.get("confidence", CONF_INFERRED),
                    json.dumps(item.get("metadata") or {}),
                ),
            )
        for item in extracted.get("tasks") or []:
            con.execute(
                """INSERT OR REPLACE INTO local_file_tasks
                   (id, file_id, path, text, status, due_date, source_span, confidence, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["id"], file_id, path, item["text"], item.get("status"),
                    item.get("due_date"), item.get("source_span"), item.get("confidence", CONF_INFERRED),
                    json.dumps(item.get("metadata") or {}),
                ),
            )
        con.commit()
    return counts


def mark_llm_error(
    row: dict[str, Any],
    *,
    model: str,
    extractor_version: str,
    error: str,
    semantics_db: Optional[str] = None,
) -> None:
    file_id = row.get("id") or row.get("path")
    with _conn(semantics_db) as con:
        con.execute(
            """INSERT INTO local_file_semantics
               (file_id, path, content_hash, extractor_version, status, extracted_at, error,
                metadata_json, llm_extractor_version, llm_model, llm_error)
               VALUES (?, ?, ?, ?, 'failed', ?, ?, '{}', ?, ?, ?)
               ON CONFLICT(file_id) DO UPDATE SET
                 path = excluded.path,
                 content_hash = excluded.content_hash,
                 llm_extractor_version = excluded.llm_extractor_version,
                 llm_model = excluded.llm_model,
                 llm_error = excluded.llm_error""",
            (
                file_id,
                row.get("path") or "",
                row.get("content_hash"),
                EXTRACTOR_VERSION,
                time.time(),
                (error or "")[:500],
                extractor_version,
                model,
                (error or "")[:500],
            ),
        )
        con.commit()


def build_semantics(
    *,
    path_db: Optional[str] = None,
    semantics_db: Optional[str] = None,
    limit: int = 500,
    force: bool = False,
) -> dict[str, Any]:
    path_db = path_db or get_settings().path_index_db
    rows = _allowed_rows(path_db, limit=limit)
    counts = {
        "status": "complete",
        "files_seen": len(rows),
        "processed": 0,
        "skipped": 0,
        "failed": 0,
        "entities": 0,
        "facts": 0,
        "tasks": 0,
        "metrics": 0,
    }
    with _conn(semantics_db) as con:
        for row in rows:
            file_id = row.get("id") or row.get("path")
            existing = con.execute(
                "SELECT content_hash, extractor_version, status FROM local_file_semantics WHERE file_id = ?",
                (file_id,),
            ).fetchone()
            if (
                not force and existing and existing["status"] == "complete"
                and existing["extractor_version"] == EXTRACTOR_VERSION
                and str(existing["content_hash"] or "") == str(row.get("content_hash") or "")
            ):
                counts["skipped"] += 1
                continue
            try:
                text, source = _read_text(row)
                extracted = extract_text_semantics(
                    file_id=file_id,
                    path=row.get("path") or "",
                    content_hash=row.get("content_hash"),
                    text=text,
                )
                _persist(con, row, extracted, status="complete", error=None, source=source)
                counts["processed"] += 1
                counts["entities"] += len(extracted["entities"])
                counts["facts"] += len(extracted["facts"])
                counts["tasks"] += len(extracted["tasks"])
                counts["metrics"] += sum(
                    1 for f in extracted["facts"]
                    if f.get("unit") or f.get("attribute") in {"revenue", "pricing", "price", "cost", "budget", "profit", "margin", "growth", "churn"}
                )
            except Exception as exc:
                _persist(con, row, {"entities": [], "facts": [], "tasks": []}, status="failed", error=str(exc), source="none")
                counts["failed"] += 1
        con.commit()
    return counts


def status(*, semantics_db: Optional[str] = None) -> dict[str, Any]:
    with _conn(semantics_db) as con:
        sem = con.execute("SELECT status, COUNT(*) AS n FROM local_file_semantics GROUP BY status").fetchall()
        entities = con.execute("SELECT entity_type, COUNT(*) AS n FROM local_file_entities GROUP BY entity_type").fetchall()
        facts = con.execute("SELECT COUNT(*) FROM local_file_facts").fetchone()[0]
        tasks = con.execute("SELECT COUNT(*) FROM local_file_tasks").fetchone()[0]
        latest = con.execute("SELECT MAX(extracted_at) FROM local_file_semantics").fetchone()[0]
        latest_llm = con.execute("SELECT MAX(llm_enriched_at) FROM local_file_semantics").fetchone()[0]
    queue = {}
    try:
        from apps.shail import local_semantics_jobs
        queue = local_semantics_jobs.queue_stats(db_path=semantics_db)
    except Exception:
        queue = {}
    return {
        "files": {r["status"]: r["n"] for r in sem},
        "entities": {r["entity_type"]: r["n"] for r in entities},
        "facts": facts,
        "tasks": tasks,
        "last_extracted_at": latest,
        "latest_llm_enriched_at": latest_llm,
        "extractor_version": EXTRACTOR_VERSION,
        "queue": queue,
    }


def for_file(file_id: str, *, semantics_db: Optional[str] = None) -> dict[str, Any]:
    with _conn(semantics_db) as con:
        sem = con.execute("SELECT * FROM local_file_semantics WHERE file_id = ?", (file_id,)).fetchone()
        entities = _visible_rows(con.execute("SELECT * FROM local_file_entities WHERE file_id = ? ORDER BY entity_type, label", (file_id,)).fetchall())
        facts = _visible_rows(con.execute("SELECT * FROM local_file_facts WHERE file_id = ? ORDER BY attribute, entity", (file_id,)).fetchall())
        tasks = _visible_rows(con.execute("SELECT * FROM local_file_tasks WHERE file_id = ? ORDER BY status, text", (file_id,)).fetchall())
    return {
        "file": dict(sem) if sem else None,
        "entities": [_entity_row(r) for r in entities],
        "facts": [_fact_row(r) for r in facts],
        "tasks": [_task_row(r) for r in tasks],
    }


def search(query: str, *, semantics_db: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    q = (query or "").strip().lower()
    like = f"%{q}%"
    with _conn(semantics_db) as con:
        if q:
            file_ids = {
                r["file_id"] for r in con.execute(
                    "SELECT file_id FROM local_file_entities WHERE LOWER(label) LIKE ? OR LOWER(COALESCE(source_span,'')) LIKE ?",
                    (like, like),
                ).fetchall()
            }
            file_ids.update(
                r["file_id"] for r in con.execute(
                    """SELECT file_id FROM local_file_facts
                       WHERE LOWER(COALESCE(entity,'')) LIKE ? OR LOWER(COALESCE(attribute,'')) LIKE ?
                          OR LOWER(COALESCE(value,'')) LIKE ? OR LOWER(COALESCE(source_span,'')) LIKE ?""",
                    (like, like, like, like),
                ).fetchall()
            )
            file_ids.update(
                r["file_id"] for r in con.execute(
                    "SELECT file_id FROM local_file_tasks WHERE LOWER(text) LIKE ? OR LOWER(COALESCE(source_span,'')) LIKE ?",
                    (like, like),
                ).fetchall()
            )
            if not file_ids:
                return {"entities": [], "facts": [], "tasks": []}
            placeholders = ",".join("?" for _ in file_ids)
            params = (*file_ids, limit)
            entity_rows = _visible_rows(con.execute(
                f"SELECT * FROM local_file_entities WHERE file_id IN ({placeholders}) ORDER BY entity_type, label LIMIT ?",
                params,
            ).fetchall())
            fact_rows = _visible_rows(con.execute(
                f"SELECT * FROM local_file_facts WHERE file_id IN ({placeholders}) ORDER BY attribute, entity LIMIT ?",
                params,
            ).fetchall())
            task_rows = _visible_rows(con.execute(
                f"SELECT * FROM local_file_tasks WHERE file_id IN ({placeholders}) ORDER BY status, text LIMIT ?",
                params,
            ).fetchall())
        else:
            entity_rows = _visible_rows(con.execute("SELECT * FROM local_file_entities ORDER BY entity_type, label LIMIT ?", (limit,)).fetchall())
            fact_rows = _visible_rows(con.execute("SELECT * FROM local_file_facts ORDER BY attribute, entity LIMIT ?", (limit,)).fetchall())
            task_rows = _visible_rows(con.execute("SELECT * FROM local_file_tasks ORDER BY status, text LIMIT ?", (limit,)).fetchall())
    return {
        "entities": [_entity_row(r) for r in entity_rows],
        "facts": [_fact_row(r) for r in fact_rows],
        "tasks": [_task_row(r) for r in task_rows],
    }


def semantic_rows_for_files(file_ids: list[str], *, semantics_db: Optional[str] = None, limit_per_file: int = 5) -> dict[str, dict[str, list[dict[str, Any]]]]:
    if not file_ids:
        return {}
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    with _conn(semantics_db) as con:
        for fid in file_ids:
            row = path_index.get_by_id(get_settings().path_index_db, fid)
            path = row.get("path") if row else ""
            if not _is_visible_path(path):
                out[fid] = {"facts": [], "tasks": [], "entities": []}
                continue
            facts = _visible_rows(con.execute(
                "SELECT * FROM local_file_facts WHERE file_id = ? ORDER BY confidence DESC, attribute LIMIT ?",
                (fid, limit_per_file),
            ).fetchall())
            tasks = _visible_rows(con.execute(
                "SELECT * FROM local_file_tasks WHERE file_id = ? ORDER BY status, text LIMIT ?",
                (fid, limit_per_file),
            ).fetchall())
            entities = _visible_rows(con.execute(
                "SELECT * FROM local_file_entities WHERE file_id = ? ORDER BY entity_type, label LIMIT ?",
                (fid, limit_per_file),
            ).fetchall())
            out[fid] = {
                "facts": [_fact_row(r) for r in facts],
                "tasks": [_task_row(r) for r in tasks],
                "entities": [_entity_row(r) for r in entities],
            }
    return out


def _entity_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "file_id": row["file_id"],
        "path": row["path"],
        "entity_type": row["entity_type"],
        "label": row["label"],
        "source_span": row["source_span"],
        "confidence": row["confidence"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def _fact_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "file_id": row["file_id"],
        "path": row["path"],
        "entity": row["entity"],
        "attribute": row["attribute"],
        "value": row["value"],
        "value_num": row["value_num"],
        "unit": row["unit"],
        "period": row["period"],
        "source_span": row["source_span"],
        "confidence": row["confidence"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def _task_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "file_id": row["file_id"],
        "path": row["path"],
        "text": row["text"],
        "status": row["status"],
        "due_date": row["due_date"],
        "source_span": row["source_span"],
        "confidence": row["confidence"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }
