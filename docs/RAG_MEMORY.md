# RAG Memory System Documentation

## Overview

SHAIL's RAG (Retrieval-Augmented Generation) memory system provides persistent storage for:
- Tool states and usage history
- Project context and user intents
- Architecture notes and design decisions
- Modification history

## Components

### Tool Memory (`shail/memory/tool_memory.py`)

Stores tool states and usage history:

```python
from shail.memory.tool_memory import store_tool_state, log_tool_usage

# Store tool state
store_tool_state("freecad", {"file": "model.fcstd"}, result={"objects": 5})

# Log tool usage
log_tool_usage("freecad", {"file": "model.fcstd"}, success=True, task_id="task_123")
```

### Project Context (`shail/memory/project_context.py`)

Stores project context and user intents:

```python
from shail.memory.project_context import store_user_intent, store_tool_config

# Store user intent
store_user_intent("my_project", "Build a robot arm")

# Store tool configuration
store_tool_config("my_project", "freecad", {"precision": "high"})
```

### Architecture Notes

Store architecture decisions:

```python
from shail.memory.project_context import store_architecture_note

store_architecture_note(
    "integration",
    "MCP Integration Complete",
    "All tools now register with MCP for universal discovery"
)
```

## Integration with RAG

All memory operations integrate with the main RAG system:

```python
from shail.memory import rag

# Store tool state via RAG
rag.store_tool_state_for_rag("freecad", {"file": "model.fcstd"})

# Get project context via RAG
context = rag.get_project_context_from_rag("my_project")
```

## RAG vector search (Gemini + pgvector)

- Embeddings: Gemini (`text-embedding-004`, set via `RAG_EMBEDDING_MODEL`, `GEMINI_API_KEY`)
- Vector store: pgvector (`RAG_VECTOR_STORE=pgvector`, `RAG_PG_DSN=postgresql://...`)  
  Fallback: Chroma (`RAG_VECTOR_STORE=chroma`, `RAG_CHROMA_PATH=./rag_chroma`)
- Chunking: `RAG_CHUNK_SIZE` (default 800 chars), overlap `RAG_CHUNK_OVERLAP` (default 120)
- Default top-k: `RAG_TOP_K` (default 5)

### Ingest files
```python
rag.ingest(paths=["README.md", "src/module.py"])
```

### Ingest arbitrary records (tool results, notes, etc.)
```python
rag.ingest(records=[{
    "namespace": "project_context",
    "content": "Important design note ...",
    "metadata": {"project": "alpha", "context_type": "note"}
}])
```

### Search with filters
```python
results = rag.search(
    "how do we call freecad?",
    k=5,
    namespace="tool_usage",
    filters={"tool_name": "freecad", "project": "alpha"}
)
for content, score, meta in results:
    print(score, meta, content[:80])
```

RAG automatically ingests:
- Tool state/usage (`rag.store_tool_state_for_rag`, `rag.log_tool_usage_for_rag`)
- Project context/intents/config/patterns
- Architecture notes

Router exposes `rag_search` for agent-side retrieval.
