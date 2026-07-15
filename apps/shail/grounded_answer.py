"""Grounded local-file answer orchestration.

This layer sits after evidence selection. It does not discover new local files
or ingest raw file content into vector memory; it decides whether the approved
evidence is strong enough to answer and prepares a citation-compatible result.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from apps.shail.evidence_bundle import EvidenceBundle, build_evidence_bundle
from apps.shail.settings import get_settings


AnswerConfidence = str


@dataclass
class GroundedAnswer:
    answer: str
    confidence: AnswerConfidence
    evidence_bundle_id: str
    query: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    evidence_summary: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)
    unresolved_conflicts: list[dict[str, Any]] = field(default_factory=list)
    semantic_resolutions: list[dict[str, Any]] = field(default_factory=list)
    semantic_conflicts: list[dict[str, Any]] = field(default_factory=list)
    quality_score: float = 0.0
    quality_signals: dict[str, Any] = field(default_factory=dict)
    prompt_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_grounded_answer(
    query: str,
    *,
    user_id: Optional[str] = None,
    k: int = 8,
    include_graph: bool = True,
    evidence_bundle: Optional[EvidenceBundle] = None,
) -> GroundedAnswer:
    settings = get_settings()
    if not getattr(settings, "shail_local_files_in_chat", True):
        empty = evidence_bundle or EvidenceBundle(
            evidence_bundle_id="evb_local_files_disabled",
            query=query,
            warnings=["Local files are disabled for chat."],
        )
        return _insufficient_answer(
            query,
            empty,
            ["Local files are disabled for chat."],
            ["Enable local-file answers or ask using another connected source."],
        )

    bundle = evidence_bundle or build_evidence_bundle(
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

    quality = score_evidence_quality(bundle)
    warnings = _plain_warnings(bundle, quality)
    followups = _followups(query, bundle, quality)

    if quality["confidence"] == "insufficient":
        return _insufficient_answer(query, bundle, warnings, followups, quality=quality)
    if followups and quality["confidence"] in {"low", "insufficient"}:
        return GroundedAnswer(
            answer="I need one more detail before I can answer from your approved local files.",
            confidence="low",
            evidence_bundle_id=bundle.evidence_bundle_id,
            query=query,
            citations=_augment_citations(bundle, "low"),
            evidence_summary=_evidence_summary(bundle),
            warnings=warnings,
            follow_up_questions=followups,
            unresolved_conflicts=_unresolved_conflicts(bundle),
            semantic_resolutions=bundle.semantic_resolutions,
            semantic_conflicts=bundle.semantic_conflicts,
            quality_score=float(quality["score"]),
            quality_signals=quality,
            prompt_context=_render_answer_context(bundle, "low", warnings, followups),
        )

    answer = _draft_answer(bundle, quality)
    confidence = str(quality["confidence"])
    return GroundedAnswer(
        answer=answer,
        confidence=confidence,
        evidence_bundle_id=bundle.evidence_bundle_id,
        query=query,
        citations=_augment_citations(bundle, confidence),
        evidence_summary=_evidence_summary(bundle),
        warnings=warnings,
        follow_up_questions=followups,
        unresolved_conflicts=_unresolved_conflicts(bundle),
        semantic_resolutions=bundle.semantic_resolutions,
        semantic_conflicts=bundle.semantic_conflicts,
        quality_score=float(quality["score"]),
        quality_signals=quality,
        prompt_context=_render_answer_context(bundle, confidence, warnings, followups, answer=answer),
    )


def score_evidence_quality(bundle: EvidenceBundle) -> dict[str, Any]:
    selected = bundle.selected_files
    direct = [item for item in selected if item.evidence_source == "direct"]
    graph = [item for item in selected if item.evidence_source == "graph"]
    high_items = [item for item in selected if item.confidence == "high"]
    semantic_hits = len(bundle.semantic_facts) + len(bundle.semantic_tasks) + len(bundle.semantic_resolutions)
    resolved_high = [
        group for group in bundle.semantic_resolutions
        if group.get("confidence") == "high" and group.get("preferred_claim")
    ]
    resolved_medium = [
        group for group in bundle.semantic_resolutions
        if group.get("confidence") == "medium" and group.get("preferred_claim")
    ]
    unresolved = _unresolved_conflicts(bundle)
    duplicate_risk = bool(bundle.suppressed_files)
    version_risk = any(not item.is_latest_candidate for item in selected) and any(item.is_latest_candidate for item in [*selected, *bundle.suppressed_files])
    old_or_skipped = any("Skipped" in w or "older" in w.lower() for w in [*bundle.warnings, *bundle.reasoning_warnings])

    score = 0.0
    score += min(0.35, 0.12 * len(direct))
    score += min(0.18, 0.06 * len(graph))
    score += min(0.24, 0.05 * semantic_hits)
    score += 0.22 if resolved_high else 0.12 if resolved_medium else 0.0
    score += min(0.12, 0.04 * len(high_items))
    if unresolved:
        score -= 0.24
    if duplicate_risk:
        score -= 0.06
    if version_risk:
        score -= 0.08
    if old_or_skipped:
        score -= 0.08
    if not selected:
        score = 0.0
    score = max(0.0, min(1.0, score))

    if not selected or score < 0.18:
        confidence = "insufficient"
    elif unresolved and not resolved_high:
        confidence = "low"
    elif score >= 0.72 and not unresolved:
        confidence = "high"
    elif score >= 0.42:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "score": round(score, 3),
        "confidence": confidence,
        "direct_match_strength": len(direct),
        "graph_support_strength": len(graph),
        "semantic_fact_match": semantic_hits,
        "resolved_claim_confidence": "high" if resolved_high else "medium" if resolved_medium else "none",
        "conflict_severity": "unresolved" if unresolved else "resolved" if bundle.semantic_conflicts else "none",
        "duplicate_risk": duplicate_risk,
        "version_risk": version_risk,
        "snippet_read_quality": "present" if any((item.snippet or "").strip() for item in selected) else "weak",
    }


def _draft_answer(bundle: EvidenceBundle, quality: dict[str, Any]) -> str:
    if bundle.semantic_resolutions:
        usable = [
            group for group in bundle.semantic_resolutions
            if group.get("preferred_claim") and group.get("confidence") in {"high", "medium"}
        ]
        if usable:
            lines = []
            for group in usable[:3]:
                claim = group.get("preferred_claim") or {}
                label = group.get("label") or "fact"
                value = claim.get("value") or claim.get("value_num") or ""
                if value:
                    lines.append(f"{label}: {value}")
            if lines:
                prefix = "The strongest approved local evidence says"
                if quality.get("conflict_severity") == "resolved":
                    prefix = "The strongest approved local evidence, after checking competing claims, says"
                return prefix + " " + "; ".join(lines) + "."

    if bundle.semantic_tasks:
        tasks = [str(t.get("text") or "").strip() for t in bundle.semantic_tasks if t.get("text")]
        if tasks:
            return "I found these task-like items in approved local files: " + "; ".join(tasks[:5]) + "."

    if bundle.semantic_facts:
        facts = []
        for fact in bundle.semantic_facts[:5]:
            label = " ".join(str(fact.get(k) or "") for k in ("entity", "attribute")).strip()
            value = fact.get("value") or fact.get("value_num")
            if label and value:
                facts.append(f"{label}: {value}")
        if facts:
            return "I found these approved local-file facts: " + "; ".join(facts) + "."

    titles = [item.title for item in bundle.selected_files[:4]]
    return "I found approved local files that look relevant: " + ", ".join(titles) + ". Use the citations to inspect the exact source."


def _plain_warnings(bundle: EvidenceBundle, quality: dict[str, Any]) -> list[str]:
    warnings = [*_dedupe(bundle.warnings), *_dedupe(bundle.semantic_warnings), *_dedupe(bundle.reasoning_warnings)]
    if bundle.semantic_conflicts:
        if _unresolved_conflicts(bundle):
            warnings.append("I found conflicting values and could not safely choose one.")
        else:
            warnings.append("I found conflicting values; I used the strongest resolved claim.")
    if quality.get("version_risk"):
        warnings.append("The strongest file may have older or newer related versions.")
    if quality.get("duplicate_risk"):
        warnings.append("Duplicate files were found and were not repeated in the answer context.")
    if quality.get("semantic_fact_match") == 0 and bundle.selected_files:
        warnings.append("I only found weak semantic evidence, so the answer should be treated cautiously.")
    if not bundle.selected_files:
        warnings.append("I do not have enough approved local-file evidence to answer this.")
    return _dedupe(warnings)


def _followups(query: str, bundle: EvidenceBundle, quality: dict[str, Any]) -> list[str]:
    normalized = re.sub(r"[^a-z0-9\s]", " ", query.lower())
    terms = [t for t in normalized.split() if len(t) > 2 and t not in {"what", "which", "where", "when", "about", "latest", "file", "files", "this", "that", "thing"}]
    if not query.strip():
        return ["What local-file question should I answer?"]
    if not bundle.selected_files:
        return ["Which project, folder, person, or document should I search inside approved local files?"]
    if len(terms) < 2 and quality.get("confidence") in {"low", "insufficient"}:
        return ["Which specific project, person, metric, or document are you asking about?"]
    return []


def _insufficient_answer(
    query: str,
    bundle: EvidenceBundle,
    warnings: list[str],
    followups: list[str],
    *,
    quality: Optional[dict[str, Any]] = None,
) -> GroundedAnswer:
    quality = quality or score_evidence_quality(bundle)
    return GroundedAnswer(
        answer="I do not have enough approved local-file evidence to answer that without guessing.",
        confidence="insufficient",
        evidence_bundle_id=bundle.evidence_bundle_id,
        query=query,
        citations=_augment_citations(bundle, "insufficient"),
        evidence_summary=_evidence_summary(bundle),
        warnings=_dedupe(warnings),
        follow_up_questions=followups,
        unresolved_conflicts=_unresolved_conflicts(bundle),
        semantic_resolutions=bundle.semantic_resolutions,
        semantic_conflicts=bundle.semantic_conflicts,
        quality_score=float(quality["score"]),
        quality_signals=quality,
        prompt_context=_render_answer_context(bundle, "insufficient", warnings, followups),
    )


def _augment_citations(bundle: EvidenceBundle, answer_confidence: str) -> list[dict[str, Any]]:
    claim_by_file: dict[str, dict[str, Any]] = {}
    conflict_by_file: dict[str, dict[str, Any]] = {}
    for group in bundle.semantic_resolutions:
        claim = group.get("preferred_claim") or {}
        fid = str(claim.get("file_id") or "")
        if fid:
            claim_by_file[fid] = group
    for group in bundle.semantic_conflicts:
        group_id = group.get("group_id") or group.get("id")
        claims = [group.get("preferred_claim") or {}, *(group.get("competing_claims") or [])]
        for claim in claims:
            fid = str(claim.get("file_id") or "")
            if fid:
                conflict_by_file[fid] = {"group_id": group_id, "status": group.get("status")}

    out: list[dict[str, Any]] = []
    for citation in bundle.citations:
        item = dict(citation)
        fid = str(item.get("id") or "")
        resolution = claim_by_file.get(fid) or {}
        conflict = conflict_by_file.get(fid) or {}
        item["answer_confidence"] = answer_confidence
        item["evidence_bundle_id"] = bundle.evidence_bundle_id
        item["resolved_claim_id"] = (resolution.get("preferred_claim") or {}).get("claim_id") or (resolution.get("preferred_claim") or {}).get("id")
        item["conflict_group_id"] = conflict.get("group_id")
        item["warning_type"] = "conflict" if conflict else "duplicate" if item.get("duplicate_of") else None
        out.append(item)
    return out


def _evidence_summary(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    return [
        {
            "file_id": item.id,
            "title": item.title,
            "path": item.path,
            "reason": item.reason,
            "confidence": item.confidence,
            "score": item.score,
            "evidence_source": item.evidence_source,
            "graph_relation": item.graph_relation,
            "is_latest_candidate": item.is_latest_candidate,
            "duplicate_of": item.duplicate_of,
        }
        for item in bundle.selected_files
    ]


def _unresolved_conflicts(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    return [
        group for group in bundle.semantic_conflicts
        if str(group.get("status") or "").lower() in {"unresolved", "conflict"}
        or str(group.get("confidence") or "").lower() in {"low", "unresolved"}
    ]


def _render_answer_context(
    bundle: EvidenceBundle,
    confidence: str,
    warnings: list[str],
    followups: list[str],
    *,
    answer: str = "",
) -> str:
    lines = [
        bundle.prompt_context,
        "",
        "[LOCAL FILE ANSWER DECISION]",
        f"answer_confidence: {confidence}",
    ]
    if answer:
        lines.append(f"grounded_draft_answer: {answer}")
    if warnings:
        lines.append("answer_warnings:")
        lines.extend(f"- {w}" for w in _dedupe(warnings))
    if followups:
        lines.append("suggested_follow_up_questions:")
        lines.extend(f"- {q}" for q in followups)
    lines.extend([
        "Rules:",
        "- Answer only from approved local-file evidence in this packet.",
        "- If evidence is insufficient or conflicting, say that clearly.",
        "- Do not invent local-file facts outside this packet.",
    ])
    return "\n".join(lines)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        key = value.strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out
