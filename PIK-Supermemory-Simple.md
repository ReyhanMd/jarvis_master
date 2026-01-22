# PIK Memory System with Supermemory Only
## Simplest, Fastest Integration Blueprint

---

## **STEP 1: Account & API Setup**

- [ ] Go to **supermemory.ai** and sign up for free account
- [ ] Create a new project called `pik-core`
- [ ] Generate API key from dashboard → copy it
- [ ] Create a folder: `mkdir pik-supermemory && cd pik-supermemory`
- [ ] Create Python virtual env: `python3 -m venv venv && source venv/bin/activate`
- [ ] Create `.env` file with: `SUPERMEMORY_API_KEY=your_key_here`
- [ ] Create `requirements.txt` with:
  ```
  supermemory
  python-dotenv
  fastapi
  uvicorn
  requests
  ```
- [ ] Install packages: `pip install -r requirements.txt`

---

## **STEP 2: Build Simple Client Module**

**File: `sm_client.py`**

- [ ] Ask Cursor/ChatGPT:
  ```
  Write a Python module sm_client.py that:
  - Loads SUPERMEMORY_API_KEY from .env
  - Creates a Supermemory client
  - Exposes: add_memory(container_tag, content, metadata) → returns memory id
  - Exposes: search_memories(container_tag, query, limit=5) → returns List[Dict] with content, metadata, score
  - Uses supermemory Python SDK
  - Handles errors and prints timing
  ```
- [ ] Copy the generated code into `sm_client.py`
- [ ] Test it: `python3 -c "from sm_client import add_memory; print('✅ Client works')"`

---

## **STEP 3: Create Smoke Test**

**File: `test_sm_basic.py`**

- [ ] Copy this code:
  ```python
  from sm_client import add_memory, search_memories
  
  TAG = "pik-test"
  
  add_memory(TAG, "PIK is a personal AI kernel for engineering workflows.", {"type": "description"})
  add_memory(TAG, "SHAIL orchestrates robotics and simulation tasks.", {"type": "description"})
  
  results = search_memories(TAG, "What is PIK?")
  for r in results:
      print(r["score"], r["content"][:80])
  ```
- [ ] Run it: `python3 test_sm_basic.py`
- [ ] Verify you see relevant text come back with scores

---

## **STEP 4: Ingest Your Real Docs & Code**

### 4.1 Plain text and Markdown

**File: `ingest_text_docs.py`**

- [ ] Ask Cursor:
  ```
  Create a script ingest_text_docs.py that:
  - Walks a ./docs folder for .md and .txt files
  - Reads each file
  - Calls add_memory(container_tag="pik-core", content=file_text, metadata={"file": filename, "source": "doc"})
  - Prints progress and summary
  ```
- [ ] Create a `./docs` folder with your markdown/text files
- [ ] Run: `python3 ingest_text_docs.py`
- [ ] Verify: check Supermemory dashboard for ingested memories

### 4.2 GitHub repos and URLs

**File: `ingest_urls.py`**

- [ ] Ask Cursor:
  ```
  Create a script ingest_urls.py that:
  - Takes a list of URLs (GitHub raw, Notion, etc.)
  - For each URL, calls add_memory(container_tag="pik-core", content=url, metadata={"source": "github"})
  - Supermemory will auto-detect URLs and extract content
  - Prints progress
  ```
- [ ] Define your URLs (GitHub repos, Notion exports, etc.)
- [ ] Run: `python3 ingest_urls.py`

### 4.3 Chat logs

**File: `ingest_chats.py`**

- [ ] Export chat history from your tool as JSON
- [ ] Ask Cursor:
  ```
  Create a script ingest_chats.py that:
  - Reads chat JSON files
  - For each conversation, joins messages into a text block
  - Calls add_memory(container_tag="pik-chats", content=conversation_text, metadata={"source": "chat", "thread_id": ...})
  - Prints progress
  ```
- [ ] Run: `python3 ingest_chats.py`

---

## **STEP 5: Build PIK Memory Interface**

**File: `pik_memory.py`**

- [ ] Create this simple module:
  ```python
  from sm_client import add_memory, search_memories
  
  def save_event(space: str, text: str, metadata: dict | None = None):
      """Save an event/decision/task to memory"""
      return add_memory(space, text, metadata)
  
  def get_context(space: str, question: str, limit: int = 5) -> str:
      """Get memory context as formatted string for prompts"""
      hits = search_memories(space, question, limit=limit)
      lines = []
      for h in hits:
          lines.append(f"- {h['content'][:200]}... (relevance: {h.get('score', 0):.1%})")
      return "\n".join(lines)
  ```
- [ ] Test it manually: `python3 -c "from pik_memory import get_context; print(get_context('pik-core', 'What is PIK?'))"`

---

## **STEP 6: (Optional) Build Simple HTTP API**

**File: `api.py`**

- [ ] Ask Cursor:
  ```
  Create a FastAPI server api.py that:
  - Imports pik_memory functions
  - POST /save → JSON: {space, text, metadata} → calls save_event
  - POST /context → JSON: {space, question, limit} → returns {"context": "..."}
  - Runs on localhost:8000
  ```
- [ ] Run: `uvicorn api:app --reload`
- [ ] Test with curl:
  ```bash
  curl -X POST http://localhost:8000/context -H "Content-Type: application/json" -d '{"space":"pik-core","question":"What is PIK?"}'
  ```

---

## **STEP 7: Integrate into PIK Agent Loop**

- [ ] Wherever you build prompts for PIK agents, do this:
  ```python
  from pik_memory import get_context, save_event
  
  # Before calling LLM:
  context = get_context("pik-core", task_description, limit=5)
  prompt = f"""
  You are PIK, the personal intelligence kernel.
  
  Past context:
  {context}
  
  Now handle this task:
  {task_description}
  """
  
  # Call your LLM with prompt
  result = llm.call(prompt)
  
  # After task completes:
  save_event("pik-core", f"Task: {task_description}\nResult: {result}", {"type": "task_result"})
  ```
- [ ] Test with a real task
- [ ] Verify memories appear in Supermemory dashboard

---

## **STEP 8: Validation & Sanity Checks**

**File: `validate.py`**

- [ ] Create a test that:
  ```python
  from pik_memory import get_context
  import time
  
  # Test 1: Latency
  start = time.perf_counter()
  result = get_context("pik-core", "What is SHAIL?", limit=5)
  elapsed = (time.perf_counter() - start) * 1000
  print(f"Query latency: {elapsed:.1f}ms")
  
  # Test 2: Content
  if "SHAIL" in result or "orchestr" in result:
      print("✅ Relevance check PASS")
  else:
      print("❌ Relevance check FAIL")
  ```
- [ ] Run: `python3 validate.py`
- [ ] Look for latency under ~500ms and relevant results

---

## **STEP 9: Documentation**

**File: `README.md`**

- [ ] Write a simple guide covering:
  - How to get Supermemory API key
  - How to set up `.env`
  - How to run ingestion scripts
  - How to call `get_context()` and `save_event()`
  - How to run the optional FastAPI server

---

## **STEP 10: Container Tags (Memory Spaces)**

- [ ] Define your memory namespaces:
  - `"pik-core"` → PIK design, architecture, plans
  - `"pik-repos"` → code files and GitHub repos
  - `"pik-chats"` → chat history
  - `"pik-experiments"` → experiment results
  - (Add more as needed)
- [ ] Use these tags consistently when calling `add_memory()` and `search_memories()`

---

## **STEP 11: Final Integration Checklist**

- [ ] Supermemory API key is active and in `.env`
- [ ] `sm_client.py` works (test manually)
- [ ] All ingestion scripts ran without errors
- [ ] `pik_memory.py` works (`get_context()` and `save_event()`)
- [ ] `validate.py` passes (latency + relevance)
- [ ] PIK agent loop calls `get_context()` before LLM
- [ ] PIK agent loop calls `save_event()` after task completes
- [ ] README.md documents everything
- [ ] No hardcoded API keys (use `.env`)

---

## **WHAT YOU'LL HAVE**

✅ PIK can query long-term memory (docs, code, chats, past tasks)  
✅ PIK saves decisions and results to memory automatically  
✅ Memory is searchable by meaning (semantic search)  
✅ No local setup complexity (just Supermemory API)  
✅ Scales automatically (Supermemory handles it)  
✅ Easy to extend (add more container tags, adjust metadata)

---

## **EXACT COMMANDS TO RUN (Copy-paste)**

```bash
# Setup
mkdir pik-supermemory && cd pik-supermemory
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install supermemory python-dotenv fastapi uvicorn requests
echo "SUPERMEMORY_API_KEY=YOUR_KEY_HERE" > .env

# Create sm_client.py (ask Cursor)
# Create pik_memory.py (simple, shown above)
# Create ingest_text_docs.py (ask Cursor)
# Create ingest_urls.py (ask Cursor)
# Create ingest_chats.py (ask Cursor)

# Ingest data
python3 ingest_text_docs.py
python3 ingest_urls.py
python3 ingest_chats.py

# Validate
python3 test_sm_basic.py
python3 validate.py

# Run (if using FastAPI API)
uvicorn api:app --reload

# Or use in-process: from pik_memory import get_context, save_event
```

---

## **THAT'S IT**

No hybrid routing. No local embeddings. No SQLite complexity.  
Just Supermemory + simple wrapper = PIK has long-term memory.

Go build! 🚀
