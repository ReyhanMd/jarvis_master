"""Embedding utilities for RAG (Gemini)."""

from typing import List
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    GENAI_AVAILABLE = False

from apps.shail.settings import get_settings


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""


def _configure():
    if not GENAI_AVAILABLE:
        raise EmbeddingError("google.generativeai is not installed. Install with: pip install google-generativeai")
    settings = get_settings()
    if not settings.gemini_api_key:
        raise EmbeddingError("GEMINI_API_KEY is missing for embeddings.")
    genai.configure(api_key=settings.gemini_api_key)
    return settings


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a list of texts using Gemini embeddings."""
    if not texts:
        return []
    settings = _configure()
    model = settings.rag_embedding_model
    embeddings: List[List[float]] = []
    for text in texts:
        try:
            resp = genai.embed_content(
                model=model,
                content=text,
                task_type="retrieval_document",
            )
            embedding = resp.get("embedding")
            if not embedding:
                raise EmbeddingError("Empty embedding returned.")
            embeddings.append(embedding)
        except Exception as exc:
            raise EmbeddingError(f"Failed to embed text: {exc}") from exc
    return embeddings


def embed_query(query: str) -> List[float]:
    """Embed a query string."""
    result = embed_texts([query])
    return result[0] if result else []
