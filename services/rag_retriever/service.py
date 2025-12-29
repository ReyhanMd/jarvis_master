"""
RAG Retriever Service - Context retrieval from knowledge base
"""

import asyncio
import time
import sys
import os
from typing import List, Optional
from loguru import logger
from fastapi import FastAPI, HTTPException

# Handle imports for both module and direct script execution
# Add parent directory to path for direct script execution
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Try relative imports first (when run as module), then absolute (when run as script)
try:
    from .models import Document, Query, RetrievalResult
except (ImportError, ValueError):
    from rag_retriever.models import Document, Query, RetrievalResult

# Optional: Embedding model
try:
    from sentence_transformers import SentenceTransformer
    HAS_EMBEDDINGS = True
except ImportError:
    logger.warning("sentence-transformers not installed - embeddings will not be available")
    HAS_EMBEDDINGS = False

# Optional: Vector database
try:
    import chromadb
    HAS_CHROMADB = True
except ImportError:
    logger.warning("chromadb not installed - using in-memory storage")
    HAS_CHROMADB = False


class RAGRetrieverService:
    """
    Retrieves relevant context from knowledge base.
    
    Namespaces:
    - git_docs: Git documentation
    - python_docs: Python documentation
    - past_runs: Episodic memory of past task executions
    - web_search: Cached web search results
    - custom: User-added knowledge
    
    Features:
    - Vector similarity search
    - Metadata filtering
    - Multiple namespaces
    - Caching
    """
    
    def __init__(self, persist_directory: str = "./rag_data"):
        self.app = FastAPI(title="Shail RAG Retriever")
        self._setup_routes()
        
        self.persist_directory = persist_directory
        self.embedding_model = None
        self.vector_db = None
        
        # Initialize embedding model
        if HAS_EMBEDDINGS:
            logger.info("🤖 Loading embedding model...")
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("✅ Embedding model loaded")
        
        # Initialize vector database
        if HAS_CHROMADB:
            logger.info("💾 Initializing vector database...")
            self.vector_db = chromadb.PersistentClient(path=persist_directory)
            logger.info("✅ Vector database initialized")
        else:
            # Fallback: in-memory storage
            self.in_memory_docs: Dict[str, List[Document]] = {}
    
    def _setup_routes(self):
        """Setup FastAPI routes"""
        
        @self.app.post("/retrieve", response_model=RetrievalResult)
        async def retrieve(query: Query):
            """Retrieve relevant documents"""
            return await self.retrieve(query)
        
        @self.app.post("/index", response_model=dict)
        async def index_document(doc: Document):
            """Index a new document"""
            await self.index(doc)
            return {"status": "ok", "document_id": doc.id}
        
        @self.app.post("/index_batch", response_model=dict)
        async def index_documents(docs: List[Document]):
            """Index multiple documents"""
            await self.index_batch(docs)
            return {"status": "ok", "count": len(docs)}
        
        @self.app.delete("/namespace/{namespace}")
        async def delete_namespace(namespace: str):
            """Delete all documents in a namespace"""
            await self.delete_namespace(namespace)
            return {"status": "ok", "namespace": namespace}
        
        @self.app.get("/health")
        async def health():
            """Health check"""
            return {
                "status": "ok",
                "embeddings_available": HAS_EMBEDDINGS,
                "vector_db_available": HAS_CHROMADB
            }
    
    async def retrieve(self, query: Query) -> RetrievalResult:
        """
        Retrieve relevant documents for a query.
        """
        start_time = time.time()
        
        logger.info(f"🔍 Retrieving: '{query.query[:50]}...' (namespace: {query.namespace}, k={query.top_k})")
        
        if self.vector_db and HAS_EMBEDDINGS:
            documents = await self._retrieve_from_chromadb(query)
        else:
            documents = await self._retrieve_from_memory(query)
        
        # Filter by minimum score
        documents = [doc for doc in documents if (doc.score or 0) >= query.min_score]
        
        # Limit to top_k
        documents = documents[:query.top_k]
        
        retrieval_time_ms = (time.time() - start_time) * 1000
        
        result = RetrievalResult(
            query=query.query,
            documents=documents,
            total_found=len(documents),
            retrieval_time_ms=retrieval_time_ms,
            namespace=query.namespace
        )
        
        logger.info(f"✅ Retrieved {len(documents)} documents in {retrieval_time_ms:.1f}ms")
        
        return result
    
    async def _retrieve_from_chromadb(self, query: Query) -> List[Document]:
        """Retrieve using ChromaDB vector search"""
        
        # Get or create collection
        collection_name = query.namespace or "default"
        
        try:
            collection = self.vector_db.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            logger.warning(f"Failed to get collection {collection_name}: {e}")
            return []
        
        # Generate query embedding
        query_embedding = await asyncio.to_thread(
            self.embedding_model.encode,
            query.query
        )
        
        # Search
        try:
            results = collection.query(
                query_embeddings=[query_embedding.tolist()],
                n_results=query.top_k,
                where=query.filters or None
            )
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []
        
        # Convert to Document objects
        documents = []
        if results['ids'] and len(results['ids'][0]) > 0:
            for i, doc_id in enumerate(results['ids'][0]):
                doc = Document(
                    id=doc_id,
                    content=results['documents'][0][i],
                    namespace=collection_name,
                    metadata=results['metadatas'][0][i] if results['metadatas'] else {},
                    score=1.0 - results['distances'][0][i]  # Convert distance to similarity
                )
                documents.append(doc)
        
        return documents
    
    async def _retrieve_from_memory(self, query: Query) -> List[Document]:
        """Fallback: simple text matching in memory"""
        
        namespace = query.namespace or "default"
        docs = self.in_memory_docs.get(namespace, [])
        
        # Simple keyword matching
        query_lower = query.query.lower()
        scored_docs = []
        
        for doc in docs:
            content_lower = doc.content.lower()
            
            # Count matching words
            query_words = set(query_lower.split())
            content_words = set(content_lower.split())
            matches = len(query_words & content_words)
            
            if matches > 0:
                score = matches / len(query_words)
                doc_copy = doc.model_copy()
                doc_copy.score = score
                scored_docs.append(doc_copy)
        
        # Sort by score
        scored_docs.sort(key=lambda d: d.score or 0, reverse=True)
        
        return scored_docs
    
    async def index(self, doc: Document):
        """Index a single document"""
        await self.index_batch([doc])
    
    async def index_batch(self, docs: List[Document]):
        """Index multiple documents"""
        
        logger.info(f"📝 Indexing {len(docs)} documents")
        
        if self.vector_db and HAS_EMBEDDINGS:
            await self._index_to_chromadb(docs)
        else:
            await self._index_to_memory(docs)
        
        logger.info(f"✅ Indexed {len(docs)} documents")
    
    async def _index_to_chromadb(self, docs: List[Document]):
        """Index documents to ChromaDB"""
        
        # Group by namespace
        by_namespace: Dict[str, List[Document]] = {}
        for doc in docs:
            if doc.namespace not in by_namespace:
                by_namespace[doc.namespace] = []
            by_namespace[doc.namespace].append(doc)
        
        # Index each namespace
        for namespace, ns_docs in by_namespace.items():
            collection = self.vector_db.get_or_create_collection(
                name=namespace,
                metadata={"hnsw:space": "cosine"}
            )
            
            # Generate embeddings
            contents = [doc.content for doc in ns_docs]
            embeddings = await asyncio.to_thread(
                self.embedding_model.encode,
                contents,
                show_progress_bar=False
            )
            
            # Add to collection
            collection.add(
                ids=[doc.id for doc in ns_docs],
                embeddings=embeddings.tolist(),
                documents=contents,
                metadatas=[doc.metadata for doc in ns_docs]
            )
    
    async def _index_to_memory(self, docs: List[Document]):
        """Index documents to in-memory storage"""
        
        for doc in docs:
            if doc.namespace not in self.in_memory_docs:
                self.in_memory_docs[doc.namespace] = []
            self.in_memory_docs[doc.namespace].append(doc)
    
    async def delete_namespace(self, namespace: str):
        """Delete all documents in a namespace"""
        
        logger.info(f"🗑️  Deleting namespace: {namespace}")
        
        if self.vector_db:
            try:
                self.vector_db.delete_collection(namespace)
            except Exception as e:
                logger.warning(f"Failed to delete collection {namespace}: {e}")
        else:
            if namespace in self.in_memory_docs:
                del self.in_memory_docs[namespace]
        
        logger.info(f"✅ Deleted namespace: {namespace}")
    
    async def start(self, host: str = "0.0.0.0", port: int = 8082):
        """Start the RAG Retriever HTTP API"""
        import uvicorn
        
        logger.info(f"🚀 Starting RAG Retriever API on {host}:{port}")
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


# Main entry point
if __name__ == "__main__":
    service = RAGRetrieverService()
    
    try:
        asyncio.run(service.start())
    except KeyboardInterrupt:
        logger.info("👋 RAG Retriever service stopped")

