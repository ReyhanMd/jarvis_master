"""Phase 2.5 local RAG foundation.

This module gives browser memories, local-file pointers, and future MCP/cloud
sources one shared retrieval shape. It deliberately keeps local files
pointer-first: file content is read only for top hits at query time and is not
bulk-written into vector memory.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from apps.shail.auth_api import get_current_user
from apps.shail.browser_memory_model import (
    BrowserMemoryRecord,
    get_record as get_browser_record,
    list_records as list_browser_records,
    search_records as search_browser_records,
    visible_namespaces,
)
from apps.shail.settings import get_settings
from apps.shail import local_graph
from apps.shail import local_intelligence
from apps.shail import local_semantic_reasoning, local_semantics, local_semantics_jobs
from apps.shail.evidence_bundle import build_evidence_bundle
from apps.shail.grounded_answer import build_grounded_answer
from shail.memory import path_index


local_rag_router = APIRouter()

SourceKind = Literal["browser_memory", "local_file", "past_chat", "mcp", "web"]
PrivacyState = Literal["allowed", "blocked", "redacted"]
MatchReason = Literal["exact_title", "keyword", "semantic", "blueprint_fact", "local_file_fts"]
RelationKind = Literal[
    "derives",
    "updates",
    "extends",
    "mentions_entity",
    "same_source",
    "same_conversation",
    "same_workspace",
    "contains",
    "belongs_to_project",
    "has_topic",
    "same_content_as",
    "newer_than",
    "version_of",
    "nearby_in_folder",
    "has_content_hash",
    "mentions_person",
    "mentions_organization",
    "has_date",
    "has_task",
    "has_decision",
    "has_metric",
    "states_fact",
    "appears_in_section",
    "supports_answer",
    "contradicts",
    "supersedes",
    "same_claim_as",
]


class SourceDocument(BaseModel):
    id: str
    source_kind: SourceKind
    source_app: Optional[str] = None
    title: str
    uri: Optional[str] = None
    namespace: str
    updated_at: Optional[str] = None
    privacy_state: PrivacyState = "allowed"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MatchedChunk(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    score: float
    match_reason: MatchReason
    locator: Optional[Dict[str, Any]] = None
    citation_token: str


class RAGSearchResult(BaseModel):
    document: SourceDocument
    score: float
    matched_chunks: List[MatchedChunk] = Field(default_factory=list)


class GraphRelation(BaseModel):
    source_id: str
    target_id: str
    relation: RelationKind
    weight: float
    evidence: Optional[str] = None
    confidence: str = "INFERRED"
    source_path: Optional[str] = None


class LocalRAGSearchRequest(BaseModel):
    query: str = ""
    k: int = Field(default=10, ge=1, le=50)
    include_browser: bool = True
    include_local_files: bool = True
    include_past_chats: bool = False
    include_mcp: bool = False


class LocalRAGSearchResponse(BaseModel):
    items: List[RAGSearchResult]
    total: int


class LocalGraphBuildResponse(BaseModel):
    status: str
    source_count: int
    node_count: int
    edge_count: int


class LocalEvidenceRequest(BaseModel):
    query: str
    k: int = Field(default=8, ge=1, le=50)
    include_graph: bool = True


class LocalEvidenceResponse(BaseModel):
    evidence_bundle_id: str
    query: str
    direct_matches: List[Dict[str, Any]]
    graph_expansions: List[Dict[str, Any]]
    selected_files: List[Dict[str, Any]]
    suppressed_files: List[Dict[str, Any]]
    warnings: List[str]
    confidence: str
    prompt_context: str
    citations: List[Dict[str, Any]]
    semantic_facts: List[Dict[str, Any]] = Field(default_factory=list)
    semantic_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    semantic_entities: List[Dict[str, Any]] = Field(default_factory=list)
    semantic_warnings: List[str] = Field(default_factory=list)
    semantic_resolutions: List[Dict[str, Any]] = Field(default_factory=list)
    semantic_conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning_warnings: List[str] = Field(default_factory=list)


class LocalAnswerRequest(BaseModel):
    query: str
    k: int = Field(default=8, ge=1, le=50)
    include_graph: bool = True


class LocalAnswerResponse(BaseModel):
    answer: str
    confidence: str
    evidence_bundle_id: str
    query: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_summary: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)
    unresolved_conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    semantic_resolutions: List[Dict[str, Any]] = Field(default_factory=list)
    semantic_conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    quality_score: float = 0.0
    quality_signals: Dict[str, Any] = Field(default_factory=dict)
    prompt_context: str = ""


class LocalIntelligencePacketRequest(BaseModel):
    query: str
    scope: Optional[str] = None
    k: int = Field(default=12, ge=1, le=50)
    include_graph: bool = True
    include_semantics: bool = True
    include_reasoning: bool = True
    include_answer: bool = True


class LocalIntelligencePacketResponse(BaseModel):
    packet_id: str
    query: str
    answer: str
    confidence: str
    canonical_facts: List[Dict[str, Any]] = Field(default_factory=list)
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    gaps: List[Dict[str, Any]] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)
    recommended_next_actions: List[str] = Field(default_factory=list)
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    source_map: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    evidence_bundle_id: str = ""
    created_at: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LocalSemanticsBuildResponse(BaseModel):
    status: str
    files_seen: int
    processed: int
    skipped: int
    failed: int
    entities: int
    facts: int
    tasks: int
    metrics: int
    mode: str = "deterministic"
    job_id: Optional[str] = None
    queued: bool = False


class LocalSemanticsStatusResponse(BaseModel):
    files: Dict[str, int]
    entities: Dict[str, int]
    facts: int
    tasks: int
    last_extracted_at: Optional[float] = None
    latest_llm_enriched_at: Optional[float] = None
    extractor_version: str
    queue: Dict[str, Any] = Field(default_factory=dict)


class LocalSemanticsJobRequest(BaseModel):
    mode: str = Field(default="hybrid")
    limit: int = Field(default=500, ge=1, le=5000)
    force: bool = False
    model: Optional[str] = None


class LocalSemanticsJobResponse(BaseModel):
    job_id: str
    status: str
    mode: Optional[str] = None
    model: Optional[str] = None
    limit: Optional[int] = None
    force: bool = False
    files_seen: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    chunks_processed: int = 0
    entities: int = 0
    facts: int = 0
    tasks: int = 0
    warnings: List[str] = Field(default_factory=list)
    last_error: Optional[str] = None


class LocalReasoningBuildRequest(BaseModel):
    limit: int = Field(default=5000, ge=1, le=50000)
    force: bool = False


class LocalReasoningBuildResponse(BaseModel):
    status: str
    groups: int
    claims: int
    conflicts: int
    resolved: int
    unresolved: int


class LocalReasoningStatusResponse(BaseModel):
    groups: int
    claims: int
    conflicts: int
    resolved: int
    unresolved: int
    last_built_at: Optional[float] = None


class RepairAction(BaseModel):
    kind: str
    memory_id: Optional[str] = None
    detail: Dict[str, Any] = Field(default_factory=dict)


class RepairReport(BaseModel):
    dry_run: bool
    applied: bool
    raw_unembedded: int
    raw_unblueprinted: int
    stale_running_jobs: int
    vector_only_browser: int
    actions: List[RepairAction] = Field(default_factory=list)


def _conn() -> sqlite3.Connection:
    from apps.shail.auth_store import _conn as auth_conn
    return auth_conn()


def _semantic_job_response(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "mode": job.get("mode"),
        "model": job.get("model"),
        "limit": job.get("limit") or job.get("limit_files"),
        "force": bool(job.get("force")),
        "files_seen": int(job.get("files_seen") or 0),
        "files_processed": int(job.get("files_processed") or 0),
        "files_skipped": int(job.get("files_skipped") or 0),
        "files_failed": int(job.get("files_failed") or 0),
        "chunks_processed": int(job.get("chunks_processed") or 0),
        "entities": int(job.get("entities") or 0),
        "facts": int(job.get("facts") or 0),
        "tasks": int(job.get("tasks") or 0),
        "warnings": list(job.get("warnings") or []),
        "last_error": job.get("last_error"),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _terms(query: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9_.-]*", (query or "").lower()) if len(t) > 1]


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _window(content: str, query: str, *, max_chars: int = 900) -> str:
    text = _normalise_text(content)
    if len(text) <= max_chars:
        return text
    terms = _terms(query)
    lower = text.lower()
    hits = [lower.find(t) for t in terms if lower.find(t) >= 0]
    if not hits:
        return text[:max_chars].rstrip()
    center = min(hits)
    start = max(0, center - max_chars // 3)
    return text[start:start + max_chars].strip()


def _match_reason(query: str, title: str, content: str, *, fallback: MatchReason) -> MatchReason:
    q = (query or "").strip().lower()
    title_l = (title or "").lower()
    content_l = (content or "").lower()
    if q and q == title_l:
        return "exact_title"
    if q and q in title_l:
        return "exact_title"
    if any(t in content_l or t in title_l for t in _terms(query)):
        return "keyword"
    return fallback


def _browser_doc(record: BrowserMemoryRecord) -> SourceDocument:
    privacy: PrivacyState = "redacted" if record.retentionPolicy == "transcript_deleted" else "allowed"
    return SourceDocument(
        id=record.id,
        source_kind="browser_memory",
        source_app=record.sourceApp,
        title=record.title or record.sourceUrl or record.id,
        uri=record.sourceUrl,
        namespace=record.namespace or "",
        updated_at=record.timestamp,
        privacy_state=privacy,
        metadata={
            "conversation_id": record.conversationId,
            "capture_mode": record.captureMode,
            "capture_source": record.captureSource,
            "state": record.state,
            "tags": record.tags,
        },
    )


def _browser_chunk(record: BrowserMemoryRecord, query: str) -> MatchedChunk:
    content = record.content or record.summary or record.title or ""
    score = float(record.score or 0.0)
    reason = _match_reason(query, record.title, content, fallback="semantic")
    return MatchedChunk(
        chunk_id=f"{record.id}:raw:0",
        document_id=record.id,
        content=_window(content, query),
        score=score,
        match_reason=reason,
        locator={"source_url": record.sourceUrl, "conversation_id": record.conversationId},
        citation_token=f"{{{{cite:memory:{record.id}}}}}",
    )


def _local_file_doc(row: Dict[str, Any]) -> SourceDocument:
    blocked = path_index.is_denied(get_settings().path_index_db, row.get("path") or "")
    return SourceDocument(
        id=row.get("id") or row.get("path") or "",
        source_kind="local_file",
        source_app="local_files",
        title=row.get("title") or os.path.basename(row.get("path") or "") or "Untitled file",
        uri=row.get("path"),
        namespace="local_file",
        updated_at=str(row.get("mtime") or ""),
        privacy_state="blocked" if blocked else "allowed",
        metadata={
            "file_type": row.get("file_type"),
            "size_bytes": row.get("size_bytes"),
            "mtime": row.get("mtime"),
            "pointer_first": True,
        },
    )


def _local_file_result(query: str, hit: Any) -> RAGSearchResult:
    row = {
        "id": getattr(hit, "id", ""),
        "path": getattr(hit, "path", ""),
        "title": getattr(hit, "title", ""),
        "file_type": getattr(hit, "file_type", ""),
        "size_bytes": getattr(hit, "size_bytes", None),
        "mtime": getattr(hit, "mtime", None),
    }
    doc = _local_file_doc(row)
    score = float(getattr(hit, "score", 0.0) or 0.0)
    chunk = MatchedChunk(
        chunk_id=f"{doc.id}:snippet:0",
        document_id=doc.id,
        content=_window(getattr(hit, "snippet", "") or "", query),
        score=score,
        match_reason="local_file_fts",
        locator={"path": getattr(hit, "path", ""), "extractor": getattr(hit, "extractor_used", None)},
        citation_token=f"{{{{cite:local_file:{doc.id}}}}}",
    )
    return RAGSearchResult(document=doc, score=score, matched_chunks=[chunk])


def _local_file_row_result(
    query: str,
    row: Dict[str, Any],
    *,
    score: float,
    graph_reason: str,
    evidence: Optional[str] = None,
) -> RAGSearchResult:
    doc = _local_file_doc(row)
    meta = dict(doc.metadata)
    meta["graph_reason"] = graph_reason
    if evidence:
        meta["graph_evidence"] = evidence
    doc.metadata = meta
    snippet = row.get("summary_snippet") or row.get("title") or row.get("path") or ""
    chunk = MatchedChunk(
        chunk_id=f"{doc.id}:graph-snippet:0",
        document_id=doc.id,
        content=_window(snippet, query),
        score=score,
        match_reason="local_file_fts",
        locator={"path": row.get("path"), "graph_reason": graph_reason},
        citation_token=f"{{{{cite:local_file:{doc.id}}}}}",
    )
    return RAGSearchResult(document=doc, score=score, matched_chunks=[chunk])


def _init_relation_schema() -> None:
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS local_rag_relations (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                evidence TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (source_id, target_id, relation)
            );
        """)


def _upsert_relations(relations: Iterable[GraphRelation]) -> None:
    _init_relation_schema()
    with _conn() as con:
        for rel in relations:
            con.execute(
                """INSERT INTO local_rag_relations
                   (source_id, target_id, relation, weight, evidence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_id, target_id, relation) DO UPDATE SET
                     weight = excluded.weight,
                     evidence = excluded.evidence,
                     updated_at = excluded.updated_at""",
                (rel.source_id, rel.target_id, rel.relation, rel.weight, rel.evidence, _now()),
            )


def semantic_search(query: str, *, user_id: str, k: int = 10) -> List[RAGSearchResult]:
    namespaces = visible_namespaces(user_id)
    records = search_browser_records(namespaces, query=query, k=k)
    return [
        RAGSearchResult(
            document=_browser_doc(record),
            score=float(record.score or 0.0),
            matched_chunks=[_browser_chunk(record, query)],
        )
        for record in records
    ]


def lexical_search(query: str, *, user_id: str, k: int = 10) -> List[RAGSearchResult]:
    return semantic_search(query, user_id=user_id, k=k)


def get_document(document_id: str, *, user_id: str) -> Optional[SourceDocument]:
    record = get_browser_record(document_id, visible_namespaces(user_id))
    if record:
        return _browser_doc(record)
    row = path_index.get_by_id(get_settings().path_index_db, document_id)
    if row:
        return _local_file_doc(row)
    return None


def get_matched_chunks(document_id: str, query: str, *, user_id: str) -> List[MatchedChunk]:
    record = get_browser_record(document_id, visible_namespaces(user_id))
    if record:
        return [_browser_chunk(record, query)]
    row = path_index.get_by_id(get_settings().path_index_db, document_id)
    if not row:
        return []
    snippet = row.get("summary_snippet") or row.get("title") or row.get("path") or ""
    return [
        MatchedChunk(
            chunk_id=f"{document_id}:snippet:0",
            document_id=document_id,
            content=_window(snippet, query),
            score=0.5,
            match_reason="local_file_fts",
            locator={"path": row.get("path")},
            citation_token=f"{{{{cite:local_file:{document_id}}}}}",
        )
    ]


def _raw_backlog(limit: int = 5000) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    from apps.shail import raw_transcripts as _rt
    from apps.shail.blueprints import get_blueprint

    raw_rows = _rt.list_recent(limit=limit)
    unembedded = [row for row in raw_rows if not bool(row.get("embedded"))]
    unblueprinted = [
        row for row in raw_rows
        if not bool(row.get("blueprinted")) and not get_blueprint(row.get("memory_id") or "")
    ]
    return unembedded, unblueprinted


def _stale_running_jobs(*, older_than_seconds: int = 1800, limit: int = 500) -> List[Dict[str, Any]]:
    from apps.shail.blueprint_queue import list_jobs

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    stale: List[Dict[str, Any]] = []
    for job in list_jobs("running", limit=limit):
        raw = job.get("updated_at") or job.get("created_at")
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = cutoff - timedelta(seconds=1)
        if dt <= cutoff:
            stale.append(job)
    return stale


def _vector_only_browser(user_id: str, *, limit: int = 5000) -> List[Dict[str, Any]]:
    from apps.shail import raw_transcripts as _rt
    from apps.shail.browser_memory_model import logical_record_id
    from apps.shail.source_normalization import is_browser_memory, normalize_browser_metadata
    from shail.memory.rag import _get_store

    raw_ids = {row.get("memory_id") for row in _rt.list_recent(limit=limit)}
    out: List[Dict[str, Any]] = []
    store = _get_store()
    if not hasattr(store, "collection"):
        return out
    for namespace in visible_namespaces(user_id):
        try:
            result = store.collection.get(
                where={"namespace": namespace},
                include=["documents", "metadatas"],
                limit=limit,
            )
        except Exception:
            continue
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
            if logical_id in raw_ids:
                continue
            out.append({"id": logical_id, "title": norm.get("title"), "namespace": namespace})
    return out


def repair_index(
    *,
    user_id: str,
    dry_run: bool = True,
    apply: bool = False,
    max_items: int = 25,
    stale_after_seconds: int = 1800,
) -> RepairReport:
    from apps.shail import raw_transcripts as _rt
    from apps.shail.blueprint_queue import enqueue, reset_stale_running_jobs
    from shail.memory.rag import ingest

    should_apply = bool(apply and not dry_run)
    unembedded, unblueprinted = _raw_backlog()
    stale_jobs = _stale_running_jobs(older_than_seconds=stale_after_seconds)
    vector_only = _vector_only_browser(user_id)
    actions: List[RepairAction] = []

    if should_apply:
        for row in unembedded[:max_items]:
            memory_id = row.get("memory_id")
            if not memory_id:
                continue
            meta = row.get("metadata") or {}
            meta.setdefault("customId", memory_id)
            meta.setdefault("id", memory_id)
            written = ingest(records=[{
                "id": memory_id,
                "namespace": row.get("namespace") or user_id,
                "content": row.get("content") or "",
                "metadata": meta,
            }])
            if written:
                _rt.mark_embedded(memory_id, True)
                actions.append(RepairAction(kind="reembedded_raw", memory_id=memory_id, detail={"chunks": written}))

        for row in unblueprinted[:max_items]:
            memory_id = row.get("memory_id")
            if not memory_id:
                continue
            job_id = enqueue(
                memory_id,
                session_id=None,
                user_id=row.get("user_id") or user_id,
                content_type=row.get("content_type") or "ai_conversation",
                priority=-1,
            )
            actions.append(RepairAction(kind="queued_blueprint", memory_id=memory_id, detail={"job_id": job_id}))

        reset_count = reset_stale_running_jobs(older_than_seconds=stale_after_seconds, limit=max_items)
        if reset_count:
            actions.append(RepairAction(kind="reset_stale_blueprint_jobs", detail={"count": reset_count}))

    else:
        for row in unembedded[:max_items]:
            actions.append(RepairAction(kind="would_reembed_raw", memory_id=row.get("memory_id"), detail={}))
        for row in unblueprinted[:max_items]:
            actions.append(RepairAction(kind="would_queue_blueprint", memory_id=row.get("memory_id"), detail={}))
        for job in stale_jobs[:max_items]:
            actions.append(RepairAction(kind="would_reset_stale_blueprint_job", memory_id=job.get("memory_id"), detail={"job_id": job.get("id")}))
        for row in vector_only[:max_items]:
            actions.append(RepairAction(kind="vector_only_browser_record", memory_id=row.get("id"), detail={"title": row.get("title")}))

    return RepairReport(
        dry_run=not should_apply,
        applied=should_apply,
        raw_unembedded=len(unembedded),
        raw_unblueprinted=len(unblueprinted),
        stale_running_jobs=len(stale_jobs),
        vector_only_browser=len(vector_only),
        actions=actions,
    )


def _graph_relations_for(records: List[BrowserMemoryRecord]) -> List[GraphRelation]:
    relations: Dict[tuple[str, str, str], GraphRelation] = {}

    by_conversation: Dict[str, List[BrowserMemoryRecord]] = {}
    by_source: Dict[str, List[BrowserMemoryRecord]] = {}
    for record in records:
        if record.conversationId:
            by_conversation.setdefault(record.conversationId, []).append(record)
        if record.sourceUrl:
            by_source.setdefault(record.sourceUrl, []).append(record)

    for group in by_conversation.values():
        group.sort(key=lambda r: r.timestamp or "")
        for prev, cur in zip(group, group[1:]):
            key = (prev.id, cur.id, "updates")
            relations[key] = GraphRelation(
                source_id=prev.id,
                target_id=cur.id,
                relation="updates",
                weight=1.0,
                evidence="same conversation recapture/update chain",
            )
        for item in group[1:]:
            first = group[0]
            if item.id != first.id:
                key = (first.id, item.id, "same_conversation")
                relations[key] = GraphRelation(
                    source_id=first.id,
                    target_id=item.id,
                    relation="same_conversation",
                    weight=0.85,
                    evidence=f"conversation_id={item.conversationId}",
                )

    for group in by_source.values():
        if len(group) < 2:
            continue
        first = group[0]
        for item in group[1:]:
            if item.id == first.id:
                continue
            key = (first.id, item.id, "same_source")
            relations[key] = GraphRelation(
                source_id=first.id,
                target_id=item.id,
                relation="same_source",
                weight=0.65,
                evidence=first.sourceUrl,
            )

    try:
        from apps.shail.blueprints import get_blueprints_for_ids
        blueprints = get_blueprints_for_ids([r.id for r in records])
    except Exception:
        blueprints = {}
    for record in records:
        bp = blueprints.get(record.id) or {}
        entities = bp.get("key_entities") or []
        facts = bp.get("facts") or []
        for entity in list(entities)[:8]:
            name = str(entity).strip()
            if not name:
                continue
            target = f"entity:{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}"
            relations[(record.id, target, "mentions_entity")] = GraphRelation(
                source_id=record.id,
                target_id=target,
                relation="mentions_entity",
                weight=0.75,
                evidence=name,
            )
        for fact in list(facts)[:8]:
            if not isinstance(fact, dict):
                continue
            entity = str(fact.get("entity") or "").strip()
            if not entity:
                continue
            target = f"entity:{re.sub(r'[^a-z0-9]+', '-', entity.lower()).strip('-')}"
            evidence = " ".join(str(fact.get(k) or "") for k in ("attribute", "value")).strip()
            relations[(record.id, target, "mentions_entity")] = GraphRelation(
                source_id=record.id,
                target_id=target,
                relation="mentions_entity",
                weight=0.9,
                evidence=evidence or entity,
            )

    return list(relations.values())


def get_graph_neighbors(document_id: str, *, user_id: str, limit: int = 50) -> Dict[str, Any]:
    del user_id
    return local_graph.graph_neighbors(document_id, limit=limit)


def build_local_graph(*, user_id: str, limit: int = 250) -> Dict[str, Any]:
    local_file_graph = local_graph.build_local_file_graph(limit=limit)
    records = list_browser_records(visible_namespaces(user_id), limit=limit)
    nodes = [
        {
            "id": record.id,
            "type": "browser_memory",
            "title": record.title,
            "source_app": record.sourceApp,
            "uri": record.sourceUrl,
            "state": record.state,
        }
        for record in records
    ]

    nodes.extend(local_file_graph["nodes"])

    relations = _graph_relations_for(records)
    _upsert_relations(relations)
    local_relations = local_file_graph["relations"]
    return {
        "nodes": nodes,
        "relations": [rel.model_dump() for rel in relations] + local_relations,
    }


@local_rag_router.post("/search", response_model=LocalRAGSearchResponse)
async def local_rag_search(
    req: LocalRAGSearchRequest,
    user_id: str = Depends(get_current_user),
) -> LocalRAGSearchResponse:
    items: List[RAGSearchResult] = []
    if req.include_browser:
        items.extend(semantic_search(req.query, user_id=user_id, k=req.k))
    if req.include_local_files and req.query.strip():
        from apps.shail.retrieval.local_files import retrieve_local_file_context
        file_hits = retrieve_local_file_context(req.query, k=req.k)
        direct_results = [_local_file_result(req.query, hit) for hit in file_hits]
        items.extend(direct_results)

        seen_doc_ids = {item.document.id for item in items}
        for direct in direct_results[:3]:
            for related in local_graph.related_local_file_ids(direct.document.id, limit=3):
                rid = related["id"]
                if rid in seen_doc_ids:
                    continue
                row = path_index.get_by_id(get_settings().path_index_db, rid)
                if not row:
                    continue
                seen_doc_ids.add(rid)
                items.append(_local_file_row_result(
                    req.query,
                    row,
                    score=max(0.05, direct.score * 0.65),
                    graph_reason=related.get("graph_reason") or "graph_neighbor",
                    evidence=related.get("evidence"),
                ))

    items.sort(key=lambda item: item.score, reverse=True)
    items = items[:req.k]
    return LocalRAGSearchResponse(items=items, total=len(items))


@local_rag_router.get("/status")
async def local_rag_status(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    from apps.shail import raw_transcripts as _rt
    from apps.shail.blueprint_queue import stats as blueprint_stats
    from apps.shail.retrieval import diagnostics as _diag

    settings = get_settings()
    unembedded, unblueprinted = _raw_backlog()
    stale_jobs = _stale_running_jobs()
    try:
        path_index_status = {
            **path_index.stats(settings.path_index_db),
            "blocked_paths": path_index.list_deny_paths(settings.path_index_db),
            "roots": path_index.list_roots(settings.path_index_db),
            "status": "ok",
        }
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower():
            raise
        path_index_status = {
            "total": 0,
            "total_files": 0,
            "total_dirs": 0,
            "by_type": {},
            "by_kind": {},
            "embedded": 0,
            "last_indexed_at": None,
            "blocked_paths": [],
            "roots": [],
            "status": "busy",
            "warning": "Path index database is busy; a scan or graph build is probably running.",
        }
    return {
        "repair_backlog": {
            "raw_total": _rt.stats().get("total", 0),
            "raw_unembedded": len(unembedded),
            "raw_unblueprinted": len(unblueprinted),
            "stale_running_blueprint_jobs": len(stale_jobs),
            "vector_only_browser": len(_vector_only_browser(user_id)),
        },
        "path_index": path_index_status,
        "blueprint_queue": blueprint_stats(),
        "extractor_diagnostics": _diag.health_summary(),
        "privacy_defaults": {
            "local_files": "pointer_first",
            "blocked_paths_override": ["scan", "search", "open", "content", "ask", "mcp_tools", "graph"],
        },
    }


@local_rag_router.post("/repair", response_model=RepairReport)
async def local_rag_repair(
    dry_run: Optional[bool] = Query(default=None),
    apply: bool = Query(default=False),
    max_items: int = Query(default=25, ge=1, le=250),
    stale_after_seconds: int = Query(default=1800, ge=60, le=86400),
    user_id: str = Depends(get_current_user),
) -> RepairReport:
    effective_dry_run = bool(dry_run) if dry_run is not None else not apply
    return repair_index(
        user_id=user_id,
        dry_run=effective_dry_run,
        apply=apply,
        max_items=max_items,
        stale_after_seconds=stale_after_seconds,
    )


@local_rag_router.post("/evidence", response_model=LocalEvidenceResponse)
async def local_rag_evidence(
    req: LocalEvidenceRequest,
    user_id: str = Depends(get_current_user),
) -> LocalEvidenceResponse:
    settings = get_settings()
    bundle = build_evidence_bundle(
        req.query,
        user_id=user_id,
        k=req.k,
        include_graph=req.include_graph,
        max_direct_files=min(req.k, settings.shail_local_files_k),
        max_graph_neighbors=3,
        max_total_evidence=req.k,
        max_snippet_chars=settings.shail_local_files_snippet_chars,
        read_cap_bytes=settings.shail_local_files_read_cap_bytes,
    )
    return LocalEvidenceResponse(**bundle.to_dict())


@local_rag_router.post("/answer", response_model=LocalAnswerResponse)
async def local_rag_answer(
    req: LocalAnswerRequest,
    user_id: str = Depends(get_current_user),
) -> LocalAnswerResponse:
    answer = build_grounded_answer(
        req.query,
        user_id=user_id,
        k=req.k,
        include_graph=req.include_graph,
    )
    return LocalAnswerResponse(**answer.to_dict())


@local_rag_router.post("/intelligence/packet", response_model=LocalIntelligencePacketResponse)
async def local_rag_intelligence_packet(
    req: LocalIntelligencePacketRequest,
    user_id: str = Depends(get_current_user),
) -> LocalIntelligencePacketResponse:
    packet = local_intelligence.build_intelligence_packet(
        req.query,
        user_id=user_id,
        scope=req.scope,
        k=req.k,
        include_graph=req.include_graph,
        include_semantics=req.include_semantics,
        include_reasoning=req.include_reasoning,
        include_answer=req.include_answer,
    )
    return LocalIntelligencePacketResponse(**packet.to_dict())


@local_rag_router.get("/intelligence/status")
async def local_rag_intelligence_status(
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    del user_id
    return local_intelligence.status()


@local_rag_router.get("/intelligence/facts/search")
async def local_rag_intelligence_facts_search(
    q: str = "",
    limit: int = Query(default=50, ge=1, le=250),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    del user_id
    return local_intelligence.search_canonical_facts(q, limit=limit)


@local_rag_router.get("/intelligence/packet/{packet_id}", response_model=LocalIntelligencePacketResponse)
async def local_rag_intelligence_packet_get(
    packet_id: str,
    user_id: str = Depends(get_current_user),
) -> LocalIntelligencePacketResponse:
    del user_id
    packet = local_intelligence.get_packet(packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Intelligence packet not found")
    return LocalIntelligencePacketResponse(**packet)


@local_rag_router.post("/semantics/build", response_model=LocalSemanticsBuildResponse)
async def local_rag_semantics_build(
    limit: int = Query(default=500, ge=1, le=5000),
    force: bool = Query(default=False),
    mode: str = Query(default="deterministic"),
    model: Optional[str] = Query(default=None),
    user_id: str = Depends(get_current_user),
) -> LocalSemanticsBuildResponse:
    del user_id
    mode = mode if mode in {"deterministic", "llm", "hybrid"} else "deterministic"
    if mode in {"llm", "hybrid"}:
        job = local_semantics_jobs.enqueue_job(mode=mode, limit=limit, force=force, model=model)
        return LocalSemanticsBuildResponse(
            status=job.get("status") or "pending",
            files_seen=int(job.get("files_seen") or 0),
            processed=int(job.get("files_processed") or 0),
            skipped=int(job.get("files_skipped") or 0),
            failed=int(job.get("files_failed") or 0),
            entities=int(job.get("entities") or 0),
            facts=int(job.get("facts") or 0),
            tasks=int(job.get("tasks") or 0),
            metrics=0,
            mode=mode,
            job_id=job.get("job_id"),
            queued=True,
        )
    result = local_semantics.build_semantics(limit=limit, force=force)
    return LocalSemanticsBuildResponse(**result, mode="deterministic", queued=False)


@local_rag_router.post("/semantics/jobs", response_model=LocalSemanticsJobResponse)
async def local_rag_semantics_job_create(
    req: LocalSemanticsJobRequest,
    user_id: str = Depends(get_current_user),
) -> LocalSemanticsJobResponse:
    del user_id
    job = local_semantics_jobs.enqueue_job(
        mode=req.mode,
        limit=req.limit,
        force=req.force,
        model=req.model,
    )
    return LocalSemanticsJobResponse(**_semantic_job_response(job))


@local_rag_router.get("/semantics/jobs/{job_id}", response_model=LocalSemanticsJobResponse)
async def local_rag_semantics_job_get(
    job_id: str,
    user_id: str = Depends(get_current_user),
) -> LocalSemanticsJobResponse:
    del user_id
    job = local_semantics_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Semantic job not found")
    return LocalSemanticsJobResponse(**_semantic_job_response(job))


@local_rag_router.post("/semantics/jobs/{job_id}/cancel", response_model=LocalSemanticsJobResponse)
async def local_rag_semantics_job_cancel(
    job_id: str,
    user_id: str = Depends(get_current_user),
) -> LocalSemanticsJobResponse:
    del user_id
    job = local_semantics_jobs.cancel_job(job_id)
    if job.get("status") == "missing":
        raise HTTPException(status_code=404, detail="Semantic job not found")
    return LocalSemanticsJobResponse(**_semantic_job_response(job))


@local_rag_router.get("/semantics/status", response_model=LocalSemanticsStatusResponse)
async def local_rag_semantics_status(
    user_id: str = Depends(get_current_user),
) -> LocalSemanticsStatusResponse:
    del user_id
    return LocalSemanticsStatusResponse(**local_semantics.status())


@local_rag_router.post("/semantics/reasoning/build", response_model=LocalReasoningBuildResponse)
async def local_rag_semantics_reasoning_build(
    req: LocalReasoningBuildRequest,
    user_id: str = Depends(get_current_user),
) -> LocalReasoningBuildResponse:
    del user_id
    return LocalReasoningBuildResponse(**local_semantic_reasoning.build_reasoning(
        limit=req.limit,
        force=req.force,
    ))


@local_rag_router.get("/semantics/reasoning/status", response_model=LocalReasoningStatusResponse)
async def local_rag_semantics_reasoning_status(
    user_id: str = Depends(get_current_user),
) -> LocalReasoningStatusResponse:
    del user_id
    return LocalReasoningStatusResponse(**local_semantic_reasoning.status())


@local_rag_router.get("/semantics/reasoning/search")
async def local_rag_semantics_reasoning_search(
    q: str = "",
    limit: int = Query(default=50, ge=1, le=250),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    del user_id
    return local_semantic_reasoning.search(q, limit=limit)


@local_rag_router.get("/semantics/reasoning/conflicts")
async def local_rag_semantics_reasoning_conflicts(
    limit: int = Query(default=50, ge=1, le=250),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    del user_id
    return local_semantic_reasoning.conflicts(limit=limit)


@local_rag_router.get("/semantics/reasoning/group/{group_id}")
async def local_rag_semantics_reasoning_group(
    group_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    del user_id
    group = local_semantic_reasoning.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Semantic reasoning group not found")
    return group


@local_rag_router.get("/semantics/search")
async def local_rag_semantics_search(
    q: str = "",
    limit: int = Query(default=50, ge=1, le=250),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    del user_id
    return local_semantics.search(q, limit=limit)


@local_rag_router.get("/semantics/file/{file_id}")
async def local_rag_semantics_file(
    file_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    del user_id
    return local_semantics.for_file(file_id)


@local_rag_router.get("/graph")
async def local_rag_graph(
    limit: int = Query(default=250, ge=1, le=1000),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    return build_local_graph(user_id=user_id, limit=limit)


@local_rag_router.post("/graph/build", response_model=LocalGraphBuildResponse)
async def local_rag_graph_build(
    limit: int = Query(default=1000, ge=1, le=5000),
    user_id: str = Depends(get_current_user),
) -> LocalGraphBuildResponse:
    del user_id
    graph = local_graph.build_local_file_graph(limit=limit)
    return LocalGraphBuildResponse(
        status="complete",
        source_count=int(graph.get("source_count") or 0),
        node_count=len(graph["nodes"]),
        edge_count=len(graph["relations"]),
    )


@local_rag_router.get("/graph/neighbors/{node_id}")
async def local_rag_graph_neighbors(
    node_id: str,
    limit: int = Query(default=50, ge=1, le=250),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    del user_id
    return local_graph.graph_neighbors(node_id, limit=limit)


@local_rag_router.get("/graph/search")
async def local_rag_graph_search(
    q: str = "",
    limit: int = Query(default=25, ge=1, le=100),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    del user_id
    return local_graph.graph_search(q, limit=limit)
