"""Retrieval strategy enums and global hit model (SuperMemory Phase 1).

Defines the shape of GlobalHit — the result type returned by
SupermemoryClient.query_global(). FusedHit in fusion.py accepts
GlobalHit as a third surface alongside exact and semantic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RetrievalStrategy(str, Enum):
    """Controls which retrieval surfaces are consulted."""
    LOCAL_ONLY   = "local_only"    # default — exact + semantic in Chroma/PgVector
    GLOBAL_ONLY  = "global_only"   # only SuperMemory REST API
    HYBRID       = "hybrid"        # local first, global fallback when local < threshold


@dataclass(frozen=True)
class GlobalHit:
    """A single result returned by SupermemoryClient from the global store.

    Shape mirrors SemanticHit (content, score, metadata) so fusion.fuse()
    can handle it without branching. The `source` field marks it as "global"
    for telemetry / provenance tracking.
    """
    memory_id: str
    content: str
    score: float                        # 0..1, cosine similarity from SuperMemory
    metadata: dict = field(default_factory=dict)
    source: str = "global"              # always "global"

    # SuperMemory-specific extras (preserved in metadata, not used by fusion)
    version: Optional[int] = None
    container_tag: Optional[str] = None

    def as_semantic_tuple(self) -> tuple:
        """Convert to legacy SemanticHit shape: (content, score, metadata)."""
        meta = dict(self.metadata)
        meta.setdefault("id",        self.memory_id)
        meta.setdefault("memory_id", self.memory_id)
        meta.setdefault("customId",  self.memory_id)
        meta.setdefault("surface",   "global")
        if self.container_tag:
            meta["container_tag"] = self.container_tag
        if self.version is not None:
            meta["version"] = self.version
        return (self.content, self.score, meta)
