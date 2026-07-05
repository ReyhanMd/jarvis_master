"""Embeddings via local Ollama (nomic-embed-text). No external API keys required.

Sprint 7: process-local LRU cache keyed by sha256(text) skips re-embedding on
backfill resume and re-runs. Cache is RAM-bounded; zero vectors are not cached
(so a transient Ollama outage doesn't poison the cache).
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from threading import Lock
from typing import List

import httpx

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    pass


def _settings():
    from apps.shail.settings import get_settings
    return get_settings()


# ── Sprint 7: process-local embedding cache ─────────────────────────────────

_EMBED_CACHE_MAX = 10_000  # entries; ~40 MB at 768-dim float32

class _LRUEmbedCache:
    def __init__(self, max_size: int = _EMBED_CACHE_MAX) -> None:
        self._cache: "OrderedDict[str, List[float]]" = OrderedDict()
        self._max = max_size
        self._lock = Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

    def get(self, text: str) -> List[float] | None:
        k = self.key(text)
        with self._lock:
            vec = self._cache.get(k)
            if vec is not None:
                self._cache.move_to_end(k)
                self.hits += 1
                return list(vec)
            self.misses += 1
            return None

    def put(self, text: str, vec: List[float]) -> None:
        if not vec:
            return
        # Don't cache zero vectors — these signal embedder failure, not a real
        # representation. Caching them would block future correct results.
        if all(abs(v) < 1e-9 for v in vec):
            return
        k = self.key(text)
        with self._lock:
            self._cache[k] = list(vec)
            self._cache.move_to_end(k)
            while len(self._cache) > self._max:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._cache),
                "max": self._max,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": (self.hits / (self.hits + self.misses)) if (self.hits + self.misses) else 0.0,
            }


_embed_cache = _LRUEmbedCache()


def embedding_cache_stats() -> dict:
    return _embed_cache.stats()


def clear_embedding_cache() -> None:
    _embed_cache.clear()


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed batch of texts via Ollama nomic-embed-text. Returns list of float vectors.

    Sprint 7: cached by sha256(text). Cache hits skip the HTTP round-trip.
    Only the misses are sent to Ollama; results are merged back in order.
    """
    if not texts:
        return []
    s = _settings()

    # Cache lookup
    results: List[List[float] | None] = [_embed_cache.get(t) for t in texts]
    miss_indices = [i for i, r in enumerate(results) if r is None]
    if not miss_indices:
        return [r for r in results]  # type: ignore[return-value]

    miss_texts = [texts[i] for i in miss_indices]
    try:
        resp = httpx.post(
            f"{s.ollama_base_url}/api/embed",
            json={"model": s.ollama_embed_model, "input": miss_texts},
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
        # Fill the misses + populate cache
        for slot_i, emb in zip(miss_indices, embeddings):
            results[slot_i] = emb
            _embed_cache.put(texts[slot_i], emb)
        return results  # type: ignore[return-value]
    except httpx.ConnectError:
        logger.error(
            "Ollama not reachable at %s — embeddings unavailable, memories will NOT be stored. "
            "Start Ollama and ensure model '%s' is pulled.",
            s.ollama_base_url, s.ollama_embed_model,
        )
        # Fill misses with zero vectors (don't cache them — see _LRUEmbedCache.put)
        for slot_i in miss_indices:
            results[slot_i] = [0.0] * s.ollama_embed_dim
        return results  # type: ignore[return-value]
    except Exception as e:
        logger.error(
            "embed_texts failed (model=%s url=%s): %s",
            s.ollama_embed_model, s.ollama_base_url, e,
        )
        for slot_i in miss_indices:
            results[slot_i] = [0.0] * s.ollama_embed_dim
        return results  # type: ignore[return-value]


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
