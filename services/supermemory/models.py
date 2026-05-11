"""Pydantic request/response models for SuperMemory sidecar (Phase 4)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    q: str = Field(..., description="Search query")
    namespace: str = Field("default", description="Memory namespace / container tag")
    k: int = Field(5, ge=1, le=50, description="Number of results")
    strategy: str = Field("hybrid", description="local_only | global_only | hybrid")
    use_cache: bool = Field(True, description="Read from cache if available")


class MemoryHit(BaseModel):
    content: str
    score: float
    metadata: Dict[str, Any] = Field(default_factory=dict)
    surface: str = Field("unknown", description="exact | semantic | global")


class QueryResponse(BaseModel):
    hits: List[MemoryHit]
    total: int
    strategy_used: str
    cached: bool = False


class IngestRequest(BaseModel):
    content: str = Field(..., description="Text content to ingest")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    container_tags: List[str] = Field(default_factory=list)
    quality_score: float = Field(1.0, ge=0.0, le=1.0)
    generated_by: Optional[str] = None
    namespace: str = Field("default")


class IngestResponse(BaseModel):
    id: Optional[str] = None
    status: str  # ok | skipped | error
    message: Optional[str] = None


class HealthResponse(BaseModel):
    status: str  # ok | degraded | error
    local_rag: bool
    global_supermemory: bool
    cache: bool
    cache_backend: str


class StatsResponse(BaseModel):
    total_docs_local: int
    cache_size_bytes: int
    cache_backend: str
    supermemory_reachable: bool


class ReindexResponse(BaseModel):
    status: str
    message: str
