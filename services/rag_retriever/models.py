"""
Data models for RAG Retriever service
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class Document(BaseModel):
    """A document in the knowledge base"""
    
    id: str = Field(..., description="Unique document ID")
    content: str = Field(..., description="Document text content")
    namespace: str = Field(..., description="Namespace (git_docs, past_runs, etc)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    embedding: Optional[List[float]] = Field(None, description="Vector embedding")
    score: Optional[float] = Field(None, description="Relevance score (for retrieval results)")


class Query(BaseModel):
    """Query for document retrieval"""
    
    query: str = Field(..., description="Query text")
    namespace: Optional[str] = Field(None, description="Filter by namespace")
    top_k: int = Field(default=5, description="Number of results to return")
    min_score: float = Field(default=0.0, description="Minimum relevance score")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Additional filters")


class RetrievalResult(BaseModel):
    """Result of document retrieval"""
    
    query: str
    documents: List[Document]
    total_found: int
    retrieval_time_ms: float
    namespace: Optional[str] = None

