# RAG Retriever Service

Retrieval-Augmented Generation (RAG) service for context retrieval from knowledge base.

## Features

- **Vector Search**: Semantic similarity search using embeddings
- **Multiple Namespaces**: Organize documents by type (git_docs, past_runs, etc.)
- **Metadata Filtering**: Filter by custom metadata
- **Persistent Storage**: ChromaDB for vector storage
- **HTTP API**: RESTful API for retrieval and indexing

## Namespaces

- `git_docs`: Git documentation
- `python_docs`: Python documentation  
- `past_runs`: Episodic memory of past task executions
- `web_search`: Cached web search results
- `custom`: User-added knowledge

## Running the Service

```bash
cd services/rag_retriever
pip install -r requirements.txt
python service.py
```

The API will be available at `http://localhost:8082`.

## API Endpoints

### POST /retrieve
Retrieve relevant documents.

```json
{
  "query": "How do I create a git commit?",
  "namespace": "git_docs",
  "top_k": 5,
  "min_score": 0.5
}
```

Response:
```json
{
  "query": "How do I create a git commit?",
  "documents": [
    {
      "id": "git-commit-1",
      "content": "To create a commit, use: git commit -m 'message'",
      "namespace": "git_docs",
      "metadata": {"source": "official_docs"},
      "score": 0.92
    }
  ],
  "total_found": 1,
  "retrieval_time_ms": 45.2,
  "namespace": "git_docs"
}
```

### POST /index
Index a single document.

```json
{
  "id": "doc-123",
  "content": "Git is a version control system...",
  "namespace": "git_docs",
  "metadata": {"author": "user", "created_at": "2025-11-13"}
}
```

### POST /index_batch
Index multiple documents at once.

### DELETE /namespace/{namespace}
Delete all documents in a namespace.

## Usage Example

```python
import httpx

async def get_git_help(question: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8082/retrieve",
            json={
                "query": question,
                "namespace": "git_docs",
                "top_k": 3
            }
        )
        result = response.json()
        
        # Use retrieved docs as context
        context = "\n\n".join([doc["content"] for doc in result["documents"]])
        return context

# Use in planner
context = await get_git_help("How do I revert a commit?")
plan = llm.generate(f"Context: {context}\n\nTask: {task}")
```

## Indexing Documents

### From Files
```python
from services.rag_retriever import RAGRetrieverService, Document

service = RAGRetrieverService()

# Load git docs
with open("git_docs.txt") as f:
    content = f.read()
    
doc = Document(
    id="git-basics",
    content=content,
    namespace="git_docs",
    metadata={"source": "file"}
)

await service.index(doc)
```

### From Past Runs
```python
# After task completion
summary = generate_task_summary(task, logs, result)

doc = Document(
    id=f"run-{task_id}",
    content=summary,
    namespace="past_runs",
    metadata={
        "task_type": "git_commit",
        "success": True,
        "timestamp": time.time()
    }
)

await rag_service.index(doc)
```

## Integration with Planner

The planner uses RAG to retrieve relevant context:

```python
# In planner
async def plan_with_rag(task: str):
    # Get relevant documentation
    docs_result = await rag.retrieve(Query(
        query=task,
        namespace="git_docs",
        top_k=5
    ))
    
    # Get similar past runs
    past_result = await rag.retrieve(Query(
        query=task,
        namespace="past_runs",
        top_k=3
    ))
    
    # Build context
    context = format_context(docs_result.documents + past_result.documents)
    
    # Generate plan with context
    prompt = f"Context:\n{context}\n\nTask: {task}\n\nPlan:"
    plan = llm.generate(prompt)
    
    return plan
```

## Performance

- Embedding generation: ~10-50ms per query
- Vector search: ~5-20ms per query (ChromaDB)
- Total retrieval: ~50-100ms

## License

Part of the Shail AI system.

