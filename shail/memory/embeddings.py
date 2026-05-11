"""Embeddings via local Ollama (nomic-embed-text). No external API keys required."""

from __future__ import annotations

import logging
from typing import List

import httpx

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    pass


def _settings():
    from apps.shail.settings import get_settings
    return get_settings()


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed batch of texts via Ollama nomic-embed-text. Returns list of float vectors."""
    if not texts:
        return []
    s = _settings()
    try:
        resp = httpx.post(
            f"{s.ollama_base_url}/api/embed",
            json={"model": s.ollama_embed_model, "input": texts},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings") or data.get("embedding")
        if embeddings is None:
            raise EmbeddingError(f"Unexpected Ollama response: {data}")
        # Ollama returns flat list for single input — normalise to list-of-lists
        if embeddings and not isinstance(embeddings[0], list):
            embeddings = [embeddings]
        return embeddings
    except httpx.ConnectError:
        logger.warning("Ollama not reachable at %s — returning zero vectors", s.ollama_base_url)
        return [[0.0] * s.ollama_embed_dim for _ in texts]
    except Exception as e:
        logger.warning("embed_texts failed: %s", e)
        return [[0.0] * s.ollama_embed_dim for _ in texts]


def embed_query(query: str) -> List[float]:
    """Embed single query string."""
    results = embed_texts([query])
    return results[0] if results else []


def is_zero_vector(embedding: List[float]) -> bool:
    """True if every component is ~0. embed_texts returns these on Ollama
    failure; upserting them poisons Chroma with records that match nothing.
    """
    if not embedding:
        return True
    return all(abs(v) < 1e-9 for v in embedding)
