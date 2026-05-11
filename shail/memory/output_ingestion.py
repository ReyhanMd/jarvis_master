"""Auto-ingest generated outputs (Phase 3).

Successful task outputs become retrievable memory.
Quality filtering + SHA-256 dedup prevent garbage and duplicates.
Fire-and-forget via IngestQueue — never on the hot path.

Usage (called by IngestQueue drain worker):
    ingestor = OutputIngestor()
    await ingestor.maybe_ingest(result, request)
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# In-memory dedup set (process-scoped). Persists across requests.
# On restart, SQLite/Chroma dedup naturally avoids re-embedding identical content.
_SEEN_HASHES: Set[str] = set()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _score_quality(result: Any) -> float:
    """Heuristic quality score in [0.0, 1.0].

    Weights (from settings defaults):
      has_artifacts: 0.3
      no_error:      0.4
      length:        0.3
    """
    from apps.shail.settings import get_settings
    weights = get_settings().memory_quality_score_weights

    score = 0.0

    # no_error
    w_no_err = weights.get("no_error", 0.4)
    status = str(getattr(result, "status", "")).lower()
    error  = getattr(result, "error", None)
    if not error and status not in ("failed", "error", "timeout"):
        score += w_no_err

    # has_artifacts
    w_art = weights.get("has_artifacts", 0.3)
    artifacts = getattr(result, "artifacts", None) or []
    if artifacts:
        score += w_art

    # length of summary
    w_len = weights.get("length", 0.3)
    summary = (
        getattr(result, "summary", "")
        or getattr(result, "content", "")
        or getattr(result, "output", "")
        or ""
    )
    char_count = len(str(summary))
    # >200 chars → full weight; 50-200 → partial; <50 → 0
    if char_count >= 200:
        score += w_len
    elif char_count >= 50:
        score += w_len * (char_count - 50) / 150

    return round(min(score, 1.0), 4)


def _extract_content(result: Any) -> str:
    """Best-effort content extraction from TaskResult."""
    parts: List[str] = []
    summary = getattr(result, "summary", "") or ""
    if summary:
        parts.append(str(summary))
    output = getattr(result, "output", "") or ""
    if output and output != summary:
        parts.append(str(output))
    return "\n\n".join(parts).strip()


def _build_metadata(result: Any, request: Any, tags: List[str], quality_score: float) -> Dict:
    return {
        "task_id":       getattr(result, "task_id", None),
        "generated_by":  getattr(result, "generated_by", None) or getattr(request, "agent_type", None),
        "mode":          getattr(request, "mode", None),
        "namespace":     getattr(request, "namespace", None) or getattr(request, "project", None),
        "tags":          tags,
        "quality_score": quality_score,
        "status":        getattr(result, "status", None),
        "auto_ingested": True,
    }


class OutputIngestor:
    """Quality-filter + dedup + ingest pipeline."""

    async def maybe_ingest(self, result: Any, request: Any) -> None:
        """Entry point called by IngestQueue for each completed task."""
        from apps.shail.settings import get_settings
        s = get_settings()

        if not s.ingest_generated_outputs:
            return

        # Quality gate
        quality = _score_quality(result)
        if quality < s.ingest_quality_threshold:
            logger.debug(
                "OutputIngestor: skip task %r — quality %.2f < threshold %.2f",
                getattr(result, "task_id", "?"), quality, s.ingest_quality_threshold,
            )
            return

        # Extract content
        content = _extract_content(result)
        if not content:
            logger.debug("OutputIngestor: skip task %r — empty content", getattr(result, "task_id", "?"))
            return

        # Dedup
        h = _content_hash(content)
        if h in _SEEN_HASHES:
            logger.debug("OutputIngestor: skip task %r — duplicate", getattr(result, "task_id", "?"))
            return
        _SEEN_HASHES.add(h)

        # Taxonomy tags (Phase 7)
        tags: List[str] = []
        if s.taxonomy_enabled:
            try:
                from shail.memory.taxonomy import get_taxonomy
                tags = get_taxonomy().classify(result, request)
            except Exception as exc:
                logger.debug("OutputIngestor: taxonomy classify failed: %s", exc)

        metadata = _build_metadata(result, request, tags, quality)
        namespace = metadata.get("namespace") or "default"

        # ── Local ingest ──────────────────────────────────────────────── #
        try:
            from shail.memory.rag import ingest as rag_ingest
            await self._ingest_local(rag_ingest, content, metadata, namespace, tags)
        except Exception as exc:
            logger.warning("OutputIngestor: local ingest failed for task %r: %s",
                           getattr(result, "task_id", "?"), exc)

        # ── Global ingest (SuperMemory) ──────────────────────────────── #
        if s.supermemory_use_global:
            try:
                from shail.memory.supermemory_client import get_supermemory_client
                sm = get_supermemory_client()
                mem_id = await sm.ingest_global(
                    content=content,
                    metadata=metadata,
                    container_tags=tags,
                    custom_id=h,
                )
                if mem_id:
                    logger.debug("OutputIngestor: global ingest OK — id=%s", mem_id)
            except Exception as exc:
                logger.warning("OutputIngestor: global ingest failed: %s", exc)

        logger.info(
            "OutputIngestor: ingested task %r quality=%.2f tags=%s ns=%s",
            getattr(result, "task_id", "?"), quality, tags[:5], namespace,
        )

    # ------------------------------------------------------------------ #

    async def _ingest_local(self, rag_ingest, content: str, metadata: Dict, namespace: str, tags: List[str]) -> None:
        """Ingest into local Chroma/PgVector. Handles both sync and async rag.ingest."""
        import asyncio
        record = {
            "content":    content,
            "metadata":   metadata,
            "namespace":  namespace,
            "tags":       tags,
        }
        # rag.ingest may be sync; wrap if needed
        if asyncio.iscoroutinefunction(rag_ingest):
            await rag_ingest(records=[record])
        else:
            await asyncio.to_thread(rag_ingest, records=[record])
