"""
Blueprint generation pipeline — structured knowledge extraction.

A "blueprint" is NOT a summary. A summary compresses content into prose;
a blueprint extracts discrete, queryable knowledge atoms from a capture
(AI conversation or web page) so the system can retrieve and act on them
independently of the original transcript.

Storage: SQLite table `blueprints`, one row per memory_id. JSON blob.

Pipeline:
    /capture succeeds → asyncio.create_task(generate_blueprint(...))
    → call_llm() with structured-extraction prompt
    → parse JSON → store in SQLite
    → blueprint becomes available via GET /browser/blueprint/{id}
    → chat_api injects blueprint highlights into RAG context

The generator is best-effort. Any failure is logged and silently dropped
— the original capture is already saved, so blueprint absence is degraded
service, not data loss.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from apps.shail.llm import call_llm
from apps.shail.settings import get_settings
from apps.shail.dynamic_sizing import compute_budget, compute_window_size

logger = logging.getLogger(__name__)

BLUEPRINT_VERSION = 2

# ── Schema ──────────────────────────────────────────────────────────────────

def init_blueprint_db() -> None:
    """Create the blueprints + memory_facts tables if absent. Called at app startup.

    `memory_facts` is the structured retrieval surface introduced in Sprint 1.
    Lineage columns (`parent_fact_id`, `is_latest`, `superseded_by`) are
    nullable upfront so Sprint 5 lineage rollout is logic-only — no migration.
    `memory_facts_fts` is an FTS5 contentless index synced via triggers.
    """
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS blueprints (
                memory_id   TEXT PRIMARY KEY,
                user_id     TEXT,
                namespace   TEXT,
                version     INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                blueprint   TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                artifact_id TEXT,
                materialization_id TEXT,
                extractor_bundle_version TEXT,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_blueprints_user ON blueprints(user_id);

            CREATE TABLE IF NOT EXISTS memory_facts (
                fact_id        TEXT PRIMARY KEY,
                memory_id      TEXT NOT NULL,
                entity         TEXT,
                attribute      TEXT,
                value          TEXT,
                value_num      REAL,
                unit           TEXT,
                period         TEXT,
                source_span    TEXT,
                confidence     REAL,
                entry_version  INTEGER NOT NULL DEFAULT 1,
                is_latest      INTEGER NOT NULL DEFAULT 1,
                parent_fact_id TEXT,
                superseded_by  TEXT,
                created_at     TEXT NOT NULL,
                artifact_id TEXT,
                materialization_id TEXT,
                extractor_bundle_version TEXT,
                fact_source_type TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_facts_memory   ON memory_facts(memory_id);
            CREATE INDEX IF NOT EXISTS idx_facts_entity   ON memory_facts(entity);
            CREATE INDEX IF NOT EXISTS idx_facts_metric   ON memory_facts(entity, attribute);
            CREATE INDEX IF NOT EXISTS idx_facts_period   ON memory_facts(period);
            CREATE INDEX IF NOT EXISTS idx_facts_latest   ON memory_facts(is_latest);
        """)
        # FTS5 may not be compiled into every SQLite build. Probe before creating.
        if _fts5_available(con):
            con.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_facts_fts USING fts5(
                    entity, attribute, value, period,
                    content='memory_facts', content_rowid='rowid'
                );
                CREATE TRIGGER IF NOT EXISTS memory_facts_ai
                AFTER INSERT ON memory_facts BEGIN
                    INSERT INTO memory_facts_fts(rowid, entity, attribute, value, period)
                    VALUES (new.rowid, new.entity, new.attribute, new.value, new.period);
                END;
                CREATE TRIGGER IF NOT EXISTS memory_facts_ad
                AFTER DELETE ON memory_facts BEGIN
                    INSERT INTO memory_facts_fts(memory_facts_fts, rowid, entity, attribute, value, period)
                    VALUES('delete', old.rowid, old.entity, old.attribute, old.value, old.period);
                END;
                CREATE TRIGGER IF NOT EXISTS memory_facts_au
                AFTER UPDATE ON memory_facts BEGIN
                    INSERT INTO memory_facts_fts(memory_facts_fts, rowid, entity, attribute, value, period)
                    VALUES('delete', old.rowid, old.entity, old.attribute, old.value, old.period);
                    INSERT INTO memory_facts_fts(rowid, entity, attribute, value, period)
                    VALUES (new.rowid, new.entity, new.attribute, new.value, new.period);
                END;
            """)
        else:
            logger.warning(
                "SQLite FTS5 not available; memory_facts_fts skipped. "
                "Exact-recall fallback will use entity/attribute indices only."
            )


def _fts5_available(con: sqlite3.Connection) -> bool:
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        con.execute("DROP TABLE IF EXISTS _fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


# ── Prompts ─────────────────────────────────────────────────────────────────

_EXTRACTION_INSTRUCTION = """Extract the structured knowledge atoms from the capture below.
Output STRICT JSON only — no prose, no markdown fences. Schema:

{
  "summary": "<one sentence — what happened, not what was said>",
  "decisions": [{"statement": "<choice>", "reasoning": "<why>", "confidence": "high|medium|low"}, ...],
  "questions_answered": [{"q": "<question>", "a": "<one-line answer>"}, ...],
  "open_questions": ["<unresolved question or unknown>", ...],
  "next_actions": ["<actionable todo implied by the content>", ...],
  "key_entities": ["<name, lib, person, project, technology>", ...],
  "reasoning_chains": [{"conclusion": "<outcome>", "steps": ["<step1>", ...], "evidence": ["<fact>", ...]}, ...],
  "failed_attempts": [{"approach": "<what was tried>", "failure": "<why it failed>", "lesson": "<takeaway>"}, ...],

  "facts": [
    {"entity": "<noun>", "attribute": "<property>", "value": "<exact text>", "unit": "<unit or null>", "period": "<time scope or null>", "source_span": "<short quote pointer>", "confidence": 0.0}
  ],
  "metrics": [
    {"entity": "<noun>", "metric": "<KPI name>", "value": "<exact text>", "value_num": 0.0, "unit": "<currency, %, count, etc.>", "period": "<time scope>", "source_span": "<short quote pointer>"}
  ],
  "tables": [
    {"title": "<table caption>", "rows": [{"<col>": "<cell>", ...}, ...], "source_span": "<short quote pointer>"}
  ],

  "extensions": {
     "coding": {"languages_used": [], "files_modified": [], "patterns_applied": []},
     "planning": {"milestones_defined": [], "priorities_set": []}
  },

  "conversation_metadata": {
    "turns_analyzed": 0,
    "is_bulk_import": false
  }
}

Rules:
- Empty arrays for fields with nothing to extract — never invent.
- Decisions are CHOICES, not facts. ("chose X over Y", not "X exists")
- Open questions are things still unknown after the conversation.
- Next actions are things the user (not the assistant) should do.
- Entities: 3–8 max, the most central. No generic terms.

STRUCTURED-FACT RULES (CRITICAL — exact recall depends on these):
- DO NOT paraphrase numeric values. Copy them verbatim from source.
  Wrong: "Tesla revenue grew strongly". Right: {"value": "$81B"}.
- For `metrics`, set `value_num` to the numeric value as a JSON number
  (parse "$81B" → 81000000000, "62%" → 62, "4.2%" → 4.2). Use null when
  the value is not numeric.
- `period` examples: "2023", "2023-Q3", "Jan 2025", "FY24". Use null if
  no time scope is stated.
- `source_span` is a short pointer (≤60 chars) into the capture so the
  fact can be cited later. A short verbatim quote is fine.
- If no facts/metrics/tables present, emit empty arrays. Never invent.

Output the JSON object, nothing else.
"""

_AI_CONV_PREFACE = "This is an AI assistant conversation. Extract knowledge from BOTH user messages and assistant replies."
_WEB_PREFACE = "This is a web page captured by the user. Extract the knowledge they likely cared about."


def _build_initial_prompt(content_type: str, content: str) -> tuple[str, str]:
    """Return (system_prompt, user_message) for fresh extraction (no prior Blueprint)."""
    preface = _AI_CONV_PREFACE if content_type == "ai_conversation" else _WEB_PREFACE
    system = (
        "You are a knowledge-extraction engine. You read captures and emit "
        "strict JSON describing the structured atoms inside them. You never "
        "summarize or paraphrase as prose."
    )
    user_msg = f"{preface}\n\n{_EXTRACTION_INSTRUCTION}\n\n--- CAPTURE ---\n{content}\n--- END ---"
    return system, user_msg


def _build_refinement_prompt(content_type: str, content: str, prior: dict) -> tuple[str, str]:
    """Return (system_prompt, user_message) for refining an existing Blueprint."""
    preface = _AI_CONV_PREFACE if content_type == "ai_conversation" else _WEB_PREFACE
    system = (
        "You are a knowledge-evolution engine. You receive an existing Blueprint and "
        "new conversation content, and produce an evolved Blueprint that preserves "
        "durable knowledge while integrating new discoveries. You emit strict JSON only."
    )
    prior_json = json.dumps(prior, ensure_ascii=False, indent=2)
    user_msg = (
        f"{preface}\n\n"
        "You are evolving an existing SHAIL Blueprint with new conversation content.\n\n"
        f"PRIOR BLUEPRINT (durable cognition — preserve unless explicitly contradicted):\n{prior_json}\n\n"
        f"NEW CONVERSATION CONTENT:\n{content}\n\n"
        "EVOLUTION RULES:\n"
        "- decisions in PRIOR are durable. Keep them. Add new ones from NEW.\n"
        "- open_questions: if NEW resolves one, move it to questions_answered.\n"
        "- questions_answered: keep all from PRIOR. Append new Q/A pairs from NEW.\n"
        "- next_actions: replace with current state; completed prior actions drop off.\n"
        "- key_entities, reasoning_chains, failed_attempts: union of PRIOR and NEW (dedup).\n"
        "- summary: rewrite to reflect the full session arc, not just the latest turns.\n"
        "- extensions: union coding/planning arrays from PRIOR and NEW.\n\n"
        "Return ONLY a single JSON object. No preamble, no markdown fences.\n\n"
        f"{_EXTRACTION_INSTRUCTION}"
    )
    return system, user_msg


# ── Parsing ─────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_REQUIRED_FIELDS = (
    "summary", "decisions", "questions_answered",
    "open_questions", "next_actions", "key_entities", "code_references",
)


def _parse_blueprint(raw: str) -> Optional[dict]:
    """Parse the LLM output. Tolerant of code fences and trailing prose.
    Returns None if no valid JSON object can be extracted.
    """
    if not raw:
        return None
    cleaned = _FENCE_RE.sub("", raw.strip())

    # Find the first {...} block — LLMs sometimes emit prose before/after.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = cleaned[start:end + 1]

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    # Coerce missing fields to safe defaults rather than reject — partial
    # blueprints are still useful. Handles v1 -> v2 migrations seamlessly.
    s = get_settings()
    out = {
        "summary": str(data.get("summary") or "")[:s.blueprint_summary_cap_chars],
        "decisions": _coerce_decision_list(data.get("decisions")),
        "questions_answered": _coerce_qa_list(data.get("questions_answered")),
        "open_questions": _coerce_str_list(data.get("open_questions"), cap=s.blueprint_max_open_questions),
        "next_actions": _coerce_str_list(data.get("next_actions"), cap=s.blueprint_max_next_actions),
        "key_entities": _coerce_str_list(data.get("key_entities"), cap=s.blueprint_max_key_entities),
        "reasoning_chains": _coerce_reasoning_list(data.get("reasoning_chains")),
        "failed_attempts": _coerce_failure_list(data.get("failed_attempts")),
        # Sprint 1: structured retrieval surfaces. Empty by default so old
        # blueprints (without these keys) deserialize unchanged.
        "facts":   _coerce_fact_list(data.get("facts")),
        "metrics": _coerce_metric_list(data.get("metrics")),
        "tables":  _coerce_table_list(data.get("tables")),
        "extensions": _coerce_extensions(data.get("extensions")),
    }
    
    # Backward compat: v1 had code_references at the top level
    if "code_references" in data:
        if "coding" not in out["extensions"]:
            out["extensions"]["coding"] = {}
        out["extensions"]["coding"]["code_references"] = _coerce_code_list(data["code_references"])

    return out


def _coerce_str_list(v, *, cap: Optional[int] = None) -> list[str]:
    if not isinstance(v, list):
        return []
    s = get_settings()
    effective_cap = cap if cap is not None else s.blueprint_max_open_questions
    item_cap = s.blueprint_value_cap_chars
    return [str(x).strip()[:item_cap] for x in v if isinstance(x, (str, int, float)) and str(x).strip()][:effective_cap]


def _coerce_qa_list(v) -> list[dict]:
    if not isinstance(v, list):
        return []
    s = get_settings()
    out = []
    item_cap = s.blueprint_value_cap_chars
    for item in v[:s.blueprint_max_qa]:
        if isinstance(item, dict):
            q = str(item.get("q") or item.get("question") or "").strip()[:item_cap]
            a = str(item.get("a") or item.get("answer") or "").strip()[:item_cap]
            if q:
                out.append({"q": q, "a": a})
    return out


def _coerce_code_list(v) -> list[dict]:
    if not isinstance(v, list):
        return []
    s = get_settings()
    out = []
    for item in v[:s.blueprint_max_code_refs]:
        if isinstance(item, dict):
            out.append({
                "language": str(item.get("language") or "").strip()[:30],
                "purpose":  str(item.get("purpose")  or "").strip()[:s.blueprint_value_cap_chars],
            })
    return out


def _coerce_extensions(v) -> dict:
    if not isinstance(v, dict):
        return {}
    return v


# ── Sprint 1: structured-fact coercers ──────────────────────────────────────


def _strip_or_none(v, cap: int = 200) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return s[:cap]


def _to_float_or_none(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _coerce_fact_list(v) -> list[dict]:
    """Generic structured facts. Tolerant: missing keys → None."""
    if not isinstance(v, list):
        return []
    s = get_settings()
    out: list[dict] = []
    for item in v[:s.blueprint_max_facts]:
        if not isinstance(item, dict):
            continue
        entity = _strip_or_none(item.get("entity"))
        attribute = _strip_or_none(item.get("attribute"))
        value = _strip_or_none(item.get("value"), s.blueprint_value_cap_chars)
        # Require at least entity OR attribute OR value to be non-empty.
        if not any((entity, attribute, value)):
            continue
        confidence = _to_float_or_none(item.get("confidence"))
        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))
        out.append({
            "entity":      entity,
            "attribute":   attribute,
            "value":       value,
            "unit":        _strip_or_none(item.get("unit"), 60),
            "period":      _strip_or_none(item.get("period"), 120),
            "source_span": _strip_or_none(item.get("source_span"), 400),
            "confidence":  confidence,
        })
    return out


def _coerce_metric_list(v) -> list[dict]:
    """Numeric KPI rows. `metric` key normalized into `attribute` for storage."""
    if not isinstance(v, list):
        return []
    s = get_settings()
    out: list[dict] = []
    for item in v[:s.blueprint_max_metrics]:
        if not isinstance(item, dict):
            continue
        entity = _strip_or_none(item.get("entity"))
        # Accept either "metric" or "attribute" as the attribute name.
        attribute = _strip_or_none(item.get("metric") or item.get("attribute"))
        value = _strip_or_none(item.get("value"), s.blueprint_value_cap_chars)
        if not any((entity, attribute, value)):
            continue
        out.append({
            "entity":      entity,
            "attribute":   attribute,
            "value":       value,
            "value_num":   _to_float_or_none(item.get("value_num")),
            "unit":        _strip_or_none(item.get("unit"), 60),
            "period":      _strip_or_none(item.get("period"), 120),
            "source_span": _strip_or_none(item.get("source_span"), 400),
        })
    return out


def _coerce_table_list(v) -> list[dict]:
    if not isinstance(v, list):
        return []
    s = get_settings()
    out: list[dict] = []
    for item in v[:s.blueprint_max_tables]:
        if not isinstance(item, dict):
            continue
        title = _strip_or_none(item.get("title"), 400) or ""
        rows_raw = item.get("rows")
        rows: list[dict] = []
        if isinstance(rows_raw, list):
            for row in rows_raw[:s.blueprint_max_table_rows]:
                if isinstance(row, dict):
                    rows.append({
                        str(k)[:120]: _strip_or_none(val, s.blueprint_value_cap_chars) or ""
                        for k, val in row.items()
                    })
        out.append({
            "title":       title,
            "rows":        rows,
            "source_span": _strip_or_none(item.get("source_span"), 400),
        })
    return out


def _coerce_decision_list(v) -> list[dict]:
    if not isinstance(v, list):
        return []
    s = get_settings()
    item_cap = s.blueprint_value_cap_chars
    out = []
    for item in v[:s.blueprint_max_decisions]:
        if isinstance(item, str):
            out.append({"statement": item.strip()[:item_cap], "reasoning": None, "confidence": "medium"})
        elif isinstance(item, dict):
            stmt = str(item.get("statement") or "").strip()[:item_cap]
            if stmt:
                out.append({
                    "statement": stmt,
                    "reasoning": str(item.get("reasoning") or "").strip()[:item_cap] or None,
                    "confidence": str(item.get("confidence") or "medium").strip()[:20]
                })
    return out


def _coerce_reasoning_list(v) -> list[dict]:
    if not isinstance(v, list):
        return []
    s = get_settings()
    item_cap = s.blueprint_value_cap_chars
    out = []
    for item in v[:s.blueprint_max_reasoning_chains]:
        if isinstance(item, dict):
            conc = str(item.get("conclusion") or "").strip()[:item_cap]
            if conc:
                out.append({
                    "conclusion": conc,
                    "steps": _coerce_str_list(item.get("steps"), cap=s.blueprint_max_open_questions),
                    "evidence": _coerce_str_list(item.get("evidence"), cap=s.blueprint_max_open_questions),
                })
    return out


def _coerce_failure_list(v) -> list[dict]:
    if not isinstance(v, list):
        return []
    s = get_settings()
    item_cap = s.blueprint_value_cap_chars
    out = []
    for item in v[:s.blueprint_max_failed_attempts]:
        if isinstance(item, dict):
            appr = str(item.get("approach") or "").strip()[:item_cap]
            fail = str(item.get("failure") or "").strip()[:item_cap]
            if appr or fail:
                out.append({
                    "approach": appr,
                    "failure": fail,
                    "lesson": str(item.get("lesson") or "").strip()[:item_cap]
                })
    return out


# ── Defensive merge ─────────────────────────────────────────────────────────

def _merge_blueprints(prior: dict, updated: dict) -> dict:
    """Union-merge accumulating fields so no durable knowledge is lost even if
    the refinement LLM omits items from the prior Blueprint.
    """
    def _union_by_key(a: list, b: list, key: str, cap: int) -> list:
        seen: set = set()
        result = []
        for item in list(a) + list(b):
            if isinstance(item, dict):
                k = str(item.get(key) or "").strip().lower()
                if k and k not in seen:
                    seen.add(k)
                    result.append(item)
        return result[:cap]

    def _union_str(a: list, b: list, cap: int) -> list:
        seen: set = set()
        result = []
        for item in list(a) + list(b):
            s = str(item).strip().lower()
            if s and s not in seen:
                seen.add(s)
                result.append(item)
        return result[:cap]

    s = get_settings()
    merged = dict(updated)
    merged["decisions"] = _union_by_key(
        prior.get("decisions", []), updated.get("decisions", []),
        "statement", s.blueprint_max_decisions,
    )
    merged["questions_answered"] = _union_by_key(
        prior.get("questions_answered", []), updated.get("questions_answered", []),
        "q", s.blueprint_max_qa,
    )
    merged["open_questions"] = _union_str(
        prior.get("open_questions", []), updated.get("open_questions", []),
        s.blueprint_max_open_questions,
    )
    merged["next_actions"] = _union_str(
        prior.get("next_actions", []), updated.get("next_actions", []),
        s.blueprint_max_next_actions,
    )
    merged["key_entities"] = _union_str(
        prior.get("key_entities", []), updated.get("key_entities", []),
        s.blueprint_max_key_entities,
    )
    merged["reasoning_chains"] = _union_by_key(
        prior.get("reasoning_chains", []), updated.get("reasoning_chains", []),
        "conclusion", s.blueprint_max_reasoning_chains,
    )
    merged["failed_attempts"] = _union_by_key(
        prior.get("failed_attempts", []), updated.get("failed_attempts", []),
        "approach", s.blueprint_max_failed_attempts,
    )
    # Union the structured-retrieval surfaces too — they're additive across
    # windows in chunked extraction, so each window's contribution must survive.
    merged["facts"] = _union_by_key(
        prior.get("facts", []), updated.get("facts", []),
        "value", s.blueprint_max_facts,
    )
    merged["metrics"] = _union_by_key(
        prior.get("metrics", []), updated.get("metrics", []),
        "value", s.blueprint_max_metrics,
    )
    merged["tables"] = _union_by_key(
        prior.get("tables", []), updated.get("tables", []),
        "title", s.blueprint_max_tables,
    )
    return merged


# ── CRUD ────────────────────────────────────────────────────────────────────

def save_blueprint(
    memory_id: str,
    blueprint: dict,
    *,
    user_id: Optional[str],
    namespace: str,
    content_type: str,
    artifact_id: Optional[str] = None,
    materialization_id: Optional[str] = None,
    extractor_bundle_version: Optional[str] = None,
    fact_source_type: str = "blueprint",
) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(settings.sqlite_path) as con:
        con.execute(
            "INSERT OR REPLACE INTO blueprints "
            "("
            "memory_id, user_id, namespace, version, content_type, blueprint, created_at, "
            "artifact_id, materialization_id, extractor_bundle_version, updated_at"
            ") "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                memory_id,
                user_id,
                namespace,
                BLUEPRINT_VERSION,
                content_type,
                json.dumps(blueprint, ensure_ascii=False),
                now,
                artifact_id,
                materialization_id,
                extractor_bundle_version,
                now,
            ),
        )

        # Sprint 1 PR3: structured-fact write path. Flag-gated, default OFF.
        # Same connection ⇒ blueprint + facts share one transaction.
        # Failures here must not break blueprint persistence — best-effort.
        if settings.shail_exact_index_write:
            try:
                from apps.shail.exact_index import (
                    collect_blueprint_facts,
                    upsert_facts,
                    upsert_facts_versioned,
                )
                rows = collect_blueprint_facts(blueprint)
                if rows:
                    for row in rows:
                        row["artifact_id"] = artifact_id
                        row["materialization_id"] = materialization_id
                        row["extractor_bundle_version"] = extractor_bundle_version
                        row["fact_source_type"] = fact_source_type
                    # Sprint 5 PR2: route to versioned writer when lineage
                    # flag is ON. Plain UPSERT otherwise (legacy behavior).
                    if settings.shail_blueprint_versioning:
                        upsert_facts_versioned(memory_id, rows, con=con)
                    else:
                        upsert_facts(memory_id, rows, con=con)
            except Exception:  # noqa: BLE001 — protect blueprint write at all costs
                logger.exception(
                    "memory_facts upsert failed for memory_id=%s; "
                    "blueprint row preserved. Investigate exact_index logs.",
                    memory_id,
                )


def get_blueprint(memory_id: str) -> Optional[dict]:
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT blueprint, content_type, created_at, version, artifact_id, materialization_id, "
            "extractor_bundle_version, updated_at "
            "FROM blueprints WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
    if not row:
        return None
    try:
        bp = json.loads(row["blueprint"])
    except json.JSONDecodeError:
        return None
    return {
        "memory_id": memory_id,
        "version": row["version"],
        "content_type": row["content_type"],
        "created_at": row["created_at"],
        "artifact_id": row["artifact_id"],
        "materialization_id": row["materialization_id"],
        "extractor_bundle_version": row["extractor_bundle_version"],
        "updated_at": row["updated_at"],
        **bp,
    }


def get_blueprint_ids(memory_ids: list[str]) -> set[str]:
    """Return the subset of memory_ids that have a blueprint row.
    Used by the Memories list to render a BLUEPRINT badge without
    fetching the full blueprint per card.
    """
    if not memory_ids:
        return set()
    path = get_settings().sqlite_path
    placeholders = ",".join("?" for _ in memory_ids)
    with sqlite3.connect(path) as con:
        rows = con.execute(
            f"SELECT memory_id FROM blueprints WHERE memory_id IN ({placeholders})",
            memory_ids,
        ).fetchall()
    return {r[0] for r in rows}


def get_blueprints_for_ids(memory_ids: list[str]) -> dict[str, dict]:
    """Batch fetch — one query for multiple ids. Used by chat_api RAG."""
    if not memory_ids:
        return {}
    path = get_settings().sqlite_path
    placeholders = ",".join("?" for _ in memory_ids)
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT memory_id, blueprint FROM blueprints WHERE memory_id IN ({placeholders})",
            memory_ids,
        ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        try:
            out[r["memory_id"]] = json.loads(r["blueprint"])
        except json.JSONDecodeError:
            continue
    return out


def delete_blueprint(memory_id: str) -> None:
    path = get_settings().sqlite_path
    with sqlite3.connect(path) as con:
        con.execute("DELETE FROM blueprints WHERE memory_id = ?", (memory_id,))


# ── Generation ──────────────────────────────────────────────────────────────

async def generate_blueprint(
    memory_id: str,
    *,
    content: str,
    content_type: str,
    user_id: Optional[str],
    namespace: str,
    artifact_id: Optional[str] = None,
    materialization_id: Optional[str] = None,
    extractor_bundle_version: Optional[str] = None,
    fact_source_type: str = "blueprint",
) -> Optional[dict]:
    """Run extraction/refinement with dynamic, context-aware sizing.

    Sizing strategy (replaces the old hard 14K/16K caps):
      1. Compute the per-call content budget from the live model context
         window minus prompt overhead, prior-blueprint payload, and a
         response reserve.
      2. If content fits the budget, run a single LLM call.
      3. Otherwise split into overlapping windows, extract one partial
         blueprint per window, and reduce-merge them. The prior blueprint
         (if any) is folded in as the seed of the reduction.

    On parse failure with a prior, the prior is preserved.
    """
    from apps.shail import pipeline_status as _ps

    if not content or len(content.strip()) < 40:
        return None

    prior = get_blueprint(memory_id)
    prior_payload_chars = len(json.dumps(prior, ensure_ascii=False)) if prior else 0

    budget = compute_budget(prior_blueprint_chars=prior_payload_chars)
    content_chars = len(content)

    _ps.mark_stage(
        memory_id, "blueprint_extracting", "active",
        size_bytes=content_chars,
        detail={
            "budget": budget.to_dict(),
            "prior_present": bool(prior),
            "strategy": "single" if content_chars <= budget.content_budget_chars else "chunked",
        },
    )

    logger.info(
        "blueprint %s: content=%d chars, budget=%d chars, prior=%d chars, mode=%s",
        memory_id, content_chars, budget.content_budget_chars, prior_payload_chars,
        "refine" if prior else "fresh",
    )

    try:
        if content_chars <= budget.content_budget_chars:
            bp = await _extract_single(content, content_type, user_id, prior)
        else:
            bp = await _extract_chunked(
                memory_id=memory_id,
                content=content,
                content_type=content_type,
                user_id=user_id,
                prior=prior,
                prior_payload_chars=prior_payload_chars,
            )
    except Exception as e:
        logger.warning("blueprint LLM call failed for %s: %s", memory_id, e)
        _ps.mark_stage(memory_id, "blueprint_extracting", "failed", error=str(e)[:500])
        return None

    if not bp:
        logger.warning("blueprint parse failed for %s", memory_id)
        _ps.mark_stage(memory_id, "blueprint_extracting", "failed",
                       error="parse_failure_or_empty")
        if prior:
            logger.info("blueprint parse failed — preserving prior for %s", memory_id)
            return prior
        return None

    try:
        save_blueprint(memory_id, bp,
                       user_id=user_id, namespace=namespace, content_type=content_type,
                       artifact_id=artifact_id,
                       materialization_id=materialization_id,
                       extractor_bundle_version=extractor_bundle_version,
                       fact_source_type=fact_source_type)
        bp_bytes = len(json.dumps(bp, ensure_ascii=False))
        _ps.mark_stage(memory_id, "blueprint_extracting", "done", size_bytes=bp_bytes)
        _ps.mark_stage(memory_id, "blueprint_ready", "done", size_bytes=bp_bytes)
    except Exception as e:
        logger.warning("blueprint save failed for %s: %s", memory_id, e)
        _ps.mark_stage(memory_id, "blueprint_extracting", "failed", error=str(e)[:500])
        return None
    return bp


async def _extract_single(
    content: str,
    content_type: str,
    user_id: Optional[str],
    prior: Optional[dict],
) -> Optional[dict]:
    """One LLM call. No truncation here — caller guarantees content fits."""
    return await extract_blueprint(
        content=content,
        content_type=content_type,
        user_id=user_id,
        prior=prior,
    )


async def _extract_chunked(
    *,
    memory_id: str,
    content: str,
    content_type: str,
    user_id: Optional[str],
    prior: Optional[dict],
    prior_payload_chars: int,
) -> Optional[dict]:
    """Split content into windows, extract each, reduce-merge.

    The merge is initialized with `prior` (so durable cognition survives) and
    each window's output is union-merged in. The result is the final blueprint
    spanning the full content — no tail loss.
    """
    window_size, overlap = compute_window_size(
        transcript_chars=len(content),
        prior_blueprint_chars=prior_payload_chars,
    )
    if overlap >= window_size:
        overlap = window_size // 5

    step = max(1, window_size - overlap)
    windows: list[str] = []
    pos = 0
    while pos < len(content):
        end = min(pos + window_size, len(content))
        windows.append(content[pos:end])
        if end == len(content):
            break
        pos += step

    logger.info(
        "blueprint %s chunked: %d windows of %d chars (overlap=%d)",
        memory_id, len(windows), window_size, overlap,
    )

    merged: Optional[dict] = prior  # may be None
    for idx, win in enumerate(windows):
        try:
            window_bp = await extract_blueprint(
                content=win,
                content_type=content_type,
                user_id=user_id,
                prior=merged,
            )
        except Exception as e:
            logger.warning("blueprint window %d/%d failed for %s: %s",
                           idx + 1, len(windows), memory_id, e)
            continue
        if not window_bp:
            continue
        if merged is None:
            merged = window_bp
        else:
            merged = _merge_blueprints(merged, window_bp)
    return merged


async def extract_blueprint(
    *,
    content: str,
    content_type: str,
    user_id: Optional[str],
    prior: Optional[dict] = None,
    refinement_prompts: Optional[tuple[str, str]] = None,
) -> Optional[dict]:
    """Extract a parsed blueprint without persisting it."""
    if not content or len(content.strip()) < 40:
        return None
    if refinement_prompts is not None:
        system_prompt, user_msg = refinement_prompts
    elif prior:
        system_prompt, user_msg = _build_refinement_prompt(content_type, content, prior)
    else:
        system_prompt, user_msg = _build_initial_prompt(content_type, content)

    raw, _meta = await call_llm(
        messages=[{"role": "user", "content": user_msg}],
        user_id=user_id,
        system_prompt=system_prompt,
    )
    bp = _parse_blueprint(raw)
    if not bp:
        return None
    if prior:
        bp = _merge_blueprints(prior, bp)
    return bp


# ── Context formatter for RAG ───────────────────────────────────────────────

def format_blueprint_for_context(bp: dict, *, max_lines: int = 8) -> str:
    """Render a blueprint as a compact context block for chat RAG.
    Highlights the actionable atoms (decisions, open_questions, next_actions)
    first because those are what make blueprint > summary for chat.
    Handles both v1 and v2 blueprints gracefully.
    """
    lines: list[str] = []
    
    if bp.get("decisions"):
        for d in bp["decisions"][:3]:
            if isinstance(d, str):
                lines.append(f"  • decided: {d}")
            elif isinstance(d, dict) and d.get("statement"):
                rsn = f" (because: {d['reasoning']})" if d.get("reasoning") else ""
                lines.append(f"  • decided: {d['statement']}{rsn}")
                
    if bp.get("open_questions"):
        for q in bp["open_questions"][:2]:
            lines.append(f"  • open: {q}")
            
    if bp.get("next_actions"):
        for a in bp["next_actions"][:2]:
            lines.append(f"  • todo: {a}")
            
    if bp.get("failed_attempts"):
        for f in bp["failed_attempts"][:1]:
            if isinstance(f, dict) and f.get("approach"):
                lines.append(f"  • failed attempt: {f['approach']} -> {f.get('lesson', '')}")
                
    if bp.get("key_entities"):
        ents = ", ".join(bp["key_entities"][:5])
        if ents:
            lines.append(f"  • entities: {ents}")
            
    # Extract extensions summary if present
    ext = bp.get("extensions", {})
    if isinstance(ext, dict) and "coding" in ext:
        coding = ext["coding"]
        if isinstance(coding, dict) and coding.get("files_modified"):
            files = ", ".join(coding["files_modified"][:3])
            lines.append(f"  • files changed: {files}")
            
    return "\n".join(lines[:max_lines])
