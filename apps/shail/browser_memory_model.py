"""Canonical browser-memory read model.

This module is the shared source of truth for browser/AI memory surfaces. It
merges vector rows, raw transcripts, pipeline state, blueprint state, and
legacy anonymous browser captures into one deduped model used by sidepanel,
dashboard, export, graph, and capture-state endpoints.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from apps.shail.source_normalization import (
    is_browser_memory,
    normalize_browser_metadata,
)
from shail.memory.rag import _get_store, search as rag_search

NS_BROWSER = "browser_memory"


@dataclass
class BrowserMemoryRecord:
    id: str
    customId: str
    eventType: str
    sourceApp: str
    sourceUrl: str
    title: str
    summary: str
    timestamp: str
    content: str = ""
    tags: List[str] = field(default_factory=list)
    pinned: bool = False
    score: Optional[float] = None
    namespace: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    conversationId: str = ""
    captureMode: str = "active"
    captureSource: str = ""
    retentionPolicy: str = "keep_raw"
    transcriptDeletedAt: Optional[str] = None
    rawEmbedded: Optional[bool] = None
    rawBlueprinted: Optional[bool] = None
    segmentCount: Optional[int] = None
    contentChars: Optional[int] = None
    pipeline: Dict[str, Any] = field(default_factory=dict)
    blueprint: Dict[str, Any] = field(default_factory=dict)
    state: str = "captured"
    isPending: bool = False
    isRecovered: bool = False
    fidelity: Optional[float] = None
    confidence: Optional[float] = None
    parentId: Optional[str] = None
    version: int = 1
    forgetAfter: Optional[str] = None
    isForgotten: bool = False
    memoryRelations: Dict[str, str] = field(default_factory=dict)

    def to_extension_item(self, include_content: bool = False) -> Dict[str, Any]:
        return {
            "id": self.id,
            "customId": self.customId,
            "eventType": self.eventType,
            "sourceApp": self.sourceApp,
            "sourceUrl": self.sourceUrl,
            "title": self.title,
            "summary": self.summary,
            "timestamp": self.timestamp,
            "tags": self.tags,
            "pinned": self.pinned,
            "score": self.score,
            "content": self.content if include_content else None,
        }

    def to_dashboard_item(self, include_content: bool = False) -> Dict[str, Any]:
        out = self.to_extension_item(include_content=include_content)
        out.update({
            "confidence": self.confidence,
            "state": self.state,
            "parentId": self.parentId,
            "version": self.version,
            "fidelity": self.fidelity,
            "forgetAfter": self.forgetAfter,
            "isForgotten": self.isForgotten,
            "memoryRelations": self.memoryRelations,
        })
        return out


def visible_namespaces(primary_namespace: str, *, include_legacy: bool = True) -> List[str]:
    namespaces = [primary_namespace]
    if include_legacy and primary_namespace != NS_BROWSER:
        namespaces.append(NS_BROWSER)
    return list(dict.fromkeys(ns for ns in namespaces if ns))


def parse_tags(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(t) for t in raw if str(t).strip()]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(t) for t in parsed if str(t).strip()]
        except Exception:
            pass
        return [s.strip() for s in raw.split(",") if s.strip()]
    return []


def logical_record_id(record_id: str, meta: Dict[str, Any]) -> str:
    return meta.get("customId") or meta.get("parent_memory_id") or meta.get("id") or record_id


def parse_capture_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def query_terms(query: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9_-]*", query.lower()) if len(t) > 1]


def search_norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def lexical_score(query: str, terms: List[str], record: BrowserMemoryRecord) -> float:
    q = query.lower().strip()
    q_norm = search_norm(query)
    if not q:
        return 0.0
    title = (record.title or "").lower()
    summary = (record.summary or "").lower()
    source_app = (record.sourceApp or "").lower()
    source_url = (record.sourceUrl or "").lower()
    tags = " ".join(record.tags).lower()
    content_l = (record.content or "")[:30000].lower()
    haystack = f"{title}\n{summary}\n{source_app}\n{source_url}\n{tags}\n{content_l}"
    title_norm = search_norm(title)
    summary_norm = search_norm(summary)
    haystack_norm = search_norm(haystack)

    score = 0.0
    if title == q:
        score += 120.0
    if title_norm and title_norm == q_norm:
        score += 110.0
    if q in title:
        score += 80.0
    if q_norm and q_norm in title_norm:
        score += 70.0
    if q in summary:
        score += 25.0
    if q_norm and q_norm in summary_norm:
        score += 20.0
    if q in tags:
        score += 18.0
    if q in source_url or q == source_app:
        score += 10.0
    if q in haystack:
        score += 8.0
    if q_norm and q_norm in haystack_norm:
        score += 6.0

    if terms:
        title_hits = sum(1 for t in terms if t in title_norm)
        summary_hits = sum(1 for t in terms if t in summary_norm)
        body_hits = sum(1 for t in terms if t in haystack_norm)
        score += title_hits * 9.0
        score += summary_hits * 4.0
        score += (body_hits / max(len(terms), 1)) * 8.0
        if body_hits == len(terms):
            score += 6.0
    return score


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").lower() == "true"


def _safe_int(value: Any, default: int = 1) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _body_from_content(content: str) -> str:
    body_start = (content or "").find("\n\n")
    return content[body_start + 2:] if body_start >= 0 else (content or "")


def _record_state(
    *,
    meta: Dict[str, Any],
    raw: Optional[Dict[str, Any]],
    pipeline: Dict[str, Any],
    blueprint: Dict[str, Any],
) -> str:
    if raw and raw.get("transcript_deleted_at"):
        return "transcript_deleted"
    current_stage = pipeline.get("current_stage")
    current_state = pipeline.get("current_state")
    if current_state == "failed":
        return "failed"
    if blueprint.get("present"):
        return "blueprint_ready"
    if current_stage:
        return str(current_stage)
    if raw and not bool(raw.get("embedded")):
        return "indexing"
    if meta.get("state"):
        return str(meta.get("state"))
    return "captured"


def _blueprint_state(memory_id: str) -> Dict[str, Any]:
    present = False
    job_state = None
    last_error = None
    try:
        from apps.shail.blueprints import get_blueprint
        present = bool(get_blueprint(memory_id))
    except Exception:
        present = False
    try:
        from apps.shail.blueprint_queue import job_for_memory
        job = job_for_memory(memory_id)
        if job:
            job_state = job.get("state")
            last_error = job.get("last_error")
    except Exception:
        pass
    return {"present": present, "job_state": job_state, "last_error": last_error}


def _pipeline_state(memory_id: str) -> Dict[str, Any]:
    try:
        from apps.shail import pipeline_status as _ps
        return _ps.get_status(memory_id)
    except Exception:
        return {"memory_id": memory_id, "current_stage": None, "current_state": None, "stages": {}}


def _from_parts(
    *,
    record_id: str,
    content: str,
    meta: Dict[str, Any],
    namespace: str,
    raw: Optional[Dict[str, Any]] = None,
    score: Optional[float] = None,
) -> BrowserMemoryRecord:
    meta = normalize_browser_metadata(meta or {}, content or "")
    memory_id = raw.get("memory_id") if raw else logical_record_id(record_id, meta)
    memory_id = memory_id or meta.get("customId") or meta.get("id") or record_id or str(uuid.uuid4())
    if raw and raw.get("transcript_deleted_at"):
        content = ""
    title = meta.get("title") or ""
    if not title:
        m = re.match(r"^\[(\w+)\]\s+([^\n]+)", content or "")
        title = m.group(2).strip() if m else ""
    body = _body_from_content(content)
    summary = meta.get("summary") or body[:400] or "Pending memory indexing"
    timestamp = meta.get("timestamp") or (raw or {}).get("captured_at") or datetime.now(timezone.utc).isoformat()
    pipeline = _pipeline_state(memory_id)
    blueprint = _blueprint_state(memory_id)
    retention_policy = (raw or {}).get("retention_policy") or meta.get("retention_policy") or "keep_raw"
    if raw and raw.get("transcript_deleted_at"):
        retention_policy = "transcript_deleted"
    state = _record_state(meta=meta, raw=raw, pipeline=pipeline, blueprint=blueprint)
    confidence = _safe_float(meta.get("importance_score", meta.get("confidence")))
    if confidence is None:
        confidence = 0.5
    forget_after = meta.get("forgetAfter")
    is_forgotten = _safe_bool(meta.get("isForgotten"))
    if forget_after and not is_forgotten:
        try:
            fa_dt = datetime.fromisoformat(str(forget_after).replace("Z", "+00:00"))
            if fa_dt.tzinfo is None:
                fa_dt = fa_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > fa_dt:
                is_forgotten = True
        except Exception:
            pass

    return BrowserMemoryRecord(
        id=memory_id,
        customId=meta.get("customId") or memory_id,
        eventType=meta.get("eventType") or (raw or {}).get("content_type") or "page_visit",
        sourceApp=meta.get("sourceApp") or "web",
        sourceUrl=meta.get("sourceUrl") or "",
        title=title,
        summary=summary,
        timestamp=timestamp,
        content=content or "",
        tags=parse_tags(meta.get("tags")),
        pinned=_safe_bool(meta.get("pinned")),
        score=round(score, 4) if score else None,
        namespace=namespace or meta.get("namespace") or (raw or {}).get("namespace") or "",
        metadata=meta,
        conversationId=meta.get("conversationId") or "",
        captureMode=(raw or {}).get("capture_mode") or meta.get("capture_mode") or "active",
        captureSource=meta.get("capture_source") or "",
        retentionPolicy=retention_policy,
        transcriptDeletedAt=(raw or {}).get("transcript_deleted_at"),
        rawEmbedded=bool(raw.get("embedded")) if raw else None,
        rawBlueprinted=bool(raw.get("blueprinted")) if raw else None,
        segmentCount=(raw or {}).get("segment_count"),
        contentChars=(raw or {}).get("content_chars") or len(content or ""),
        pipeline=pipeline,
        blueprint=blueprint,
        state=state,
        isPending=state in {"indexing", "captured", "blueprint_queued", "blueprint_extracting"},
        isRecovered=_safe_bool(meta.get("recovered")) or _safe_bool(meta.get("legacy_recovered")),
        fidelity=_safe_float(meta.get("fidelity")),
        confidence=confidence,
        parentId=meta.get("parentId") or meta.get("parent_memory_id") or None,
        version=_safe_int(meta.get("version"), 1),
        forgetAfter=forget_after,
        isForgotten=is_forgotten,
        memoryRelations=meta.get("memoryRelations") or {},
    )


def list_records(
    namespaces: Iterable[str],
    *,
    limit: int = 5000,
    after: Optional[str] = None,
    source_app: Optional[str] = None,
) -> List[BrowserMemoryRecord]:
    records: Dict[str, BrowserMemoryRecord] = {}
    store = _get_store()
    namespaces = list(dict.fromkeys(ns for ns in namespaces if ns))

    if hasattr(store, "collection"):
        for namespace in namespaces:
            try:
                result = store.collection.get(
                    where={"namespace": namespace},
                    include=["documents", "metadatas"],
                    limit=limit,
                )
            except Exception:
                result = {"ids": [], "documents": [], "metadatas": []}
            for rid, doc, meta in zip(
                result.get("ids", []) or [],
                result.get("documents", []) or [],
                result.get("metadatas", []) or [],
            ):
                meta = meta or {}
                if not is_browser_memory(meta, doc or ""):
                    continue
                norm = normalize_browser_metadata(meta, doc or "")
                logical_id = logical_record_id(rid, norm)
                chunk_index = _safe_int(norm.get("chunk_index"), 0)
                current = records.get(logical_id)
                if current is None or chunk_index == 0:
                    records[logical_id] = _from_parts(
                        record_id=logical_id,
                        content=doc or "",
                        meta=norm,
                        namespace=namespace,
                    )

    try:
        from apps.shail import raw_transcripts as _rt
        for namespace in namespaces:
            for raw in _rt.list_recent(namespace=namespace, limit=limit, after=after):
                raw_id = raw.get("memory_id")
                if not raw_id:
                    continue
                content = raw.get("content") or ""
                meta = raw.get("metadata") or {}
                if not is_browser_memory(meta, content):
                    continue
                norm = normalize_browser_metadata(meta, content)
                norm.setdefault("customId", raw_id)
                norm.setdefault("id", raw_id)
                norm.setdefault("eventType", raw.get("content_type", "page_visit"))
                norm.setdefault("timestamp", raw.get("captured_at"))
                records[raw_id] = _from_parts(
                    record_id=raw_id,
                    content=content,
                    meta=norm,
                    namespace=namespace,
                    raw=raw,
                )
    except Exception:
        pass

    items = list(records.values())
    if after:
        items = [r for r in items if (r.timestamp or "") >= after]
    if source_app:
        items = [r for r in items if r.sourceApp == source_app]
    items.sort(key=lambda r: r.timestamp or "", reverse=True)
    return items


def get_record(memory_id: str, namespaces: Iterable[str]) -> Optional[BrowserMemoryRecord]:
    namespaces = list(dict.fromkeys(ns for ns in namespaces if ns))
    try:
        from apps.shail import raw_transcripts as _rt
        raw = _rt.get(memory_id)
        if raw and raw.get("namespace") in namespaces:
            content = raw.get("content") or ""
            meta = raw.get("metadata") or {}
            if is_browser_memory(meta, content):
                return _from_parts(
                    record_id=memory_id,
                    content=content,
                    meta=meta,
                    namespace=raw.get("namespace") or "",
                    raw=raw,
                )
    except Exception:
        pass

    store = _get_store()
    if not hasattr(store, "collection"):
        return None
    lookup_specs = [
        {"ids": [memory_id]},
        {"where": {"customId": memory_id}},
        {"where": {"parent_memory_id": memory_id}},
    ]
    for spec in lookup_specs:
        try:
            result = store.collection.get(
                **spec,
                include=["documents", "metadatas"],
            )
        except Exception:
            continue
        ids = result.get("ids", []) or []
        if not ids:
            continue
        rows = list(zip(
            ids,
            result.get("documents", []) or [],
            result.get("metadatas", []) or [],
        ))
        rows = [
            row for row in rows
            if (row[2] or {}).get("namespace", NS_BROWSER) in namespaces
            and is_browser_memory(row[2] or {}, row[1] or "")
        ]
        if not rows:
            continue
        rows.sort(key=lambda row: _safe_int((row[2] or {}).get("chunk_index"), 0))
        meta = normalize_browser_metadata(rows[0][2] or {}, rows[0][1] or "")
        logical_id = logical_record_id(rows[0][0], meta)
        content = "\n\n".join((doc or "") for _, doc, _ in rows)
        return _from_parts(
            record_id=logical_id,
            content=content,
            meta=meta,
            namespace=meta.get("namespace") or "",
        )
    return None


def find_latest_capture(
    namespaces: Iterable[str],
    *,
    memory_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    source_url: Optional[str] = None,
) -> Optional[BrowserMemoryRecord]:
    if memory_id:
        return get_record(memory_id, namespaces)
    items = list_records(namespaces)
    for item in items:
        if conversation_id and item.conversationId == conversation_id:
            return item
        if source_url and item.sourceUrl == source_url:
            return item
    return None


def search_records(
    namespaces: Iterable[str],
    *,
    query: str,
    k: int,
    after: Optional[str] = None,
    source_app: Optional[str] = None,
) -> List[BrowserMemoryRecord]:
    q = (query or "").strip()
    if not q:
        return list_records(namespaces, limit=5000, after=after, source_app=source_app)[:k]

    ranked: Dict[str, tuple[BrowserMemoryRecord, float]] = {}
    terms = query_terms(q)
    for record in list_records(namespaces, limit=5000, after=after, source_app=source_app):
        score = lexical_score(q, terms, record)
        if score > 0:
            record.score = round(score, 4)
            ranked[record.id] = (record, score)

    for namespace in namespaces:
        try:
            results = rag_search(query=q, k=min(max(k * 3, 50), 100), namespace=namespace)
        except Exception:
            continue
        for content, dist_score, metadata in results:
            if not is_browser_memory(metadata or {}, content or ""):
                continue
            metadata = normalize_browser_metadata(metadata or {}, content or "")
            record_id = logical_record_id(metadata.get("id") or str(uuid.uuid4()), metadata)
            existing = ranked.get(record_id)
            similarity = max(0.0, 1.0 - dist_score / 2.0)
            if existing:
                existing[0].score = round(existing[1] + similarity, 4)
                ranked[record_id] = (existing[0], existing[1] + similarity)
            else:
                record = get_record(record_id, namespaces) or _from_parts(
                    record_id=record_id,
                    content=content or "",
                    meta=metadata,
                    namespace=metadata.get("namespace") or namespace,
                    score=similarity,
                )
                record.score = round(similarity, 4)
                ranked[record_id] = (record, similarity)

    items = [item for item, _ in ranked.values()]
    items.sort(key=lambda r: (r.score or 0.0, r.timestamp or ""), reverse=True)
    return items[:k]
