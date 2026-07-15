"""Deterministic reasoning over local semantic atoms.

This layer is derived state. It groups already-extracted facts, detects
conflicts, and records a preferred claim when deterministic evidence is strong
enough. It never stores full local file content.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from apps.shail.settings import get_settings
from shail.memory import path_index

CONF_EXTRACTED = "EXTRACTED"
CONF_INFERRED = "INFERRED"
CONF_AMBIGUOUS = "AMBIGUOUS"

_CURRENT_ATTRS = {
    "arr", "budget", "churn", "conversion", "cost", "date", "decision",
    "growth", "margin", "mrr", "price", "pricing", "profit", "retention",
    "revenue", "runway", "sales", "status", "valuation",
}
_VERSION_RE = re.compile(
    r"(?i)(?:^|[_\-\s.])(?:v(?:ersion)?\s*\d+|final|draft|copy|\d{4}[-_.]\d{1,2}[-_.]\d{1,2})(?:$|[_\-\s.])"
)


def _db_path() -> str:
    return getattr(get_settings(), "sqlite_path", "") or get_settings().path_index_db


def _conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = Path(db_path or _db_path()).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    ensure_schema(con)
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS local_semantic_fact_groups (
            group_id TEXT PRIMARY KEY,
            entity_norm TEXT NOT NULL,
            attribute_norm TEXT NOT NULL,
            period_norm TEXT NOT NULL,
            unit_norm TEXT NOT NULL,
            value_type TEXT NOT NULL,
            label TEXT NOT NULL,
            claim_count INTEGER NOT NULL DEFAULT 0,
            distinct_value_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            preferred_claim_id TEXT,
            confidence TEXT NOT NULL,
            reason TEXT,
            warnings_json TEXT NOT NULL DEFAULT '[]',
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS local_semantic_fact_claims (
            claim_id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            fact_id TEXT NOT NULL,
            file_id TEXT NOT NULL,
            path TEXT NOT NULL,
            entity TEXT,
            attribute TEXT,
            value TEXT,
            value_num REAL,
            unit TEXT,
            period TEXT,
            value_norm TEXT NOT NULL,
            confidence TEXT NOT NULL,
            extractor TEXT NOT NULL,
            source_span TEXT,
            content_hash TEXT,
            file_mtime REAL,
            is_latest_candidate INTEGER NOT NULL DEFAULT 0,
            is_duplicate_candidate INTEGER NOT NULL DEFAULT 0,
            support_count INTEGER NOT NULL DEFAULT 1,
            score REAL NOT NULL DEFAULT 0,
            reason TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS local_semantic_conflicts (
            conflict_id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            status TEXT NOT NULL,
            preferred_claim_id TEXT,
            competing_claim_ids_json TEXT NOT NULL DEFAULT '[]',
            reason TEXT,
            warnings_json TEXT NOT NULL DEFAULT '[]',
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS local_semantic_resolutions (
            group_id TEXT PRIMARY KEY,
            preferred_claim_id TEXT,
            confidence TEXT NOT NULL,
            reason TEXT,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_local_reason_groups_label ON local_semantic_fact_groups(label);
        CREATE INDEX IF NOT EXISTS idx_local_reason_claims_group ON local_semantic_fact_claims(group_id);
        CREATE INDEX IF NOT EXISTS idx_local_reason_claims_file ON local_semantic_fact_claims(file_id);
        CREATE INDEX IF NOT EXISTS idx_local_reason_claims_value ON local_semantic_fact_claims(value_norm);
        CREATE INDEX IF NOT EXISTS idx_local_reason_conflicts_group ON local_semantic_conflicts(group_id);
        """
    )
    con.commit()


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return prefix + ":" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _clean(value: Any, *, limit: int = 240) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _norm(value: Any) -> str:
    text = _clean(value).casefold()
    text = re.sub(r"[^a-z0-9%$€£₹.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _value_type(value_num: Any, unit: Any, value: Any) -> str:
    if value_num is not None:
        if unit == "%":
            return "percent"
        if unit:
            return "metric"
        return "number"
    if re.search(r"(?i)\b(?:yes|no|true|false|approved|rejected|pending|done)\b", str(value or "")):
        return "status"
    return "text"


def _value_norm(row: dict[str, Any]) -> str:
    value_num = row.get("value_num")
    unit = row.get("unit") or ""
    if value_num is not None:
        try:
            return f"{float(value_num):.6g}:{unit}"
        except Exception:
            pass
    return _norm(row.get("value"))


def _group_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        _norm(row.get("entity")),
        _norm(row.get("attribute")),
        _norm(row.get("period")),
        _norm(row.get("unit")),
        _value_type(row.get("value_num"), row.get("unit"), row.get("value")),
    )


def _group_label(row: dict[str, Any]) -> str:
    parts = [row.get("entity"), row.get("attribute"), row.get("period"), row.get("unit")]
    label = " ".join(_clean(p, limit=80) for p in parts if p)
    return label or "Document fact"


def _version_key(path: str) -> str:
    p = Path(path or "")
    stem = _VERSION_RE.sub("_", p.stem)
    stem = re.sub(r"[_\-\s.]+", "_", stem).strip("_").lower() or p.stem.lower()
    return f"{p.parent}:{stem}:{p.suffix.lower()}"


def _version_rank(path: str, mtime: float) -> tuple[int, int, float]:
    name = Path(path or "").name
    nums = [int(x) for x in re.findall(r"(?i)(?:v|version)[_\-\s.]*(\d+)", name)]
    version = max(nums) if nums else 0
    final_bonus = 1 if re.search(r"(?i)\bfinal\b", name) else 0
    return final_bonus, version, float(mtime or 0.0)


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    try:
        meta = json.loads(row.get("metadata_json") or "{}")
        return meta if isinstance(meta, dict) else {}
    except Exception:
        return {}


def _extractor(meta: dict[str, Any]) -> str:
    value = str(meta.get("extractor") or "deterministic").strip().lower()
    return value or "deterministic"


def _is_visible(path: str) -> bool:
    if not path:
        return False
    db = get_settings().path_index_db
    if path_index.is_denied(db, path):
        return False
    row = path_index.get_by_path(db, path)
    if not row:
        return False
    return not bool(row.get("deleted_at"))


def _path_rows_for_facts(fact_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    db = get_settings().path_index_db
    out: dict[str, dict[str, Any]] = {}
    for row in fact_rows:
        path = row.get("path") or ""
        if not path or path in out:
            continue
        try:
            idx_row = path_index.get_by_path(db, path)
            out[path] = dict(idx_row) if idx_row else {}
        except Exception:
            out[path] = {}
    return out


def _load_visible_fact_rows(con: sqlite3.Connection, *, limit: int) -> list[dict[str, Any]]:
    rows = con.execute(
        """SELECT * FROM local_file_facts
           WHERE COALESCE(entity,'') != '' OR COALESCE(attribute,'') != '' OR COALESCE(value,'') != ''
           ORDER BY entity, attribute, period, path LIMIT ?""",
        (limit,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        if _is_visible(d.get("path") or ""):
            out.append(d)
    return out


def _score_claim(
    row: dict[str, Any],
    *,
    path_row: dict[str, Any],
    support_count: int,
    is_latest: bool,
    is_duplicate: bool,
) -> tuple[float, str]:
    meta = _metadata(row)
    extractor = _extractor(meta)
    confidence = row.get("confidence") or CONF_AMBIGUOUS
    score = {CONF_EXTRACTED: 34.0, CONF_INFERRED: 22.0, CONF_AMBIGUOUS: 8.0}.get(confidence, 12.0)
    reasons: list[str] = [f"{confidence.lower()} semantic atom"]
    if extractor == "ollama" and confidence != CONF_AMBIGUOUS:
        score += 4
        reasons.append("Ollama enriched")
    elif extractor == "ollama":
        score -= 4
        reasons.append("ambiguous Ollama atom")
    else:
        score += 2
        reasons.append("rule extracted")
    if is_latest:
        score += 12
        reasons.append("latest version candidate")
    if is_duplicate:
        score -= 10
        reasons.append("duplicate copy")
    if support_count > 1:
        score += min(14, support_count * 4)
        reasons.append(f"supported by {support_count} matching claims")
    attr = _norm(row.get("attribute"))
    if attr in _CURRENT_ATTRS and path_row.get("mtime"):
        score += min(6.0, max(0.0, float(path_row.get("mtime") or 0.0)) / 10_000_000_000)
        reasons.append("newer modified file")
    return round(score, 3), "; ".join(reasons)


def _status_for_group(distinct_values: int, preferred_claim: Optional[dict[str, Any]], confidence: str) -> str:
    if distinct_values <= 1:
        return "resolved" if preferred_claim else "unresolved"
    if preferred_claim and confidence in {"high", "medium"}:
        return "conflict_resolved"
    return "conflict_unresolved"


def _resolution_confidence(top: Optional[dict[str, Any]], second: Optional[dict[str, Any]], distinct_values: int) -> str:
    if not top:
        return "unresolved"
    if top.get("confidence") == CONF_AMBIGUOUS:
        return "low" if distinct_values <= 1 else "unresolved"
    score = float(top.get("score") or 0.0)
    runner = float(second.get("score") or 0.0) if second else 0.0
    margin = score - runner
    if distinct_values <= 1:
        return "high" if score >= 48 else "medium" if score >= 30 else "low"
    if margin >= 12 and score >= 42:
        return "high"
    if margin >= 8 and score >= 34:
        return "medium"
    return "unresolved"


def build_reasoning(
    *,
    semantics_db: Optional[str] = None,
    limit: int = 5000,
    force: bool = False,
) -> dict[str, Any]:
    del force  # Reasoning is fully derived and always safe to rebuild.
    now = time.time()
    with _conn(semantics_db) as con:
        rows = _load_visible_fact_rows(con, limit=limit)
        con.execute("DELETE FROM local_semantic_fact_groups")
        con.execute("DELETE FROM local_semantic_fact_claims")
        con.execute("DELETE FROM local_semantic_conflicts")
        con.execute("DELETE FROM local_semantic_resolutions")
        if not rows:
            con.commit()
            return {
                "status": "complete",
                "groups": 0,
                "claims": 0,
                "conflicts": 0,
                "resolved": 0,
                "unresolved": 0,
            }

        path_rows = _path_rows_for_facts(rows)
        by_version: dict[str, list[dict[str, Any]]] = {}
        by_hash: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            path_row = path_rows.get(row.get("path") or "") or {}
            by_version.setdefault(_version_key(row.get("path") or ""), []).append(row)
            content_hash = path_row.get("content_hash")
            if content_hash:
                by_hash.setdefault(str(content_hash), []).append(row)

        latest_paths: set[str] = set()
        for group in by_version.values():
            latest = max(
                group,
                key=lambda r: _version_rank(r.get("path") or "", float((path_rows.get(r.get("path") or "") or {}).get("mtime") or 0.0)),
            )
            latest_paths.add(latest.get("path") or "")
        duplicate_paths: set[str] = set()
        for hash_group in by_hash.values():
            if len({r.get("path") for r in hash_group}) < 2:
                continue
            ordered = sorted(
                hash_group,
                key=lambda r: _version_rank(r.get("path") or "", float((path_rows.get(r.get("path") or "") or {}).get("mtime") or 0.0)),
                reverse=True,
            )
            for row in ordered[1:]:
                duplicate_paths.add(row.get("path") or "")

        grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(_group_key(row), []).append(row)

        group_count = claim_count = conflict_count = resolved_count = unresolved_count = 0
        for key, fact_rows in grouped.items():
            entity_norm, attribute_norm, period_norm, unit_norm, value_type = key
            sample = fact_rows[0]
            group_id = _stable_id("fact_group", *key)
            value_support: dict[str, int] = {}
            for row in fact_rows:
                value_support[_value_norm(row)] = value_support.get(_value_norm(row), 0) + 1

            claims: list[dict[str, Any]] = []
            for row in fact_rows:
                value_norm = _value_norm(row)
                path = row.get("path") or ""
                path_row = path_rows.get(path) or {}
                meta = _metadata(row)
                is_latest = path in latest_paths
                is_duplicate = path in duplicate_paths
                score, reason = _score_claim(
                    row,
                    path_row=path_row,
                    support_count=value_support.get(value_norm, 1),
                    is_latest=is_latest,
                    is_duplicate=is_duplicate,
                )
                claim = {
                    "claim_id": _stable_id("claim", group_id, row.get("id"), value_norm),
                    "group_id": group_id,
                    "fact_id": row.get("id"),
                    "file_id": row.get("file_id"),
                    "path": path,
                    "entity": row.get("entity"),
                    "attribute": row.get("attribute"),
                    "value": row.get("value"),
                    "value_num": row.get("value_num"),
                    "unit": row.get("unit"),
                    "period": row.get("period"),
                    "value_norm": value_norm,
                    "confidence": row.get("confidence") or CONF_AMBIGUOUS,
                    "extractor": _extractor(meta),
                    "source_span": row.get("source_span"),
                    "content_hash": path_row.get("content_hash"),
                    "file_mtime": path_row.get("mtime"),
                    "is_latest_candidate": bool(is_latest),
                    "is_duplicate_candidate": bool(is_duplicate),
                    "support_count": value_support.get(value_norm, 1),
                    "score": score,
                    "reason": reason,
                    "metadata": {
                        "source": "approved_local_file",
                        "extractor_metadata": meta,
                        "content_hash": path_row.get("content_hash"),
                    },
                }
                claims.append(claim)

            claims.sort(key=lambda c: (float(c.get("score") or 0.0), str(c.get("value_norm") or "")), reverse=True)
            distinct_values = len({c["value_norm"] for c in claims if c["value_norm"]})
            top = claims[0] if claims else None
            second = next((c for c in claims[1:] if c["value_norm"] != (top or {}).get("value_norm")), None)
            resolution_confidence = _resolution_confidence(top, second, distinct_values)
            preferred = top if resolution_confidence != "unresolved" else None
            status = _status_for_group(distinct_values, preferred, resolution_confidence)
            warnings: list[str] = []
            if distinct_values > 1:
                warnings.append("Conflicting values were found for this fact group.")
            if resolution_confidence == "unresolved":
                warnings.append("Top claims are too close or too weak to choose safely.")
            if any(c["confidence"] == CONF_AMBIGUOUS for c in claims):
                warnings.append("Some claims are ambiguous.")
            reason = _reason_summary(preferred, second, distinct_values)

            con.execute(
                """INSERT INTO local_semantic_fact_groups
                   (group_id, entity_norm, attribute_norm, period_norm, unit_norm, value_type,
                    label, claim_count, distinct_value_count, status, preferred_claim_id,
                    confidence, reason, warnings_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    group_id, entity_norm, attribute_norm, period_norm, unit_norm, value_type,
                    _group_label(sample), len(claims), distinct_values, status,
                    preferred.get("claim_id") if preferred else None, resolution_confidence,
                    reason, json.dumps(warnings), now,
                ),
            )
            for claim in claims:
                con.execute(
                    """INSERT INTO local_semantic_fact_claims
                       (claim_id, group_id, fact_id, file_id, path, entity, attribute, value,
                        value_num, unit, period, value_norm, confidence, extractor, source_span,
                        content_hash, file_mtime, is_latest_candidate, is_duplicate_candidate,
                        support_count, score, reason, metadata_json, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        claim["claim_id"], claim["group_id"], claim["fact_id"], claim["file_id"],
                        claim["path"], claim["entity"], claim["attribute"], claim["value"],
                        claim["value_num"], claim["unit"], claim["period"], claim["value_norm"],
                        claim["confidence"], claim["extractor"], claim["source_span"],
                        claim["content_hash"], claim["file_mtime"],
                        1 if claim["is_latest_candidate"] else 0,
                        1 if claim["is_duplicate_candidate"] else 0,
                        claim["support_count"], claim["score"], claim["reason"],
                        json.dumps(claim["metadata"]), now,
                    ),
                )
                claim_count += 1
            if distinct_values > 1:
                conflict_count += 1
                con.execute(
                    """INSERT INTO local_semantic_conflicts
                       (conflict_id, group_id, status, preferred_claim_id,
                        competing_claim_ids_json, reason, warnings_json, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        _stable_id("conflict", group_id),
                        group_id,
                        "resolved" if preferred else "unresolved",
                        preferred.get("claim_id") if preferred else None,
                        json.dumps([c["claim_id"] for c in claims if not preferred or c["claim_id"] != preferred["claim_id"]]),
                        reason,
                        json.dumps(warnings),
                        now,
                    ),
                )
            if preferred:
                resolved_count += 1
                con.execute(
                    """INSERT INTO local_semantic_resolutions
                       (group_id, preferred_claim_id, confidence, reason, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (group_id, preferred["claim_id"], resolution_confidence, reason, now),
                )
            else:
                unresolved_count += 1
            group_count += 1
        con.commit()

    return {
        "status": "complete",
        "groups": group_count,
        "claims": claim_count,
        "conflicts": conflict_count,
        "resolved": resolved_count,
        "unresolved": unresolved_count,
    }


def _reason_summary(preferred: Optional[dict[str, Any]], second: Optional[dict[str, Any]], distinct_values: int) -> str:
    if not preferred:
        return "No preferred claim selected because the evidence was weak or too close."
    bits = [f"Preferred '{preferred.get('value')}'"]
    if preferred.get("is_latest_candidate"):
        bits.append("from the latest-looking file")
    if preferred.get("support_count", 1) > 1:
        bits.append(f"with {preferred.get('support_count')} matching claims")
    if preferred.get("confidence"):
        bits.append(f"at {preferred.get('confidence')} extraction confidence")
    if distinct_values > 1 and second:
        bits.append(f"over competing value '{second.get('value')}'")
    return "; ".join(bits) + "."


def _json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _claim_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "claim_id": row["claim_id"],
        "group_id": row["group_id"],
        "fact_id": row["fact_id"],
        "file_id": row["file_id"],
        "path": row["path"],
        "entity": row["entity"],
        "attribute": row["attribute"],
        "value": row["value"],
        "value_num": row["value_num"],
        "unit": row["unit"],
        "period": row["period"],
        "value_norm": row["value_norm"],
        "confidence": row["confidence"],
        "extractor": row["extractor"],
        "source_span": row["source_span"],
        "content_hash": row["content_hash"],
        "file_mtime": row["file_mtime"],
        "is_latest_candidate": bool(row["is_latest_candidate"]),
        "is_duplicate_candidate": bool(row["is_duplicate_candidate"]),
        "support_count": row["support_count"],
        "score": row["score"],
        "reason": row["reason"],
        "metadata": _json(row["metadata_json"], {}),
    }


def _group_row(row: sqlite3.Row, claims: list[dict[str, Any]]) -> dict[str, Any]:
    preferred_id = row["preferred_claim_id"]
    return {
        "group_id": row["group_id"],
        "label": row["label"],
        "entity_norm": row["entity_norm"],
        "attribute_norm": row["attribute_norm"],
        "period_norm": row["period_norm"],
        "unit_norm": row["unit_norm"],
        "value_type": row["value_type"],
        "claim_count": row["claim_count"],
        "distinct_value_count": row["distinct_value_count"],
        "status": row["status"],
        "preferred_claim_id": preferred_id,
        "preferred_claim": next((c for c in claims if c["claim_id"] == preferred_id), None),
        "competing_claims": [c for c in claims if c["claim_id"] != preferred_id],
        "confidence": row["confidence"],
        "reason": row["reason"],
        "warnings": _json(row["warnings_json"], []),
        "updated_at": row["updated_at"],
    }


def get_group(group_id: str, *, semantics_db: Optional[str] = None) -> Optional[dict[str, Any]]:
    with _conn(semantics_db) as con:
        group = con.execute("SELECT * FROM local_semantic_fact_groups WHERE group_id = ?", (group_id,)).fetchone()
        if not group:
            return None
        claims = [
            _claim_row(r)
            for r in con.execute(
                "SELECT * FROM local_semantic_fact_claims WHERE group_id = ? ORDER BY score DESC",
                (group_id,),
            ).fetchall()
        ]
    return _group_row(group, claims)


def status(*, semantics_db: Optional[str] = None) -> dict[str, Any]:
    with _conn(semantics_db) as con:
        counts = con.execute(
            """SELECT
                 COUNT(*) AS groups_total,
                 SUM(claim_count) AS claims_total,
                 SUM(CASE WHEN status IN ('conflict_resolved','conflict_unresolved') THEN 1 ELSE 0 END) AS conflicts_total,
                 SUM(CASE WHEN preferred_claim_id IS NOT NULL THEN 1 ELSE 0 END) AS resolved_total,
                 SUM(CASE WHEN preferred_claim_id IS NULL THEN 1 ELSE 0 END) AS unresolved_total,
                 MAX(updated_at) AS last_built_at
               FROM local_semantic_fact_groups"""
        ).fetchone()
    return {
        "groups": int(counts["groups_total"] or 0),
        "claims": int(counts["claims_total"] or 0),
        "conflicts": int(counts["conflicts_total"] or 0),
        "resolved": int(counts["resolved_total"] or 0),
        "unresolved": int(counts["unresolved_total"] or 0),
        "last_built_at": counts["last_built_at"],
    }


def search(query: str = "", *, semantics_db: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    q = _norm(query)
    with _conn(semantics_db) as con:
        if q:
            like = f"%{q}%"
            groups = con.execute(
                """SELECT * FROM local_semantic_fact_groups
                   WHERE LOWER(label) LIKE ? OR entity_norm LIKE ? OR attribute_norm LIKE ?
                   ORDER BY confidence, label LIMIT ?""",
                (like, like, like, limit),
            ).fetchall()
        else:
            groups = con.execute(
                "SELECT * FROM local_semantic_fact_groups ORDER BY updated_at DESC, label LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for group in groups:
            claims = [
                _claim_row(r)
                for r in con.execute(
                    "SELECT * FROM local_semantic_fact_claims WHERE group_id = ? ORDER BY score DESC LIMIT 12",
                    (group["group_id"],),
                ).fetchall()
            ]
            out.append(_group_row(group, claims))
    return {"items": out, **status(semantics_db=semantics_db)}


def conflicts(*, semantics_db: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    with _conn(semantics_db) as con:
        rows = con.execute(
            "SELECT * FROM local_semantic_conflicts ORDER BY status DESC, updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for conflict in rows:
            group = get_group(conflict["group_id"], semantics_db=semantics_db)
            if not group:
                continue
            group["conflict_id"] = conflict["conflict_id"]
            group["conflict_status"] = conflict["status"]
            group["conflict_reason"] = conflict["reason"]
            group["conflict_warnings"] = _json(conflict["warnings_json"], [])
            out.append(group)
    return {"items": out, **status(semantics_db=semantics_db)}


def reasoning_for_files(
    file_ids: list[str],
    *,
    semantics_db: Optional[str] = None,
    limit_per_file: int = 5,
) -> dict[str, Any]:
    if not file_ids:
        return {"resolutions": [], "conflicts": [], "warnings": []}
    placeholders = ",".join("?" for _ in file_ids)
    with _conn(semantics_db) as con:
        claim_rows = con.execute(
            f"""SELECT DISTINCT group_id FROM local_semantic_fact_claims
                WHERE file_id IN ({placeholders})
                LIMIT ?""",
            (*file_ids, max(1, len(file_ids) * limit_per_file)),
        ).fetchall()
    groups = [get_group(r["group_id"], semantics_db=semantics_db) for r in claim_rows]
    groups = [g for g in groups if g]
    resolutions = [g for g in groups if g.get("preferred_claim")]
    conflicts_out = [g for g in groups if g.get("distinct_value_count", 0) > 1]
    warnings = []
    for group in conflicts_out:
        if group.get("confidence") == "unresolved":
            warnings.append(f"Unresolved conflict for {group.get('label')}.")
        else:
            warnings.append(f"Competing claims found for {group.get('label')}; preferred source was selected deterministically.")
    return {
        "resolutions": resolutions[: max(1, len(file_ids) * limit_per_file)],
        "conflicts": conflicts_out[: max(1, len(file_ids) * limit_per_file)],
        "warnings": warnings,
    }
