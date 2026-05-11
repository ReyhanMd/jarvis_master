"""Auto-ingest generated outputs (Phase 3 + Sprint 2 hardening).

Successful task outputs become retrievable memory.

Pipeline:
  1. Quality gate (heuristic score >= threshold)
  2. Provenance attached (source_type=agent, task_id, generated_by)
  3. Semantic dedup against per-namespace rolling window
  4. Local ingest into Chroma/PgVector
  5. Global ingest into SuperMemory (if flag on)
  6. Dead-letter on any persistent failure

Fire-and-forget via IngestQueue — never on the hot path.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _emit_counter(name: str, **labels) -> None:
    try:
        from apps.shail import telemetry
        telemetry.incr(name, **labels)
    except Exception:
        pass


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


def _build_metadata(
    result: Any,
    request: Any,
    tags: List[str],
    quality_score: float,
) -> Dict:
    """Build memory metadata with provenance attached."""
    from shail.memory.provenance import (
        SOURCE_AGENT, attach_provenance, build_provenance,
    )

    task_id      = getattr(result, "task_id", None)
    generated_by = getattr(result, "generated_by", None) or getattr(request, "agent_type", None)
    namespace    = getattr(request, "namespace", None) or getattr(request, "project", None)

    prov = build_provenance(
        source_type=SOURCE_AGENT,
        source_id=generated_by,
        generated_by=generated_by,
        creation_confidence=quality_score,
        task_id=task_id,
        generation_lineage=[generated_by] if generated_by else [],
    )

    base = {
        "task_id":       task_id,
        "generated_by":  generated_by,
        "mode":          getattr(request, "mode", None),
        "namespace":     namespace,
        "tags":          tags,
        "quality_score": quality_score,
        "status":        getattr(result, "status", None),
        "auto_ingested": True,
    }
    return attach_provenance(base, prov)


class OutputIngestor:
    """Quality-filter + provenance + semantic-dedup + ingest pipeline."""

    async def maybe_ingest(self, result: Any, request: Any) -> None:
        """Entry point called by IngestQueue for each completed task."""
        from apps.shail.settings import get_settings
        s = get_settings()

        if not s.ingest_generated_outputs:
            return

        task_label = getattr(result, "task_id", "?")

        # ── Quality gate ────────────────────────────────────────────── #
        quality = _score_quality(result)
        if quality < s.ingest_quality_threshold:
            logger.debug("OutputIngestor: skip task %r — quality %.2f < threshold %.2f",
                         task_label, quality, s.ingest_quality_threshold)
            _emit_counter("memory.ingest_rejected", status="quality")
            return

        # ── Content extraction ──────────────────────────────────────── #
        content = _extract_content(result)
        if not content:
            logger.debug("OutputIngestor: skip task %r — empty content", task_label)
            _emit_counter("memory.ingest_rejected", status="empty")
            return

        # ── Taxonomy tags ───────────────────────────────────────────── #
        tags: List[str] = []
        if s.taxonomy_enabled:
            try:
                from shail.memory.taxonomy import get_taxonomy
                tags = get_taxonomy().classify(result, request)
            except Exception as exc:
                logger.debug("OutputIngestor: taxonomy classify failed: %s", exc)

        metadata = _build_metadata(result, request, tags, quality)
        namespace = metadata.get("namespace") or "default"
        h = _content_hash(content)

        # ── Semantic dedup (pre-embed compute) ──────────────────────── #
        # Compute embedding once; reuse for dedup check + record-on-success.
        embedding: Optional[list] = None
        if getattr(s, "semantic_dedup_enabled", True):
            try:
                from shail.memory.embeddings import embed_texts
                import asyncio
                embedding = (await asyncio.to_thread(embed_texts, [content]))[0]
                from shail.memory.semantic_dedup import get_semantic_dedup
                dedup = get_semantic_dedup()
                is_dup, sim, matched = dedup.is_duplicate(content, namespace, embedding)
                if is_dup:
                    logger.debug("OutputIngestor: skip task %r — semantic dup sim=%.3f matched=%s",
                                 task_label, sim, (matched or "")[:12])
                    metadata["semantic_duplicate_score"] = sim
                    metadata["dedup_rejection_reason"] = "semantic" if sim < 1.0 else "exact_hash"
                    _emit_counter("memory.dedup_rejections", status=metadata["dedup_rejection_reason"])
                    _emit_counter("memory.ingest_rejected", status="dedup")
                    return
            except Exception as exc:
                logger.debug("OutputIngestor: dedup check failed (continuing): %s", exc)
                embedding = None

        # ── Local ingest ────────────────────────────────────────────── #
        local_ok = False
        try:
            from shail.memory.rag import ingest as rag_ingest
            await self._ingest_local(rag_ingest, content, metadata, namespace, tags)
            local_ok = True
            _emit_counter("memory.ingest_succeeded", status="local")
        except Exception as exc:
            logger.warning("OutputIngestor: local ingest failed for task %r: %s",
                           task_label, exc)
            self._dead_letter(content, metadata, namespace, f"local_ingest: {exc}")

        # Record in dedup window only after successful local ingest
        if local_ok and embedding is not None:
            try:
                from shail.memory.semantic_dedup import get_semantic_dedup
                get_semantic_dedup().record(content, namespace, embedding)
            except Exception:
                pass

        # ── Global ingest (SuperMemory) ─────────────────────────────── #
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
                    _emit_counter("memory.ingest_succeeded", status="global")
                    logger.debug("OutputIngestor: global ingest OK — id=%s", mem_id)
            except Exception as exc:
                logger.warning("OutputIngestor: global ingest failed: %s", exc)
                self._dead_letter(content, metadata, namespace, f"global_ingest: {exc}")

        logger.info("OutputIngestor: ingested task %r quality=%.2f tags=%s ns=%s",
                    task_label, quality, tags[:5], namespace)

    # ------------------------------------------------------------------ #

    async def _ingest_local(self, rag_ingest, content: str, metadata: Dict,
                            namespace: str, tags: List[str]) -> None:
        """Ingest into local Chroma/PgVector. Handles sync + async rag.ingest."""
        import asyncio
        record = {
            "content":    content,
            "metadata":   metadata,
            "namespace":  namespace,
            "tags":       tags,
        }
        if asyncio.iscoroutinefunction(rag_ingest):
            await rag_ingest(records=[record])
        else:
            await asyncio.to_thread(rag_ingest, records=[record])

    def _dead_letter(self, content: str, metadata: Dict, namespace: str, error: str) -> None:
        """Route failed ingests to the dead-letter queue."""
        try:
            from shail.memory.dead_letter import get_dead_letter_queue
            get_dead_letter_queue().record(content, metadata, error, namespace=namespace)
        except Exception as exc:
            logger.debug("OutputIngestor: dead-letter record failed: %s", exc)
