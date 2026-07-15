"""Evidence bundles for graph-guided local-file answers.

The bundle is query-time derived state. It reads only approved local files,
keeps citations pointer-first, and adds Graphify reasons before the LLM sees
local-file context.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from apps.shail import local_graph
from apps.shail import local_semantic_reasoning
from apps.shail import local_semantics
from apps.shail.retrieval.local_files import (
    _best_snippet,
    retrieve_local_file_context,
)
from apps.shail.settings import get_settings
from shail.memory import path_index


Confidence = str

_RELATION_WEIGHTS = {
    "same_content_as": 0.98,
    "newer_than": 0.92,
    "version_of": 0.86,
    "belongs_to_project": 0.74,
    "has_topic": 0.68,
    "mentions_entity": 0.62,
    "nearby_in_folder": 0.42,
}


@dataclass
class EvidenceItem:
    id: str
    title: str
    path: str
    snippet: str
    file_type: str = ""
    score: float = 0.0
    reason: str = "Direct local-file match"
    graph_relation: Optional[str] = None
    graph_evidence: Optional[str] = None
    evidence_source: str = "direct"
    confidence: Confidence = "medium"
    is_latest_candidate: bool = False
    is_duplicate_candidate: bool = False
    duplicate_of: Optional[str] = None
    content_hash: Optional[str] = None
    mtime: Optional[float] = None
    size_bytes: Optional[int] = None
    extractor_used: Optional[str] = None


@dataclass
class EvidenceBundle:
    evidence_bundle_id: str
    query: str
    direct_matches: list[EvidenceItem] = field(default_factory=list)
    graph_expansions: list[EvidenceItem] = field(default_factory=list)
    selected_files: list[EvidenceItem] = field(default_factory=list)
    suppressed_files: list[EvidenceItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: Confidence = "low"
    prompt_context: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    semantic_facts: list[dict[str, Any]] = field(default_factory=list)
    semantic_tasks: list[dict[str, Any]] = field(default_factory=list)
    semantic_entities: list[dict[str, Any]] = field(default_factory=list)
    semantic_warnings: list[str] = field(default_factory=list)
    semantic_resolutions: list[dict[str, Any]] = field(default_factory=list)
    semantic_conflicts: list[dict[str, Any]] = field(default_factory=list)
    reasoning_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bundle_id(query: str, selected_ids: list[str]) -> str:
    raw = "|".join([query.strip().lower(), *selected_ids])
    return "evb_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _row_for_file_id(file_id: str) -> Optional[dict[str, Any]]:
    try:
        row = path_index.get_by_id(get_settings().path_index_db, file_id)
        return dict(row) if row else None
    except Exception:
        return None


def _is_allowed_row(row: dict[str, Any]) -> bool:
    p = row.get("path") or ""
    if not p or row.get("deleted_at"):
        return False
    return not path_index.is_denied(get_settings().path_index_db, p)


def _read_snippet(
    row: dict[str, Any],
    query: str,
    *,
    max_snippet_chars: int,
    read_cap_bytes: int,
) -> tuple[str, Optional[str], Optional[str]]:
    file_path = row.get("path") or ""
    if not file_path or not os.path.exists(file_path):
        return "", None, "missing_on_disk"
    try:
        size = os.path.getsize(file_path)
    except OSError:
        size = None
    if size is not None and size > read_cap_bytes:
        return "", None, "too_large"

    text = ""
    extractor = None
    try:
        from shail.memory.rag import _extract_text_from_file
        text = _extract_text_from_file(file_path) or ""
        extractor = "rag" if text else None
    except Exception:
        text = ""
    if not text:
        text = row.get("summary_snippet") or ""
        extractor = "snippet" if text else extractor
    if not text:
        return "", extractor, "empty_extract"
    return _best_snippet(text, query, max_chars=max_snippet_chars), extractor, None


def _item_from_hit(hit: Any, row: Optional[dict[str, Any]]) -> EvidenceItem:
    row = row or {}
    return EvidenceItem(
        id=getattr(hit, "id", "") or row.get("id") or getattr(hit, "path", ""),
        title=getattr(hit, "title", "") or row.get("title") or Path(getattr(hit, "path", "")).name,
        path=getattr(hit, "path", "") or row.get("path") or "",
        snippet=getattr(hit, "snippet", "") or row.get("summary_snippet") or "",
        file_type=getattr(hit, "file_type", "") or row.get("file_type") or "",
        score=float(getattr(hit, "score", 0.0) or 0.0),
        reason="Direct match in approved local files",
        evidence_source="direct",
        confidence="high",
        content_hash=row.get("content_hash"),
        mtime=row.get("mtime"),
        size_bytes=row.get("size_bytes"),
        extractor_used=getattr(hit, "extractor_used", None),
    )


def _item_from_row(
    row: dict[str, Any],
    query: str,
    *,
    base_score: float,
    relation: str,
    evidence: Optional[str],
    max_snippet_chars: int,
    read_cap_bytes: int,
) -> tuple[Optional[EvidenceItem], Optional[str]]:
    snippet, extractor, warning = _read_snippet(
        row, query,
        max_snippet_chars=max_snippet_chars,
        read_cap_bytes=read_cap_bytes,
    )
    if warning:
        return None, f"Skipped {Path(row.get('path') or '').name or row.get('id')} because it was {warning}."
    score = max(0.01, min(1.0, base_score * _RELATION_WEIGHTS.get(relation, 0.5)))
    return EvidenceItem(
        id=row.get("id") or row.get("path") or "",
        title=row.get("title") or Path(row.get("path") or "").name,
        path=row.get("path") or "",
        snippet=snippet,
        file_type=row.get("file_type") or "",
        score=score,
        reason=_plain_reason(relation, evidence),
        graph_relation=relation,
        graph_evidence=evidence,
        evidence_source="graph",
        confidence="medium" if relation in {"belongs_to_project", "has_topic", "version_of", "newer_than"} else "low",
        content_hash=row.get("content_hash"),
        mtime=row.get("mtime"),
        size_bytes=row.get("size_bytes"),
        extractor_used=extractor,
    ), None


def _plain_reason(relation: str, evidence: Optional[str]) -> str:
    if relation == "same_content_as":
        return "Same content as another selected file"
    if relation == "newer_than":
        return "Looks newer than a related file"
    if relation == "version_of":
        return "Part of the same version group"
    if relation == "belongs_to_project":
        return f"Belongs to the same approved project{f': {evidence}' if evidence else ''}"
    if relation == "has_topic":
        return f"Shares a topic{f': {evidence}' if evidence else ''}"
    if relation == "mentions_entity":
        return f"Mentions the same entity{f': {evidence}' if evidence else ''}"
    if relation == "nearby_in_folder":
        return "Nearby file in the same approved folder"
    return "Related through the local graph"


def _version_group_key(item: EvidenceItem) -> str:
    stem = Path(item.path).stem.lower()
    stem = re.sub(r"(?i)(?:^|[_\-\s.])(?:v(?:ersion)?\s*\d+|final|draft|copy|\d{4}[-_.]\d{1,2}[-_.]\d{1,2})(?:$|[_\-\s.])", "_", stem)
    stem = re.sub(r"[_\-\s.]+", "_", stem).strip("_")
    return f"{Path(item.path).parent}:{stem}:{Path(item.path).suffix.lower()}"


def _rank_version(item: EvidenceItem) -> tuple[int, float, int]:
    name = Path(item.path).name
    nums = [int(x) for x in re.findall(r"(?i)(?:v|version)[_\-\s.]*(\d+)", name)]
    version = max(nums) if nums else 0
    final_bonus = 1 if re.search(r"(?i)\bfinal\b", name) else 0
    return final_bonus, version, float(item.mtime or 0.0)


def _select_items(
    direct: list[EvidenceItem],
    graph: list[EvidenceItem],
    *,
    max_total_evidence: int,
) -> tuple[list[EvidenceItem], list[EvidenceItem], list[str]]:
    warnings: list[str] = []
    candidates = sorted([*direct, *graph], key=lambda i: i.score, reverse=True)
    selected: list[EvidenceItem] = []
    suppressed: list[EvidenceItem] = []
    by_hash: dict[str, EvidenceItem] = {}

    for item in candidates:
        if item.content_hash and item.content_hash in by_hash:
            item.is_duplicate_candidate = True
            item.duplicate_of = by_hash[item.content_hash].id
            item.reason = f"Duplicate of {by_hash[item.content_hash].title}"
            suppressed.append(item)
            continue
        if len(selected) < max_total_evidence:
            selected.append(item)
            if item.content_hash:
                by_hash[item.content_hash] = item
        else:
            suppressed.append(item)

    groups: dict[str, list[EvidenceItem]] = {}
    for item in [*selected, *suppressed]:
        groups.setdefault(_version_group_key(item), []).append(item)
    for group in groups.values():
        if len(group) < 2:
            continue
        latest = max(group, key=_rank_version)
        latest.is_latest_candidate = True
        for item in group:
            if item.id != latest.id and item in selected:
                item.confidence = "medium"
        if any(item.id != latest.id for item in group):
            warnings.append("Older related versions were found; the latest-looking file is marked in the evidence.")

    if any(i.is_duplicate_candidate for i in suppressed):
        warnings.append("Duplicate files were found and suppressed from the prompt context.")
    return selected, suppressed, warnings


def _confidence(selected: list[EvidenceItem], warnings: list[str]) -> Confidence:
    if not selected:
        return "low"
    high = sum(1 for item in selected if item.confidence == "high")
    if high >= 2 or (high >= 1 and len(selected) >= 2):
        return "medium" if any("Skipped" in w for w in warnings) else "high"
    return "medium" if high else "low"


def _render_prompt_context(bundle: EvidenceBundle) -> str:
    if not bundle.selected_files:
        return (
            "[LOCAL FILE EVIDENCE BUNDLE]\n"
            "No approved local-file evidence was strong enough for this query.\n"
            "Do not claim local-file facts unless other context supports them."
        )

    lines = [
        "[LOCAL FILE EVIDENCE BUNDLE]",
        "Rules:",
        "- These files are approved local files.",
        "- Content was read live from disk.",
        "- Use citations when referencing them.",
        "",
        f"Bundle confidence: {bundle.confidence}",
        "",
        "Primary evidence:",
    ]
    primary = [item for item in bundle.selected_files if item.evidence_source == "direct"]
    related = [item for item in bundle.selected_files if item.evidence_source == "graph"]
    for item in primary:
        lines.extend(_render_item(item))
    if related:
        lines.extend(["", "Related evidence:"])
        for item in related:
            lines.extend(_render_item(item))
    if bundle.semantic_facts or bundle.semantic_tasks or bundle.semantic_entities:
        lines.extend(["", "Semantic evidence:"])
        for fact in bundle.semantic_facts[:12]:
            head = " ".join(str(fact.get(k) or "") for k in ("entity", "attribute")).strip() or "fact"
            value = fact.get("value") or ""
            source = fact.get("source_span") or ""
            lines.append(f"- {head}: {value} [file_id={fact.get('file_id')} confidence={fact.get('confidence')}]")
            if source:
                lines.append(f"  source: {source}")
        for task in bundle.semantic_tasks[:8]:
            lines.append(f"- task: {task.get('text')} [file_id={task.get('file_id')} status={task.get('status')} confidence={task.get('confidence')}]")
        for entity in bundle.semantic_entities[:12]:
            lines.append(f"- {entity.get('entity_type')}: {entity.get('label')} [file_id={entity.get('file_id')} confidence={entity.get('confidence')}]")
    if bundle.semantic_warnings:
        lines.extend(["", "Semantic warnings:"])
        lines.extend(f"- {w}" for w in bundle.semantic_warnings)
    if bundle.semantic_resolutions:
        lines.extend(["", "Resolved semantic facts:"])
        for group in bundle.semantic_resolutions[:10]:
            claim = group.get("preferred_claim") or {}
            label = group.get("label") or "fact"
            value = claim.get("value") or ""
            source = claim.get("source_span") or ""
            lines.append(f"- {label}: {value} [file_id={claim.get('file_id')} confidence={group.get('confidence')}]")
            if group.get("reason"):
                lines.append(f"  why: {group.get('reason')}")
            if source:
                lines.append(f"  source: {source}")
    if bundle.semantic_conflicts:
        lines.extend(["", "Semantic conflicts:"])
        for group in bundle.semantic_conflicts[:8]:
            label = group.get("label") or "fact"
            values = []
            preferred = group.get("preferred_claim") or {}
            if preferred.get("value"):
                values.append(f"preferred={preferred.get('value')}")
            values.extend(
                str(c.get("value"))
                for c in (group.get("competing_claims") or [])[:3]
                if c.get("value")
            )
            lines.append(f"- {label}: {', '.join(values)} [status={group.get('status')} confidence={group.get('confidence')}]")
            if group.get("reason"):
                lines.append(f"  why: {group.get('reason')}")
    if bundle.reasoning_warnings:
        lines.extend(["", "Reasoning warnings:"])
        lines.extend(f"- {w}" for w in bundle.reasoning_warnings)
    if bundle.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {w}" for w in bundle.warnings)
    return "\n".join(lines)


def _render_item(item: EvidenceItem) -> list[str]:
    flags = []
    if item.is_latest_candidate:
        flags.append("latest_candidate=true")
    if item.is_duplicate_candidate:
        flags.append("duplicate_candidate=true")
    if item.graph_relation:
        flags.append(f"graph_relation={item.graph_relation}")
    flag_text = f" {' '.join(flags)}" if flags else ""
    return [
        f"[local_file_id={item.id} type={item.file_type or 'unknown'} score={item.score:.2f} confidence={item.confidence}{flag_text}]",
        f"title: {item.title}",
        f"path: {item.path}",
        f"why: {item.reason}",
        item.snippet,
        "",
    ]


def build_evidence_bundle(
    query: str,
    *,
    user_id: Optional[str] = None,
    k: int = 8,
    include_graph: bool = True,
    max_direct_files: Optional[int] = None,
    max_graph_neighbors: int = 3,
    max_total_evidence: Optional[int] = None,
    max_snippet_chars: Optional[int] = None,
    read_cap_bytes: Optional[int] = None,
) -> EvidenceBundle:
    del user_id  # local approved files are already scoped by path_index roots.
    settings = get_settings()
    max_direct_files = max_direct_files or min(k, settings.shail_local_files_k)
    max_total_evidence = max_total_evidence or max(k, max_direct_files)
    max_snippet_chars = max_snippet_chars or settings.shail_local_files_snippet_chars
    read_cap_bytes = read_cap_bytes or settings.shail_local_files_read_cap_bytes
    warnings: list[str] = []

    if not query.strip():
        bundle = EvidenceBundle(evidence_bundle_id=_bundle_id(query, []), query=query, warnings=["No query provided."])
        bundle.prompt_context = _render_prompt_context(bundle)
        return bundle

    direct_hits = retrieve_local_file_context(
        query,
        k=max_direct_files,
        max_snippet_chars=max_snippet_chars,
        read_cap_bytes=read_cap_bytes,
    )
    direct = []
    for hit in direct_hits:
        row = _row_for_file_id(hit.id)
        if row and not _is_allowed_row(row):
            warnings.append(f"Skipped {hit.title} because it is no longer approved.")
            continue
        direct.append(_item_from_hit(hit, row))

    graph_items: list[EvidenceItem] = []
    if include_graph and direct:
        try:
            graph = local_graph.load_graph(limit=25)
            if not graph.get("nodes"):
                local_graph.build_local_file_graph(limit=1000)
        except Exception:
            try:
                local_graph.build_local_file_graph(limit=1000)
            except Exception as exc:
                warnings.append(f"Graph expansion was unavailable: {exc}")

        seen_ids = {item.id for item in direct}
        for item in direct[:max_direct_files]:
            try:
                related = local_graph.related_local_file_ids(item.id, limit=max_graph_neighbors)
            except Exception as exc:
                warnings.append(f"Graph neighbors were unavailable for {item.title}: {exc}")
                continue
            for rel in related:
                rid = rel.get("id")
                if not rid or rid in seen_ids:
                    continue
                row = _row_for_file_id(rid)
                if not row or not _is_allowed_row(row):
                    continue
                graph_item, warning = _item_from_row(
                    row,
                    query,
                    base_score=item.score,
                    relation=rel.get("graph_reason") or "graph_neighbor",
                    evidence=rel.get("evidence"),
                    max_snippet_chars=max_snippet_chars,
                    read_cap_bytes=read_cap_bytes,
                )
                if warning:
                    warnings.append(warning)
                    continue
                if graph_item:
                    graph_items.append(graph_item)
                    seen_ids.add(rid)

    selected, suppressed, selection_warnings = _select_items(
        direct, graph_items, max_total_evidence=max_total_evidence,
    )
    warnings.extend(selection_warnings)
    if not selected:
        warnings.append("No approved local-file evidence was strong enough for this question.")

    semantic = local_semantics.semantic_rows_for_files([item.id for item in selected], limit_per_file=5)
    semantic_facts: list[dict[str, Any]] = []
    semantic_tasks: list[dict[str, Any]] = []
    semantic_entities: list[dict[str, Any]] = []
    for item in selected:
        rows = semantic.get(item.id) or {}
        semantic_facts.extend(rows.get("facts") or [])
        semantic_tasks.extend(rows.get("tasks") or [])
        semantic_entities.extend(rows.get("entities") or [])
        first_fact = next((f for f in rows.get("facts") or [] if f.get("value")), None)
        first_task = next(iter(rows.get("tasks") or []), None)
        if first_fact:
            item.reason = f"Contains semantic fact: {first_fact.get('attribute')} = {first_fact.get('value')}"
            item.confidence = "high" if item.confidence == "medium" else item.confidence
        elif first_task:
            item.reason = f"Contains task: {first_task.get('text')}"
            item.confidence = "high" if item.confidence == "medium" else item.confidence

    semantic_warnings = _semantic_conflict_warnings(semantic_facts)
    try:
        if not get_settings().shail_local_semantic_llm:
            semantic_warnings.append("Ollama semantic enrichment is not enabled; evidence uses deterministic semantic extraction only.")
    except Exception:
        pass

    semantic_resolutions: list[dict[str, Any]] = []
    semantic_conflicts: list[dict[str, Any]] = []
    reasoning_warnings: list[str] = []
    try:
        reasoning = local_semantic_reasoning.reasoning_for_files([item.id for item in selected], limit_per_file=4)
        semantic_resolutions = reasoning.get("resolutions") or []
        semantic_conflicts = reasoning.get("conflicts") or []
        reasoning_warnings = reasoning.get("warnings") or []
    except Exception as exc:
        reasoning_warnings.append(f"Semantic reasoning was unavailable: {exc}")

    preferred_by_file: dict[str, list[dict[str, Any]]] = {}
    for group in semantic_resolutions:
        claim = group.get("preferred_claim") or {}
        fid = claim.get("file_id")
        if fid:
            preferred_by_file.setdefault(str(fid), []).append(group)
    for item in selected:
        groups = preferred_by_file.get(item.id) or []
        if not groups:
            continue
        group = groups[0]
        claim = group.get("preferred_claim") or {}
        value = claim.get("value") or ""
        label = group.get("label") or claim.get("attribute") or "semantic fact"
        item.reason = f"Preferred resolved semantic fact: {label} = {value}".strip()
        if group.get("confidence") in {"high", "medium"}:
            item.confidence = "high"

    bundle = EvidenceBundle(
        evidence_bundle_id=_bundle_id(query, [item.id for item in selected]),
        query=query,
        direct_matches=direct,
        graph_expansions=graph_items,
        selected_files=selected,
        suppressed_files=suppressed,
        warnings=_dedupe(warnings),
        confidence="low",
        citations=[_citation(item) for item in selected],
        semantic_facts=semantic_facts,
        semantic_tasks=semantic_tasks,
        semantic_entities=semantic_entities,
        semantic_warnings=semantic_warnings,
        semantic_resolutions=semantic_resolutions,
        semantic_conflicts=semantic_conflicts,
        reasoning_warnings=_dedupe(reasoning_warnings),
    )
    bundle.confidence = _confidence(bundle.selected_files, bundle.warnings)
    bundle.prompt_context = _render_prompt_context(bundle)
    return bundle


def _semantic_conflict_warnings(facts: list[dict[str, Any]]) -> list[str]:
    grouped: dict[tuple[str, str, str], set[str]] = {}
    for fact in facts:
        key = (
            str(fact.get("entity") or "").lower(),
            str(fact.get("attribute") or "").lower(),
            str(fact.get("period") or "").lower(),
        )
        value = str(fact.get("value") or "").strip()
        if not key[0] and not key[1]:
            continue
        if value:
            grouped.setdefault(key, set()).add(value)
    warnings = []
    for (entity, attr, period), values in grouped.items():
        if len(values) > 1:
            label = " ".join(p for p in (entity, attr, period) if p)
            warnings.append(f"Conflicting semantic facts found for {label}: {', '.join(sorted(values)[:4])}.")
    return warnings


def _citation(item: EvidenceItem) -> dict[str, Any]:
    return {
        "type": "local_file",
        "id": item.id,
        "title": item.title,
        "path": item.path,
        "snippet": item.snippet,
        "file_type": item.file_type,
        "score": item.score,
        "graph_reason": item.graph_relation,
        "evidence_reason": item.reason,
        "confidence": item.confidence,
        "is_latest_candidate": item.is_latest_candidate,
        "duplicate_of": item.duplicate_of,
    }


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
