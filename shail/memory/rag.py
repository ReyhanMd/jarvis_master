"""RAG (Retrieval-Augmented Generation) memory system for SHAIL."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional

from apps.shail.settings import get_settings
from shail.memory.embeddings import embed_texts, embed_query, EmbeddingError
from shail.memory.vector_store import (
    EmbeddingRecord,
    VectorStore,
    get_vector_store,
)

logger = logging.getLogger(__name__)

# Namespaces / collections
NS_TOOL_STATE = "tool_state"
NS_TOOL_USAGE = "tool_usage"
NS_PROJECT_CONTEXT = "project_context"
NS_ARCH_NOTES = "arch_notes"
NS_CODE = "code"
NS_LOGS = "logs"
NS_DOCS = "docs"

TEXT_EXTS = {".md", ".txt"}
CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".cpp", ".h", ".hpp", ".rs", ".go"}
LOG_EXTS = {".log"}

_vector_store: Optional[VectorStore] = None


def _get_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        settings = get_settings()
        _vector_store = get_vector_store(
            settings.rag_vector_store,
            dsn=settings.rag_pg_dsn,
            chroma_path=settings.rag_chroma_path,
            dim=settings.rag_embedding_dim,
        )
    return _vector_store


def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    if not text:
        return []
    chunks = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(text[start:end])
        if end == length:
            break
        start = max(0, end - overlap)
    return chunks


def _detect_namespace(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in CODE_EXTS:
        return NS_CODE
    if ext in LOG_EXTS:
        return NS_LOGS
    if ext in TEXT_EXTS:
        return NS_DOCS
    return NS_DOCS


def ingest(paths: Optional[List[str]] = None, records: Optional[List[Dict[str, Any]]] = None) -> int:
    """
    Ingest documents or records into the RAG system.
    
    Args:
        paths: List of file paths to ingest
        records: List of dict records with keys: content, namespace, metadata
        
    Returns:
        Number of chunks ingested
    """
    settings = get_settings()
    store = _get_store()
    chunk_size = settings.rag_chunk_size
    overlap = settings.rag_chunk_overlap

    embedding_records: List[EmbeddingRecord] = []

    # Handle file ingestion
    if paths:
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                namespace = _detect_namespace(path)
                chunks = _chunk_text(text, chunk_size, overlap)
                for idx, chunk in enumerate(chunks):
                    metadata = {
                        "file_path": path,
                        "chunk_id": idx,
                        "content_type": namespace,
                        "source": "file",
                    }
                    embedding_records.append(
                        EmbeddingRecord(
                            id=None,
                            namespace=namespace,
                            content=chunk,
                            metadata=metadata,
                            embedding=[],
                        )
                    )
            except Exception as exc:
                logger.warning("Failed to ingest %s: %s", path, exc)

    # Handle direct records (e.g., tool results)
    if records:
        for rec in records:
            content = rec.get("content", "")
            namespace = rec.get("namespace", NS_DOCS)
            metadata = rec.get("metadata", {}) or {}
            embedding_records.append(
                EmbeddingRecord(
                    id=rec.get("id"),
                    namespace=namespace,
                    content=content,
                    metadata=metadata,
                    embedding=[],
                )
            )

    if not embedding_records:
        return 0

    texts = [r.content for r in embedding_records]
    try:
        embeddings = embed_texts(texts)
    except EmbeddingError as exc:
        logger.error("Embedding failed: %s", exc)
        return 0

    for rec, emb in zip(embedding_records, embeddings):
        rec.embedding = emb
        # Ensure namespace in metadata for Chroma filter
        rec.metadata = rec.metadata or {}
        rec.metadata.setdefault("namespace", rec.namespace)

    store.upsert(embedding_records)
    return len(embedding_records)


def search(
    query: str,
    k: int = 5,
    namespace: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, float, Dict[str, Any]]]:
    """
    Search the RAG system for relevant context.
    
    Args:
        query: Search query
        k: Number of results to return
        namespace: Optional namespace/collection filter
        filters: Optional metadata filters (dict)
        
    Returns:
        List of (content, score, metadata)
    """
    store = _get_store()
    try:
        q_emb = embed_query(query)
    except EmbeddingError as exc:
        logger.error("Query embedding failed: %s", exc)
        return []

    results = store.query(q_emb, namespace=namespace, filters=filters, k=k)
    return [(r["content"], r.get("score", 0.0), r.get("metadata", {})) for r in results]


# Tool state integration
def store_tool_state_for_rag(
    tool_name: str,
    state: Dict[str, Any],
    result: Optional[Dict[str, Any]] = None,
    category: Optional[str] = None,
) -> int:
    """
    Store tool state in RAG memory.
    
    Args:
        tool_name: Name of the tool
        state: Current state of the tool
        result: Optional result from tool execution
        category: Optional category
        
    Returns:
        ID of the stored state
    """
    from shail.memory.tool_memory import store_tool_state
    state_id = store_tool_state(tool_name, state, result, category)
    try:
        ingest(
            records=[
                {
                    "namespace": NS_TOOL_STATE,
                    "content": json.dumps({"state": state, "result": result}),
                    "metadata": {
                        "tool_name": tool_name,
                        "category": category,
                        "record_id": state_id,
                        "content_type": NS_TOOL_STATE,
                        "source": "tool_state",
                    },
                }
            ]
        )
    except Exception as exc:
        logger.warning("RAG ingest for tool_state failed: %s", exc)
    return state_id


def get_tool_state_from_rag(tool_name: str) -> Optional[Dict[str, Any]]:
    """
    Get tool state from RAG memory.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        Tool state dictionary or None
    """
    from shail.memory.tool_memory import get_tool_state
    return get_tool_state(tool_name)


def log_tool_usage_for_rag(
    tool_name: str,
    arguments: Dict[str, Any],
    result: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    task_id: Optional[str] = None,
    category: Optional[str] = None,
) -> int:
    """
    Log tool usage in RAG memory.
    
    Args:
        tool_name: Name of the tool
        arguments: Arguments passed to the tool
        result: Optional result
        success: Whether execution was successful
        error_message: Optional error message
        task_id: Optional task ID
        category: Optional category
        
    Returns:
        ID of the logged usage
    """
    from shail.memory.tool_memory import log_tool_usage
    usage_id = log_tool_usage(
        tool_name, arguments, result, success, error_message, task_id, category
    )
    try:
        ingest(
            records=[
                {
                    "namespace": NS_TOOL_USAGE,
                    "content": json.dumps(
                        {
                            "arguments": arguments,
                            "result": result,
                            "success": success,
                            "error": error_message,
                        }
                    ),
                    "metadata": {
                        "tool_name": tool_name,
                        "task_id": task_id,
                        "category": category,
                        "record_id": usage_id,
                        "content_type": NS_TOOL_USAGE,
                        "source": "tool_usage",
                    },
                }
            ]
        )
    except Exception as exc:
        logger.warning("RAG ingest for tool_usage failed: %s", exc)
    return usage_id


# Project context integration
def store_project_context_for_rag(
    project_name: str,
    context_type: str,
    content: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Store project context in RAG memory.
    
    Args:
        project_name: Name of the project
        context_type: Type of context ('intent', 'config', 'pattern', 'note')
        content: Context content
        metadata: Optional metadata
        
    Returns:
        ID of the stored context
    """
    from shail.memory.project_context import store_project_context
    ctx_id = store_project_context(project_name, context_type, content, metadata)
    try:
        ingest(
            records=[
                {
                    "namespace": NS_PROJECT_CONTEXT,
                    "content": json.dumps(content),
                    "metadata": {
                        "project": project_name,
                        "context_type": context_type,
                        "record_id": ctx_id,
                        "content_type": NS_PROJECT_CONTEXT,
                        "source": "project_context",
                        **(metadata or {}),
                    },
                }
            ]
        )
    except Exception as exc:
        logger.warning("RAG ingest for project_context failed: %s", exc)
    return ctx_id


def get_project_context_from_rag(
    project_name: str,
    context_type: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Get project context from RAG memory.
    
    Args:
        project_name: Name of the project
        context_type: Optional filter by type
        limit: Maximum number of records
        
    Returns:
        List of context records
    """
    from shail.memory.project_context import get_project_context
    return get_project_context(project_name, context_type, limit)


def store_user_intent_for_rag(
    project_name: str,
    intent: str,
    details: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Store user intent in RAG memory.
    
    Args:
        project_name: Name of the project
        intent: Description of user intent
        details: Optional additional details
        
    Returns:
        ID of the stored intent
    """
    from shail.memory.project_context import store_user_intent
    intent_id = store_user_intent(project_name, intent, details)
    try:
        ingest(
            records=[
                {
                    "namespace": NS_PROJECT_CONTEXT,
                    "content": json.dumps({"intent": intent, **(details or {})}),
                    "metadata": {
                        "project": project_name,
                        "context_type": "intent",
                        "record_id": intent_id,
                        "content_type": NS_PROJECT_CONTEXT,
                        "source": "project_context",
                    },
                }
            ]
        )
    except Exception as exc:
        logger.warning("RAG ingest for user_intent failed: %s", exc)
    return intent_id


def store_tool_config_for_rag(
    project_name: str,
    tool_name: str,
    config: Dict[str, Any],
) -> int:
    """
    Store tool configuration in RAG memory.
    
    Args:
        project_name: Name of the project
        tool_name: Name of the tool
        config: Configuration dictionary
        
    Returns:
        ID of the stored config
    """
    from shail.memory.project_context import store_tool_config
    cfg_id = store_tool_config(project_name, tool_name, config)
    try:
        ingest(
            records=[
                {
                    "namespace": NS_PROJECT_CONTEXT,
                    "content": json.dumps({"tool_name": tool_name, "config": config}),
                    "metadata": {
                        "project": project_name,
                        "context_type": "config",
                        "record_id": cfg_id,
                        "content_type": NS_PROJECT_CONTEXT,
                        "source": "project_context",
                    },
                }
            ]
        )
    except Exception as exc:
        logger.warning("RAG ingest for tool_config failed: %s", exc)
    return cfg_id


def store_workflow_pattern_for_rag(
    project_name: str,
    pattern: Dict[str, Any],
    description: Optional[str] = None,
) -> int:
    """
    Store workflow pattern in RAG memory.
    
    Args:
        project_name: Name of the project
        pattern: Pattern dictionary
        description: Optional description
        
    Returns:
        ID of the stored pattern
    """
    from shail.memory.project_context import store_workflow_pattern
    pat_id = store_workflow_pattern(project_name, pattern, description)
    try:
        ingest(
            records=[
                {
                    "namespace": NS_PROJECT_CONTEXT,
                    "content": json.dumps({"pattern": pattern, "description": description}),
                    "metadata": {
                        "project": project_name,
                        "context_type": "pattern",
                        "record_id": pat_id,
                        "content_type": NS_PROJECT_CONTEXT,
                        "source": "project_context",
                    },
                }
            ]
        )
    except Exception as exc:
        logger.warning("RAG ingest for workflow_pattern failed: %s", exc)
    return pat_id


# Architecture notes integration
def store_architecture_note_for_rag(
    note_type: str,
    title: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Store architecture note in RAG memory.
    
    Args:
        note_type: Type of note ('module', 'dependency', 'integration', 'design')
        title: Title of the note
        content: Content of the note
        metadata: Optional metadata
        
    Returns:
        ID of the stored note
    """
    from shail.memory.project_context import store_architecture_note
    note_id = store_architecture_note(note_type, title, content, metadata)
    try:
        ingest(
            records=[
                {
                    "namespace": NS_ARCH_NOTES,
                    "content": content,
                    "metadata": {
                        "note_type": note_type,
                        "title": title,
                        "record_id": note_id,
                        "content_type": NS_ARCH_NOTES,
                        "source": "arch_notes",
                        **(metadata or {}),
                    },
                }
            ]
        )
    except Exception as exc:
        logger.warning("RAG ingest for architecture_note failed: %s", exc)
    return note_id


def get_architecture_notes_from_rag(
    note_type: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Get architecture notes from RAG memory.
    
    Args:
        note_type: Optional filter by type
        limit: Maximum number of records
        
    Returns:
        List of architecture note records
    """
    from shail.memory.project_context import get_architecture_notes
    return get_architecture_notes(note_type, limit)


