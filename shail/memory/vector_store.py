"""Vector store abstraction for RAG (pgvector with Chroma fallback)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingRecord:
    id: Optional[str]
    namespace: str
    content: str
    metadata: Dict[str, Any]
    embedding: List[float]


class VectorStore:
    """Base class for vector stores."""

    def upsert(self, records: List[EmbeddingRecord]) -> List[str]:
        raise NotImplementedError

    def query(
        self,
        query_embedding: List[float],
        namespace: Optional[str],
        filters: Optional[Dict[str, Any]],
        k: int,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError


class PgVectorStore(VectorStore):
    """Postgres + pgvector implementation."""

    def __init__(self, dsn: str, table: str = "rag_embeddings", dim: int = 768):
        import psycopg2

        self.dsn = dsn
        self.table = table
        self.dim = dim
        self._conn = psycopg2
        self._init_schema()

    def _connect(self):
        return self._conn.connect(self.dsn)

    def _init_schema(self):
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                    cur.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self.table} (
                            id TEXT PRIMARY KEY,
                            namespace TEXT NOT NULL,
                            content TEXT NOT NULL,
                            metadata JSONB,
                            embedding vector({self.dim}),
                            created_at TIMESTAMPTZ DEFAULT NOW()
                        );
                        """
                    )
                    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.table}_ns ON {self.table}(namespace);")
                    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.table}_meta ON {self.table} USING GIN (metadata);")
        finally:
            conn.close()

    @staticmethod
    def _vector_literal(embedding: List[float]) -> str:
        return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"

    def upsert(self, records: List[EmbeddingRecord]) -> List[str]:
        if not records:
            return []
        conn = self._connect()
        ids: List[str] = []
        try:
            with conn:
                with conn.cursor() as cur:
                    for rec in records:
                        rec_id = rec.id or str(uuid.uuid4())
                        ids.append(rec_id)
                        meta = rec.metadata or {}
                        meta.setdefault("namespace", rec.namespace)
                        vec = self._vector_literal(rec.embedding)
                        cur.execute(
                            f"""
                            INSERT INTO {self.table} (id, namespace, content, metadata, embedding)
                            VALUES (%s, %s, %s, %s, %s::vector)
                            ON CONFLICT (id) DO UPDATE
                              SET content=EXCLUDED.content,
                                  metadata=EXCLUDED.metadata,
                                  embedding=EXCLUDED.embedding,
                                  namespace=EXCLUDED.namespace;
                            """,
                            (
                                rec_id,
                                rec.namespace,
                                rec.content,
                                json.dumps(meta),
                                vec,
                            ),
                        )
        finally:
            conn.close()
        return ids

    def query(
        self,
        query_embedding: List[float],
        namespace: Optional[str],
        filters: Optional[Dict[str, Any]],
        k: int,
    ) -> List[Dict[str, Any]]:
        if not query_embedding:
            return []
        conn = self._connect()
        results: List[Dict[str, Any]] = []
        try:
            where_clauses = []
            params: List[Any] = []
            if namespace:
                where_clauses.append("namespace = %s")
                params.append(namespace)
            if filters:
                for key, val in filters.items():
                    where_clauses.append(f"metadata ->> %s = %s")
                    params.append(key)
                    params.append(str(val))
            where_sql = " AND ".join(where_clauses)
            if where_sql:
                where_sql = "WHERE " + where_sql

            vec = self._vector_literal(query_embedding)
            sql = f"""
            SELECT id, content, metadata, embedding <=> %s::vector AS score
            FROM {self.table}
            {where_sql}
            ORDER BY score ASC
            LIMIT %s;
            """
            params = [vec] + params + [k]
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                for row in rows:
                    rec_id, content, metadata, score = row
                    results.append(
                        {
                            "id": rec_id,
                            "content": content,
                            "metadata": metadata or {},
                            "score": score,
                        }
                    )
        finally:
            conn.close()
        return results


class ChromaVectorStore(VectorStore):
    """Chroma fallback store (persisted locally)."""

    def __init__(self, persist_path: str):
        import chromadb

        self.client = chromadb.PersistentClient(path=persist_path)
        self.collection = self.client.get_or_create_collection(
            name="shail_rag",
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, records: List[EmbeddingRecord]) -> List[str]:
        if not records:
            return []
        ids = [rec.id or str(uuid.uuid4()) for rec in records]
        metadatas = []
        for rec in records:
            meta = rec.metadata or {}
            meta.setdefault("namespace", rec.namespace)
            metadatas.append(meta)
        self.collection.upsert(
            ids=ids,
            documents=[rec.content for rec in records],
            embeddings=[rec.embedding for rec in records],
            metadatas=metadatas,
        )
        return ids

    def query(
        self,
        query_embedding: List[float],
        namespace: Optional[str],
        filters: Optional[Dict[str, Any]],
        k: int,
    ) -> List[Dict[str, Any]]:
        if not query_embedding:
            return []
        chroma_filters = filters.copy() if filters else {}
        if namespace:
            chroma_filters["namespace"] = namespace
        res = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=chroma_filters or None,
        )
        results: List[Dict[str, Any]] = []
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        ids = res.get("ids", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for doc, meta, rid, dist in zip(docs, metas, ids, dists):
            results.append({"id": rid, "content": doc, "metadata": meta or {}, "score": dist})
        return results


def get_vector_store(store_type: str, *, dsn: str, chroma_path: str, dim: int) -> VectorStore:
    """Factory to create vector store."""
    if store_type == "pgvector":
        return PgVectorStore(dsn=dsn, dim=dim)
    if store_type == "chroma":
        return ChromaVectorStore(persist_path=chroma_path)
    logger.warning("Unknown vector store type %s, falling back to Chroma.", store_type)
    return ChromaVectorStore(persist_path=chroma_path)
