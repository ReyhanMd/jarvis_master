"""USSF-style intelligence packets over approved local-file evidence.

USSF in Phase 9 means Unified Source of Semantic Facts. This module builds a
derived packet from evidence, grounded answers, and semantic reasoning. It does
not extract new content or store full local-file text.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from apps.shail.evidence_bundle import EvidenceBundle, build_evidence_bundle
from apps.shail.grounded_answer import GroundedAnswer, build_grounded_answer
from apps.shail.settings import get_settings
from shail.memory import path_index


CANONICAL_STATUSES = {"accepted", "conflicted", "unresolved", "stale", "weak", "missing"}


@dataclass
class IntelligencePacket:
    packet_id: str
    query: str
    answer: str
    confidence: str
    canonical_facts: list[dict[str, Any]] = field(default_factory=list)
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)
    recommended_next_actions: list[str] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    source_map: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence_bundle_id: str = ""
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        CREATE TABLE IF NOT EXISTS local_intelligence_packets (
            packet_id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            confidence TEXT NOT NULL,
            answer TEXT NOT NULL,
            evidence_bundle_id TEXT,
            packet_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_local_intel_packets_created ON local_intelligence_packets(created_at);
        CREATE INDEX IF NOT EXISTS idx_local_intel_packets_query ON local_intelligence_packets(query);
        """
    )
    con.commit()


def build_intelligence_packet(
    query: str,
    *,
    user_id: Optional[str] = None,
    scope: Optional[str] = None,
    k: int = 12,
    include_graph: bool = True,
    include_semantics: bool = True,
    include_reasoning: bool = True,
    include_answer: bool = True,
    store: bool = True,
) -> IntelligencePacket:
    del include_semantics, include_reasoning  # current evidence bundle already joins these when available.
    settings = get_settings()
    bundle = build_evidence_bundle(
        query,
        user_id=user_id,
        k=k,
        include_graph=include_graph,
        max_direct_files=min(k, settings.shail_local_files_k),
        max_graph_neighbors=3,
        max_total_evidence=k,
        max_snippet_chars=settings.shail_local_files_snippet_chars,
        read_cap_bytes=settings.shail_local_files_read_cap_bytes,
    )
    grounded = build_grounded_answer(
        query,
        user_id=user_id,
        k=k,
        include_graph=include_graph,
        evidence_bundle=bundle,
    )
    canonical_facts = canonical_facts_from_grounded(grounded, bundle)
    supporting_evidence = _supporting_evidence(grounded, bundle)
    conflicts = _conflicts(grounded)
    gaps = _gaps(query, grounded, bundle, canonical_facts)
    source_map = _source_map(bundle, grounded)
    timeline = _timeline(canonical_facts, source_map)
    warnings = _dedupe([*grounded.warnings, *bundle.warnings, *bundle.semantic_warnings, *bundle.reasoning_warnings])
    recommended = _recommended_actions(grounded, conflicts, gaps, warnings)
    answer = grounded.answer if include_answer else _summary_answer(grounded, canonical_facts, gaps)

    if getattr(settings, "shail_local_intelligence_llm", False):
        synthesized, warning = _try_ollama_synthesis(answer, canonical_facts, conflicts, gaps)
        if synthesized:
            answer = synthesized
        if warning:
            warnings.append(warning)

    packet = IntelligencePacket(
        packet_id=_packet_id(query, grounded.evidence_bundle_id, canonical_facts, time.time()),
        query=query,
        answer=answer,
        confidence=grounded.confidence,
        canonical_facts=canonical_facts,
        supporting_evidence=supporting_evidence,
        conflicts=conflicts,
        gaps=gaps,
        follow_up_questions=grounded.follow_up_questions,
        recommended_next_actions=recommended,
        timeline=timeline,
        source_map=source_map,
        warnings=_dedupe(warnings),
        evidence_bundle_id=grounded.evidence_bundle_id,
        created_at=time.time(),
        metadata={
            "scope": scope,
            "include_graph": include_graph,
            "include_answer": include_answer,
            "llm_synthesis_enabled": bool(getattr(settings, "shail_local_intelligence_llm", False)),
            "source": "approved_local_files",
        },
    )
    if store:
        store_packet(packet)
    return packet


def canonical_facts_from_grounded(grounded: GroundedAnswer, bundle: EvidenceBundle) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    conflict_group_ids = {str(group.get("group_id") or "") for group in grounded.semantic_conflicts}
    for group in grounded.semantic_resolutions:
        fact = _canonical_from_group(group)
        if fact["fact_id"] in conflict_group_ids or fact.get("conflict_group_id") in conflict_group_ids:
            fact["status"] = "conflicted" if fact["confidence"] in {"high", "medium"} else "unresolved"
        facts.append(fact)

    if facts:
        return _dedupe_facts(facts)

    weak_facts: list[dict[str, Any]] = []
    for fact in bundle.semantic_facts[:12]:
        fid = str(fact.get("id") or _stable_id("weak_fact", fact.get("file_id"), fact.get("entity"), fact.get("attribute"), fact.get("value")))
        weak_facts.append({
            "fact_id": fid,
            "entity": fact.get("entity"),
            "attribute": fact.get("attribute"),
            "value": fact.get("value") or fact.get("value_num"),
            "period": fact.get("period"),
            "confidence": "low",
            "status": "weak",
            "preferred_claim": fact,
            "competing_claims": [],
            "source_files": _source_files_for_claims([fact]),
            "why_this_is_preferred": "No resolved semantic fact was available; this is a raw extracted fact.",
            "warnings": ["Weak fact: not resolved by semantic reasoning."],
        })
    return _dedupe_facts(weak_facts)


def search_canonical_facts(query: str, *, limit: int = 50) -> dict[str, Any]:
    from apps.shail import local_semantic_reasoning

    result = local_semantic_reasoning.search(query, limit=limit)
    groups = result.get("items") or []
    facts = [_canonical_from_group(group) for group in groups]
    return {
        "query": query,
        "items": facts,
        "total": len(facts),
        "status": status(),
    }


def store_packet(packet: IntelligencePacket, *, db_path: Optional[str] = None) -> None:
    with _conn(db_path) as con:
        con.execute(
            """
            INSERT OR REPLACE INTO local_intelligence_packets
            (packet_id, query, confidence, answer, evidence_bundle_id, packet_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                packet.packet_id,
                packet.query,
                packet.confidence,
                packet.answer,
                packet.evidence_bundle_id,
                json.dumps(packet.to_dict(), ensure_ascii=False, sort_keys=True),
                packet.created_at,
            ),
        )
        con.commit()


def get_packet(packet_id: str, *, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    with _conn(db_path) as con:
        row = con.execute(
            "SELECT packet_json FROM local_intelligence_packets WHERE packet_id = ?",
            (packet_id,),
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["packet_json"] or "{}")
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def status(*, db_path: Optional[str] = None) -> dict[str, Any]:
    with _conn(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS packets,
                   MAX(created_at) AS latest_packet_at,
                   SUM(CASE WHEN confidence = 'high' THEN 1 ELSE 0 END) AS high,
                   SUM(CASE WHEN confidence = 'medium' THEN 1 ELSE 0 END) AS medium,
                   SUM(CASE WHEN confidence = 'low' THEN 1 ELSE 0 END) AS low,
                   SUM(CASE WHEN confidence = 'insufficient' THEN 1 ELSE 0 END) AS insufficient
            FROM local_intelligence_packets
            """
        ).fetchone()
    return {
        "packets": int(row["packets"] or 0),
        "latest_packet_at": row["latest_packet_at"],
        "confidence": {
            "high": int(row["high"] or 0),
            "medium": int(row["medium"] or 0),
            "low": int(row["low"] or 0),
            "insufficient": int(row["insufficient"] or 0),
        },
        "llm_synthesis_enabled": bool(getattr(get_settings(), "shail_local_intelligence_llm", False)),
        "model": getattr(get_settings(), "shail_local_intelligence_model", get_settings().ollama_chat_model),
    }


def _canonical_from_group(group: dict[str, Any]) -> dict[str, Any]:
    preferred = group.get("preferred_claim") or {}
    competing = group.get("competing_claims") or []
    group_id = str(group.get("group_id") or group.get("id") or _stable_id("fact_group", group.get("label")))
    confidence = str(group.get("confidence") or "low").lower()
    status_value = _canonical_status(group)
    return {
        "fact_id": group_id,
        "entity": preferred.get("entity") or group.get("entity") or group.get("entity_norm"),
        "attribute": preferred.get("attribute") or group.get("attribute") or group.get("attribute_norm"),
        "value": preferred.get("value") or preferred.get("value_num") or preferred.get("value_norm"),
        "period": preferred.get("period") or group.get("period") or group.get("period_norm"),
        "confidence": confidence if confidence in {"high", "medium", "low"} else "low",
        "status": status_value,
        "preferred_claim": preferred,
        "competing_claims": competing,
        "source_files": _source_files_for_claims([preferred, *competing]),
        "why_this_is_preferred": group.get("reason") or "Selected by deterministic semantic reasoning.",
        "warnings": group.get("warnings") or [],
        "conflict_group_id": group_id if status_value in {"conflicted", "unresolved"} else None,
    }


def _canonical_status(group: dict[str, Any]) -> str:
    status_value = str(group.get("status") or "").lower()
    confidence = str(group.get("confidence") or "").lower()
    if status_value in {"unresolved"} or confidence in {"unresolved"}:
        return "unresolved"
    if status_value in {"conflict", "conflicted"} or len(group.get("competing_claims") or []) > 0:
        return "conflicted"
    if confidence == "low":
        return "weak"
    if not group.get("preferred_claim"):
        return "missing"
    return "accepted"


def _supporting_evidence(grounded: GroundedAnswer, bundle: EvidenceBundle) -> list[dict[str, Any]]:
    selected_by_id = {item.id: item for item in bundle.selected_files}
    evidence = []
    for item in grounded.evidence_summary:
        fid = str(item.get("file_id") or "")
        bundle_item = selected_by_id.get(fid)
        evidence.append({
            **item,
            "snippet": bundle_item.snippet if bundle_item else "",
            "warning_type": next((c.get("warning_type") for c in grounded.citations if c.get("id") == fid), None),
        })
    return evidence


def _conflicts(grounded: GroundedAnswer) -> list[dict[str, Any]]:
    out = []
    for group in grounded.semantic_conflicts:
        out.append({
            "group_id": group.get("group_id") or group.get("id"),
            "label": group.get("label"),
            "status": group.get("status"),
            "confidence": group.get("confidence"),
            "preferred_claim": group.get("preferred_claim"),
            "competing_claims": group.get("competing_claims") or [],
            "reason": group.get("reason"),
            "warnings": group.get("warnings") or [],
        })
    return out


def _gaps(
    query: str,
    grounded: GroundedAnswer,
    bundle: EvidenceBundle,
    canonical_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if grounded.confidence == "insufficient":
        gaps.append({
            "type": "missing_evidence",
            "message": "No approved local-file evidence was strong enough to answer without guessing.",
            "query": query,
        })
    if grounded.confidence == "low":
        gaps.append({
            "type": "weak_evidence",
            "message": "Evidence exists, but it is too weak for a confident answer.",
        })
    if not canonical_facts:
        gaps.append({
            "type": "missing_canonical_facts",
            "message": "No resolved or raw semantic facts were available for this packet.",
        })
    for warning in [*bundle.warnings, *bundle.reasoning_warnings]:
        lower = warning.lower()
        if "too_large" in lower or "skipped" in lower or "missing" in lower:
            gaps.append({"type": "unreadable_or_skipped_source", "message": warning})
    if grounded.follow_up_questions:
        gaps.append({
            "type": "clarification_needed",
            "message": "The question needs a narrower project, document, person, or metric.",
        })
    return _dedupe_dicts(gaps)


def _recommended_actions(
    grounded: GroundedAnswer,
    conflicts: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    warnings: list[str],
) -> list[str]:
    actions: list[str] = []
    if grounded.confidence == "insufficient":
        actions.append("Approve or index the folder that contains this information, then rebuild evidence.")
    if grounded.follow_up_questions:
        actions.append("Ask a narrower follow-up question using a project, person, metric, or document name.")
    if conflicts:
        actions.append("Review the competing source files before treating the preferred claim as final.")
    if any("semantic enrichment is not enabled" in w.lower() for w in warnings):
        actions.append("Run deterministic semantics, and optionally enable Ollama enrichment for richer objects.")
    if not actions and grounded.confidence in {"high", "medium"}:
        actions.append("Use the cited files as the primary source trail for this answer.")
    return _dedupe(actions)


def _source_map(bundle: EvidenceBundle, grounded: GroundedAnswer) -> list[dict[str, Any]]:
    citation_by_id = {str(c.get("id") or ""): c for c in grounded.citations}
    rows: list[dict[str, Any]] = []
    for item in bundle.selected_files:
        citation = citation_by_id.get(item.id) or {}
        rows.append({
            "file_id": item.id,
            "title": item.title,
            "path": item.path,
            "role": "primary" if item.evidence_source == "direct" else "related",
            "reason": item.reason,
            "confidence": item.confidence,
            "score": item.score,
            "is_latest_candidate": item.is_latest_candidate,
            "duplicate_of": item.duplicate_of,
            "suppressed": False,
            "resolved_claim_id": citation.get("resolved_claim_id"),
            "conflict_group_id": citation.get("conflict_group_id"),
        })
    for item in bundle.suppressed_files:
        rows.append({
            "file_id": item.id,
            "title": item.title,
            "path": item.path,
            "role": "suppressed",
            "reason": item.reason,
            "confidence": item.confidence,
            "score": item.score,
            "is_latest_candidate": item.is_latest_candidate,
            "duplicate_of": item.duplicate_of,
            "suppressed": True,
            "resolved_claim_id": None,
            "conflict_group_id": None,
        })
    return [row for row in rows if _path_allowed(row.get("path") or "")]


def _timeline(canonical_facts: list[dict[str, Any]], source_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for fact in canonical_facts:
        period = fact.get("period")
        if period:
            entries.append({
                "type": "fact_period",
                "label": f"{fact.get('entity') or ''} {fact.get('attribute') or ''}".strip(),
                "when": period,
                "fact_id": fact.get("fact_id"),
            })
    for source in source_map:
        if source.get("is_latest_candidate"):
            entries.append({
                "type": "latest_source_candidate",
                "label": source.get("title"),
                "file_id": source.get("file_id"),
            })
    return entries[:20]


def _summary_answer(grounded: GroundedAnswer, facts: list[dict[str, Any]], gaps: list[dict[str, Any]]) -> str:
    if grounded.confidence == "insufficient":
        return "SHAIL does not have enough approved local evidence to answer this yet."
    if facts:
        return f"SHAIL found {len(facts)} source-backed fact(s) for this topic."
    if gaps:
        return "SHAIL found gaps that need clarification or more approved evidence."
    return grounded.answer


def _try_ollama_synthesis(
    answer: str,
    facts: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
) -> tuple[Optional[str], Optional[str]]:
    try:
        import httpx

        settings = get_settings()
        prompt = (
            "Rewrite this local intelligence packet as a concise brief. "
            "Do not add facts. Use only this JSON.\n"
            + json.dumps({
                "answer": answer,
                "facts": facts[:12],
                "conflicts": conflicts[:8],
                "gaps": gaps[:8],
            }, ensure_ascii=False)
        )
        payload = {
            "model": settings.shail_local_intelligence_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_ctx": min(settings.ollama_num_ctx, 8192)},
        }
        with httpx.Client(timeout=8.0) as client:
            res = client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
            res.raise_for_status()
            data = res.json()
        text = ((data.get("message") or {}).get("content") or "").strip()
        return (text[:4000] if text else None), None
    except Exception as exc:
        return None, f"Ollama intelligence synthesis was unavailable: {exc}"


def _packet_id(query: str, evidence_bundle_id: str, facts: list[dict[str, Any]], ts: float) -> str:
    raw = "|".join([query.strip().lower(), evidence_bundle_id, str(len(facts)), f"{ts:.6f}"])
    return "intel_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return prefix + ":" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _source_files_for_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen: set[str] = set()
    for claim in claims:
        if not claim:
            continue
        path = str(claim.get("path") or "")
        fid = str(claim.get("file_id") or "")
        if not path or not _path_allowed(path) or fid in seen:
            continue
        seen.add(fid)
        out.append({
            "file_id": fid,
            "path": path,
            "title": Path(path).name,
            "claim_id": claim.get("claim_id") or claim.get("id"),
        })
    return out


def _path_allowed(path: str) -> bool:
    if not path:
        return False
    try:
        db = get_settings().path_index_db
        if path_index.is_denied(db, path):
            return False
        row = path_index.get_by_path(db, path)
        if row and row.get("deleted_at"):
            return False
    except Exception:
        return False
    return True


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        key = str(value).strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _dedupe_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen: set[str] = set()
    for fact in facts:
        fid = str(fact.get("fact_id") or "")
        if fid in seen:
            continue
        seen.add(fid)
        out.append(fact)
    return out


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen: set[str] = set()
    for item in items:
        key = json.dumps(item, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
