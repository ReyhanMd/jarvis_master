"""Exact-retrieval index over `memory_facts` (Sprint 1+).

Sprint 1 PR1 lands schema + init guard.
Sprint 1 PR3 adds the plain (non-versioned) writer.
Readers (`search_fts`, `search_numeric`) ship in Sprint 2.
Versioned writer (`upsert_fact_versioned`) ships in Sprint 5 PR2.

Local-first: SQLite + FTS5. No external services. All callers must
hold a shared connection or open one against `Settings.sqlite_path`.
"""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from apps.shail import telemetry
from apps.shail.settings import get_settings

logger = logging.getLogger(__name__)


def init() -> None:
    """Idempotent schema bootstrap. Delegates to `init_blueprint_db`.

    Kept as a separate entry point so callers can express intent
    (`exact_index.init()`) without importing blueprints.
    """
    # Imported lazily to avoid circular import at module load.
    from apps.shail.blueprints import init_blueprint_db
    init_blueprint_db()


def get_connection() -> sqlite3.Connection:
    """Open a connection against the configured SQLite path. Caller closes."""
    return sqlite3.connect(get_settings().sqlite_path)


def has_fts5(con: Optional[sqlite3.Connection] = None) -> bool:
    """Detect FTS5 support at runtime. Used by readers to choose code path."""
    own = False
    if con is None:
        con = get_connection()
        own = True
    try:
        cur = con.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='memory_facts_fts'"
        )
        return cur.fetchone() is not None
    finally:
        if own:
            con.close()


# ── Sprint 1 PR3: writer ────────────────────────────────────────────────────


def compute_fact_id(memory_id: str, entity: Optional[str], attribute: Optional[str],
                    period: Optional[str]) -> str:
    """Stable hash so re-extraction of the same fact does not duplicate rows.

    Inputs deliberately exclude `value` — value updates are caught at UPSERT
    time and (in Sprint 5) trigger lineage flips. Entity/attribute/period
    define the IDENTITY of a fact within a memory.
    """
    h = hashlib.sha256()
    parts = (
        memory_id or "",
        (entity or "").strip().lower(),
        (attribute or "").strip().lower(),
        (period or "").strip().lower(),
    )
    h.update("|".join(parts).encode("utf-8"))
    return h.hexdigest()[:32]


def _row_from_fact(memory_id: str, fact: dict, *, now_iso: str) -> tuple:
    entity = fact.get("entity")
    attribute = fact.get("attribute")
    period = fact.get("period")
    fact_id = compute_fact_id(memory_id, entity, attribute, period)
    return (
        fact_id,
        memory_id,
        entity,
        attribute,
        fact.get("value"),
        fact.get("value_num"),
        fact.get("unit"),
        period,
        fact.get("source_span"),
        fact.get("confidence"),
        fact.get("artifact_id"),
        fact.get("materialization_id"),
        fact.get("extractor_bundle_version"),
        fact.get("fact_source_type"),
        now_iso,
    )


def upsert_facts_versioned(
    memory_id: str,
    facts: Iterable[dict],
    *,
    con: Optional[sqlite3.Connection] = None,
) -> int:
    """Versioned UPSERT — flips prior `is_latest=0`, links lineage chain.

    Identity key (entity, attribute, period) routes a new fact to existing
    lineage even across `memory_id` boundaries (e.g. different captures
    reporting the same metric). When a value changes:
      1. Find the latest existing row matching identity (`is_latest=1`).
      2. Generate a NEW `fact_id` for this version (random suffix to avoid
         collision with the deterministic plain-writer hash).
      3. Insert new row with `parent_fact_id` = prior, `entry_version` = +1.
      4. Update prior row: `is_latest=0`, `superseded_by=<new_fact_id>`.
    All writes share one transaction.

    Behind `SHAIL_BLUEPRINT_VERSIONING` flag at the caller. When values are
    unchanged, no-op (no new row, no flip).
    """
    facts = [f for f in facts if isinstance(f, dict)]
    if not facts:
        return 0

    own = False
    if con is None:
        con = get_connection()
        own = True

    now = datetime.now(timezone.utc).isoformat()
    written = 0
    try:
        for f in facts:
            entity = f.get("entity")
            attribute = f.get("attribute")
            period = f.get("period")
            new_value = f.get("value")
            new_value_num = f.get("value_num")
            unit = f.get("unit")
            source_span = f.get("source_span")
            confidence = f.get("confidence")

            row = con.execute(
                """
                SELECT fact_id, value, value_num, entry_version
                FROM memory_facts
                WHERE is_latest = 1
                  AND COALESCE(LOWER(entity),'')    = COALESCE(LOWER(?),'')
                  AND COALESCE(LOWER(attribute),'') = COALESCE(LOWER(?),'')
                  AND COALESCE(LOWER(period),'')    = COALESCE(LOWER(?),'')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (entity, attribute, period),
            ).fetchone()

            if row is None:
                # First version — plain insert with fresh deterministic id.
                fact_id = compute_fact_id(memory_id, entity, attribute, period)
                con.execute(
                    """
                    INSERT INTO memory_facts (
                        fact_id, memory_id, entity, attribute, value, value_num,
                        unit, period, source_span, confidence,
                        entry_version, is_latest, parent_fact_id, superseded_by,
                        artifact_id, materialization_id, extractor_bundle_version, fact_source_type,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, NULL, NULL, ?, ?, ?, ?, ?)
                    ON CONFLICT(fact_id) DO UPDATE SET
                        value = excluded.value,
                        value_num = excluded.value_num,
                        unit = excluded.unit,
                        source_span = excluded.source_span,
                        confidence = excluded.confidence,
                        artifact_id = excluded.artifact_id,
                        materialization_id = excluded.materialization_id,
                        extractor_bundle_version = excluded.extractor_bundle_version,
                        fact_source_type = excluded.fact_source_type,
                        created_at = excluded.created_at
                    """,
                    (fact_id, memory_id, entity, attribute, new_value, new_value_num,
                     unit, period, source_span, confidence,
                     f.get("artifact_id"), f.get("materialization_id"),
                     f.get("extractor_bundle_version"), f.get("fact_source_type"), now),
                )
                written += 1
                continue

            prior_id, prior_value, prior_value_num, prior_version = row
            unchanged = (
                str(prior_value or "") == str(new_value or "")
                and (prior_value_num is None and new_value_num is None
                     or prior_value_num == new_value_num)
            )
            if unchanged:
                # No-op: identity + value identical → skip lineage flip.
                continue

            # Insert new version. Use unique fact_id so the deterministic
            # identity hash does not collide with the prior row.
            new_fact_id = hashlib.sha256(
                f"{prior_id}|{now}|{written}".encode("utf-8")
            ).hexdigest()[:32]
            con.execute(
                """
                INSERT INTO memory_facts (
                    fact_id, memory_id, entity, attribute, value, value_num,
                    unit, period, source_span, confidence,
                    entry_version, is_latest, parent_fact_id, superseded_by,
                    artifact_id, materialization_id, extractor_bundle_version, fact_source_type,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (new_fact_id, memory_id, entity, attribute, new_value, new_value_num,
                 unit, period, source_span, confidence,
                 int(prior_version or 0) + 1, prior_id,
                 f.get("artifact_id"), f.get("materialization_id"),
                 f.get("extractor_bundle_version"), f.get("fact_source_type"), now),
            )
            con.execute(
                "UPDATE memory_facts SET is_latest = 0, superseded_by = ? "
                "WHERE fact_id = ?",
                (new_fact_id, prior_id),
            )
            telemetry.observe(telemetry.BLUEPRINT_VERSIONS_PER_FACT, prior_version + 1)
            written += 1
        if own:
            con.commit()
    finally:
        if own:
            con.close()

    return written


def upsert_facts(
    memory_id: str,
    facts: Iterable[dict],
    *,
    con: Optional[sqlite3.Connection] = None,
) -> int:
    """Plain (non-versioned) UPSERT of fact rows for a memory.

    `con` may be supplied so the caller wraps blueprint + facts writes in
    a single transaction. Returns the number of rows written.
    Sprint 5 will introduce `upsert_facts_versioned` which flips
    `is_latest` on existing rows; this function leaves `is_latest=1`
    on every write (safe default per current schema).
    """
    facts = [f for f in facts if isinstance(f, dict)]
    if not facts:
        return 0

    own = False
    if con is None:
        con = get_connection()
        own = True

    now = datetime.now(timezone.utc).isoformat()
    rows = [_row_from_fact(memory_id, f, now_iso=now) for f in facts]

    try:
        con.executemany(
            """
            INSERT INTO memory_facts (
                fact_id, memory_id, entity, attribute, value, value_num,
                unit, period, source_span, confidence,
                artifact_id, materialization_id, extractor_bundle_version, fact_source_type,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fact_id) DO UPDATE SET
                value       = excluded.value,
                value_num   = excluded.value_num,
                unit        = excluded.unit,
                source_span = excluded.source_span,
                confidence  = excluded.confidence,
                artifact_id = excluded.artifact_id,
                materialization_id = excluded.materialization_id,
                extractor_bundle_version = excluded.extractor_bundle_version,
                fact_source_type = excluded.fact_source_type,
                created_at  = excluded.created_at
            """,
            rows,
        )
        if own:
            con.commit()
    finally:
        if own:
            con.close()

    telemetry.incr(telemetry.BLUEPRINT_FACTS_EXTRACTED, value=float(len(rows)))
    return len(rows)


def collect_blueprint_facts(blueprint: dict) -> list[dict]:
    """Flatten the parsed blueprint's `facts[]` + `metrics[]` into write rows.

    Tables are NOT exploded into facts here — they are stored as-is in the
    blueprint JSON and considered for retrieval as structured payload.
    """
    out: list[dict] = []
    for f in blueprint.get("facts") or []:
        if isinstance(f, dict):
            out.append(f)
    for m in blueprint.get("metrics") or []:
        if isinstance(m, dict):
            out.append(m)
    return out


# ── Sprint 2 PR1+PR2: readers ───────────────────────────────────────────────


@dataclass(frozen=True)
class ExactHit:
    """Single result row from an exact-index query.

    `score` is normalized to [0,1] for fusion with semantic-cosine scores.
    `raw_score` preserves the underlying signal (BM25 magnitude or 1.0 for
    numeric exact match) for diagnostics.
    """
    fact_id: str
    memory_id: str
    entity: Optional[str]
    attribute: Optional[str]
    value: Optional[str]
    value_num: Optional[float]
    unit: Optional[str]
    period: Optional[str]
    source_span: Optional[str]
    confidence: Optional[float]
    score: float
    raw_score: float
    surface: str  # "fts" | "numeric"

    def as_dict(self) -> dict:
        return asdict(self)


_FACT_COLS = (
    "fact_id, memory_id, entity, attribute, value, value_num, "
    "unit, period, source_span, confidence"
)
# Qualified form for JOIN queries where column names collide with FTS5 shadow.
_FACT_COLS_MF = ", ".join(f"mf.{c}" for c in (
    "fact_id", "memory_id", "entity", "attribute", "value", "value_num",
    "unit", "period", "source_span", "confidence",
))


def _row_to_hit(row: tuple, *, score: float, raw_score: float, surface: str) -> ExactHit:
    return ExactHit(
        fact_id=row[0], memory_id=row[1],
        entity=row[2], attribute=row[3], value=row[4], value_num=row[5],
        unit=row[6], period=row[7], source_span=row[8], confidence=row[9],
        score=score, raw_score=raw_score, surface=surface,
    )


# ── PR1: FTS5 search ────────────────────────────────────────────────────────

# FTS5 special chars per https://sqlite.org/fts5.html#full_text_query_syntax
_FTS_SPECIAL = re.compile(r'[\"\(\)\:\*\^]')


def _sanitize_fts_query(q: str) -> str:
    """Strip FTS5 syntax chars and quote each token to avoid query-parse errors.

    Tokens like `$1.5M`, `62%`, `2023-Q3` are preserved as quoted phrases so
    the FTS5 tokenizer matches them literally where stored.
    """
    cleaned = _FTS_SPECIAL.sub(" ", q or "")
    tokens = [t for t in re.split(r"\s+", cleaned.strip()) if t]
    return " ".join(f'"{t}"' for t in tokens)


def _normalize_bm25(raw: float) -> float:
    """SQLite FTS5 returns BM25 as `-1 * bm25_value` (lower = better match).

    Map to [0,1] via `1 / (1 + |raw|)`. Bounded, monotonic, deterministic.
    """
    return 1.0 / (1.0 + abs(raw))


def search_fts(
    query: str,
    k: int = 10,
    *,
    con: Optional[sqlite3.Connection] = None,
) -> List[ExactHit]:
    """BM25 FTS5 search over `memory_facts_fts` joined back to `memory_facts`.

    Returns up to `k` hits, sorted best-first, with `score` normalized to
    [0,1]. Empty/whitespace queries return `[]`. If FTS5 is unavailable,
    returns `[]` (caller falls back to other surfaces).
    """
    q = (query or "").strip()
    if not q or k <= 0:
        return []

    own = False
    if con is None:
        con = get_connection()
        own = True
    try:
        if not has_fts5(con):
            return []
        match = _sanitize_fts_query(q)
        if not match:
            return []
        try:
            cur = con.execute(
                f"""
                SELECT {_FACT_COLS_MF}, fts.rank
                FROM memory_facts_fts AS fts
                JOIN memory_facts AS mf ON mf.rowid = fts.rowid
                WHERE memory_facts_fts MATCH ?
                ORDER BY fts.rank
                LIMIT ?
                """,
                (match, int(k)),
            )
            rows = cur.fetchall()
        except sqlite3.OperationalError as exc:
            # Malformed query slipping past sanitizer → empty result, not crash.
            logger.warning("FTS5 query failed for input %r: %s", q, exc)
            return []
    finally:
        if own:
            con.close()

    settings = get_settings()
    hits = [
        _row_to_hit(
            r[:10],
            score=_normalize_bm25(float(r[10])),
            raw_score=float(r[10]),
            surface="fts",
        )
        for r in rows
    ]
    if settings.shail_retrieval_debug:
        logger.info(
            "exact_index.search_fts q=%r k=%d hits=%d top_score=%.3f",
            q, k, len(hits), hits[0].score if hits else 0.0,
        )
    return hits


# ── PR2: numeric / structured filter search ─────────────────────────────────


@dataclass(frozen=True)
class NumericFilter:
    """Structured filter for numeric/period-aware retrieval.

    Any field may be None — only non-None constraints are applied.
    `op` is one of: '>', '<', '>=', '<=', '='. None means no comparison.
    """
    entity: Optional[str] = None
    attribute: Optional[str] = None
    period: Optional[str] = None
    op: Optional[str] = None
    value_num: Optional[float] = None
    unit: Optional[str] = None

    def is_empty(self) -> bool:
        return all(getattr(self, f) is None for f in (
            "entity", "attribute", "period", "op", "value_num", "unit"
        ))


_OP_TO_SQL = {">": ">", "<": "<", ">=": ">=", "<=": "<=", "=": "="}


def search_numeric_historical(
    flt: NumericFilter,
    k: int = 10,
    *,
    con: Optional[sqlite3.Connection] = None,
) -> List[ExactHit]:
    """Like `search_numeric` but returns historical (`is_latest=0`) rows too.

    Used when the query carries an "as of" / "previously" intent. Sorted
    newest-first within the matched set so the most recent prior version
    surfaces first. Falls back to current rows when no historical exist.
    """
    if flt is None or flt.is_empty() or k <= 0:
        return []

    where: list[str] = []  # NO is_latest filter — full lineage in scope
    params: list = []
    if flt.entity is not None:
        where.append("LOWER(entity) = LOWER(?)")
        params.append(flt.entity.strip())
    if flt.attribute is not None:
        where.append("LOWER(attribute) = LOWER(?)")
        params.append(flt.attribute.strip())
    if flt.period is not None:
        where.append("LOWER(period) = LOWER(?)")
        params.append(flt.period.strip())
    if flt.unit is not None:
        where.append("LOWER(unit) = LOWER(?)")
        params.append(flt.unit.strip())
    if flt.op is not None and flt.value_num is not None:
        sql_op = _OP_TO_SQL.get(flt.op)
        if sql_op is None:
            return []
        where.append(f"value_num IS NOT NULL AND value_num {sql_op} ?")
        params.append(float(flt.value_num))

    sql = (
        f"SELECT {_FACT_COLS} FROM memory_facts "
        + (f"WHERE {' AND '.join(where)} " if where else "")
        + "ORDER BY is_latest ASC, created_at DESC LIMIT ?"
    )
    params.append(int(k))

    own = False
    if con is None:
        con = get_connection()
        own = True
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        if own:
            con.close()

    return [_row_to_hit(r, score=1.0, raw_score=1.0, surface="numeric") for r in rows]


def search_numeric(
    flt: NumericFilter,
    k: int = 10,
    *,
    con: Optional[sqlite3.Connection] = None,
) -> List[ExactHit]:
    """Typed-column WHERE search over `memory_facts`.

    Returns rows matching all supplied constraints (case-insensitive on
    text fields). `score` is `1.0` when all supplied constraints match
    exactly (deterministic by design — fusion handles tie-breaking).
    """
    if flt is None or flt.is_empty() or k <= 0:
        return []

    where: list[str] = ["is_latest = 1"]  # default-latest semantics (Sprint 5 lineage-safe)
    params: list = []
    if flt.entity is not None:
        where.append("LOWER(entity) = LOWER(?)")
        params.append(flt.entity.strip())
    if flt.attribute is not None:
        where.append("LOWER(attribute) = LOWER(?)")
        params.append(flt.attribute.strip())
    if flt.period is not None:
        where.append("LOWER(period) = LOWER(?)")
        params.append(flt.period.strip())
    if flt.unit is not None:
        where.append("LOWER(unit) = LOWER(?)")
        params.append(flt.unit.strip())
    if flt.op is not None and flt.value_num is not None:
        sql_op = _OP_TO_SQL.get(flt.op)
        if sql_op is None:
            return []  # unknown op → reject defensively
        where.append(f"value_num IS NOT NULL AND value_num {sql_op} ?")
        params.append(float(flt.value_num))

    sql = (
        f"SELECT {_FACT_COLS} FROM memory_facts "
        f"WHERE {' AND '.join(where)} "
        # Newest first within the matched set so caller sees most recent.
        f"ORDER BY created_at DESC LIMIT ?"
    )
    params.append(int(k))

    own = False
    if con is None:
        con = get_connection()
        own = True
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        if own:
            con.close()

    hits = [_row_to_hit(r, score=1.0, raw_score=1.0, surface="numeric") for r in rows]
    if get_settings().shail_retrieval_debug:
        logger.info(
            "exact_index.search_numeric flt=%s hits=%d", flt, len(hits)
        )
    return hits


# ── PR3: numeric filter parser ──────────────────────────────────────────────


# Number with optional currency / multiplier / percent. Examples:
#   $1.5M, $50B, 81e9, 4.2%, 62, 1,200, $4.2k
_NUM_RE = re.compile(
    r"""
    (?P<currency>[\$€£])?
    (?P<num>\d+(?:[.,]\d+)?)
    (?P<mult>[KkMmBbTt])?
    (?P<percent>%)?
    """,
    re.VERBOSE,
)
_OP_RE = re.compile(r"(>=|<=|>|<|=)")
_PERIOD_RE = re.compile(
    r"\b("
    r"(?:FY|Q[1-4]|H[12])\s*\d{2,4}"          # FY24, Q3 2023, H1 2024
    r"|\d{4}-Q[1-4]"                            # 2023-Q3
    r"|\d{4}-\d{2}"                             # 2024-01
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{2,4}"
    r"|\b(?:19|20)\d{2}\b"                      # plain year (1900-2099)
    r")",
    re.IGNORECASE,
)
_MULT = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def _parse_number(match: "re.Match[str]") -> Optional[tuple[float, Optional[str]]]:
    """Return (value_num, unit_hint) from a regex match. None if invalid."""
    raw = match.group("num").replace(",", "")
    try:
        n = float(raw)
    except ValueError:
        return None
    mult = match.group("mult")
    if mult:
        n *= _MULT[mult.lower()]
    unit: Optional[str] = None
    if match.group("currency"):
        unit = {"$": "USD", "€": "EUR", "£": "GBP"}[match.group("currency")]
    elif match.group("percent"):
        unit = "%"
    return n, unit


def parse_numeric_filter(query: str) -> Optional[NumericFilter]:
    """Best-effort regex extraction of structured filter constraints.

    Returns None when no numeric/comparison signal is present (caller
    falls back to FTS path). Conservative: only emits fields it is
    confident about. Period detection runs even without comparison op.
    """
    if not query:
        return None
    text = query.strip()

    period_match = _PERIOD_RE.search(text)
    period = period_match.group(1) if period_match else None

    op_match = _OP_RE.search(text)
    value_num: Optional[float] = None
    unit: Optional[str] = None
    op: Optional[str] = None
    if op_match:
        op = op_match.group(1)
        # First number AFTER the operator. Exclude tokens that fall inside the
        # period span — otherwise "> stuff in 2023" would mis-bind 2023 as the
        # comparison value.
        tail_start = op_match.end()
        period_span = period_match.span() if period_match else None
        n_iter = _NUM_RE.finditer(text, tail_start)
        for n_match in n_iter:
            if not n_match.group("num"):
                continue
            ns, ne = n_match.span()
            if period_span and ns >= period_span[0] and ne <= period_span[1]:
                continue  # this number is the period — skip
            parsed = _parse_number(n_match)
            if parsed is not None:
                value_num, unit = parsed
                break

    flt = NumericFilter(
        entity=None,        # entity disambiguation deferred to Sprint 3 intent classifier
        attribute=None,
        period=period,
        op=op if value_num is not None else None,
        value_num=value_num,
        unit=unit,
    )
    return None if flt.is_empty() else flt
