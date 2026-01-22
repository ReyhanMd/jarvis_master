# PIK: OUTCOME-DRIVEN ENGINEERING BLUEPRINT
## From Cursor → Live → Functional (3-Day Sprint)

**Principle:** Build for outcome (demo works, users sign up), not perfection.

**Tech Stack:**
- **Frontend:** React 18 + Vite + Tailwind + Framer Motion
- **Backend:** Express.js + better-sqlite3 (or SQLite3)
- **Deployment:** Vercel (frontend) + Railway (backend)
- **Dev Tool:** Cursor (AI-powered scaffolding)
- **APIs:** Perplexity (research) + Gemini (decision-making) + Tesseract.js (OCR)

---

## ARCHITECTURE DIAGRAM

```
┌─────────────────────────────────────────────────────────────┐
│                     USER BROWSER                            │
├─────────────────────────────────────────────────────────────┤
│ QuickPopup (Cmd+Shift+Space)                                │
│   ↓ (text input)                                            │
│ ChatOverlay (right panel)                                   │
│   ↓ (displays response)                                     │
│ ScreenshotButton (capture intent)                           │
│   ↓ (screenshot + OCR)                                      │
│ AgentView (animated "thinking" state)                       │
│   ↓ (shows router decision)                                 │
│ Export button (download JSON)                               │
└─────────────────────────────────────────────────────────────┘
                         ↓ API calls
┌─────────────────────────────────────────────────────────────┐
│               BACKEND (Express.js on Railway)               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  POST /api/memory (save memory + tags)                      │
│    ↓ triggers router logic                                  │
│  GET /api/route (intent detection)                          │
│    ├─ Keywords: research → Perplexity                       │
│    ├─ Keywords: plan/structure → Gemini                     │
│    └─ Default: Gemini                                       │
│                                                             │
│  Routes to External APIs:                                   │
│    ├─ POST → Perplexity API (research queries)              │
│    ├─ POST → Gemini API (general Q&A, reasoning)            │
│    └─ POST → Tesseract.js (OCR, screenshot text)            │
│                                                             │
│  GET /api/memory (retrieve saved memories)                  │
│    └─ Returns recent 20 items or search by tags             │
│                                                             │
│  DELETE /api/memory/:id (delete memory)                     │
│                                                             │
│  POST /api/export (download session JSON)                   │
│    └─ Returns memories + metadata                           │
│                                                             │
│  Database: SQLite3 Local                                    │
│    └─ memories table (id, user_id, content, tags, ...)      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## DAY 1: SCAFFOLDING & SETUP

### Phase 1: Repository Initialization (30 min)

**Ritwik does this first (unblocks everyone):**

```bash
# Initialize repo
git clone [your-repo]
cd pik

# Backend structure
npm init -y
npm install express better-sqlite3 dotenv cors uuid

# Create structure
mkdir -p src/api src/db src/routes
touch src/server.js src/db/memory.js src/routes/memory.js

# Frontend structure
npm create vite@latest pik-web -- --template react
cd pik-web
npm install tailwind postcss autoprefixer framer-motion

# Root structure
echo "
PERPLEXITY_API_KEY=xxx
GEMINI_API_KEY=xxx
PORT=3000
" > .env
```

**Add to `.gitignore`:**
```
.env
node_modules
dist
.DS_Store
```

### Phase 2: Database Schema (45 min)

**Cursor Prompt for Ritwik:**

```
You are a backend engineer. Create SQLite schema for PIK memory system.

Requirements:
1. Table "memories": id (UUID), user_id (string), content (text), tags (string, comma-separated), created_at (timestamp), source (enum: chat, screenshot, research), metadata (JSON string)
2. CRUD functions using better-sqlite3
3. Search by tag, by date range, by source
4. Export all memories as JSON
5. Delete memory by ID

Return:
- Schema creation script
- Functions: createMemory, getMemory, searchMemory, deleteMemory, exportAll
- Example usage for each function

Use better-sqlite3 driver. No async/await (synchronous DB).

Export as src/db/memory.js
```

**Ritwik runs this in Cursor → generates file:**

```javascript
// src/db/memory.js
const Database = require('better-sqlite3');
const { v4: uuidv4 } = require('uuid');
const path = require('path');

const db = new Database(path.join(__dirname, 'pik.db'));

// Initialize schema
db.exec(`
  CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    source TEXT,
    metadata TEXT,
    project_id TEXT DEFAULT 'default'
  );
  
  CREATE INDEX IF NOT EXISTS idx_user_id ON memories(user_id);
  CREATE INDEX IF NOT EXISTS idx_created_at ON memories(created_at);
  CREATE INDEX IF NOT EXISTS idx_project_id ON memories(project_id);
`);

// CRUD Operations
const createMemory = (userId, content, tags = '', source = 'chat', metadata = {}) => {
  const id = uuidv4();
  const stmt = db.prepare(`
    INSERT INTO memories (id, user_id, content, tags, source, metadata, project_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `);
  stmt.run(id, userId, content, tags, source, JSON.stringify(metadata), 'default');
  return { id, userId, content, tags, source };
};

const getMemory = (id) => {
  const stmt = db.prepare('SELECT * FROM memories WHERE id = ?');
  return stmt.get(id);
};

const searchMemory = (userId, tags = null, limit = 20) => {
  let query = 'SELECT * FROM memories WHERE user_id = ?';
  const params = [userId];
  
  if (tags) {
    query += ' AND tags LIKE ?';
    params.push(`%${tags}%`);
  }
  
  query += ' ORDER BY created_at DESC LIMIT ?';
  params.push(limit);
  
  const stmt = db.prepare(query);
  return stmt.all(...params);
};

const deleteMemory = (id) => {
  const stmt = db.prepare('DELETE FROM memories WHERE id = ?');
  const result = stmt.run(id);
  return result.changes > 0;
};

const exportAll = (userId) => {
  const memories = searchMemory(userId, null, 1000);
  return memories.map(m => ({
    ...m,
    metadata: m.metadata ? JSON.parse(m.metadata) : {}
  }));
};

module.exports = { createMemory, getMemory, searchMemory, deleteMemory, exportAll, db };
```

**Ritwik commits:**
```bash
git add src/db/memory.js
git commit -m "feat: add SQLite memory schema and CRUD functions"
```

### Phase 3: Express Backend Routes (60 min)

**Cursor Prompt for Ritwik:**

```
You are a backend engineer. Create Express.js REST API for PIK.

Requirements:
1. POST /api/memory
   - Body: {query: string, tags?: string}
   - Returns: {id, message: "Memory saved"}
   - Calls memory.createMemory()

2. GET /api/memory?project=default&limit=20
   - Returns: {memories: [...]}
   - Calls memory.searchMemory()

3. DELETE /api/memory/:id
   - Returns: {success: true}
   - Calls memory.deleteMemory()

4. POST /api/route
   - Body: {query: string}
   - Logic: 
     - If query contains ['search', 'find', 'latest', 'news'] → model = 'perplexity'
     - Else if query contains ['plan', 'structure', 'steps', 'how'] → model = 'gemini'
     - Else → model = 'gemini' (default)
   - Returns: {model, reasoning, confidence}

5. POST /api/export
   - Returns: JSON file download of all memories

6. Error handling: try/catch, 500 errors with message

Export as src/routes/memory.js and src/server.js
```

**Ritwik generates Express app:**

```javascript
// src/server.js
const express = require('express');
const cors = require('cors');
require('dotenv').config();

const { createMemory, searchMemory, deleteMemory, exportAll } = require('./db/memory');

const app = express();
app.use(express.json());
app.use(cors());

// Routes
app.post('/api/memory', (req, res) => {
  try {
    const { query, tags = '' } = req.body;
    const userId = req.headers['x-user-id'] || 'default-user';
    
    const memory = createMemory(userId, query, tags, 'chat');
    res.json({ id: memory.id, message: 'Memory saved' });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/memory', (req, res) => {
  try {
    const userId = req.headers['x-user-id'] || 'default-user';
    const { tags, limit = 20 } = req.query;
    
    const memories = searchMemory(userId, tags, parseInt(limit));
    res.json({ memories });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.delete('/api/memory/:id', (req, res) => {
  try {
    const success = deleteMemory(req.params.id);
    res.json({ success });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/route', (req, res) => {
  try {
    const { query } = req.body;
    
    const researchKeywords = ['search', 'find', 'latest', 'news', 'research', 'what is', 'how does'];
    const planningKeywords = ['plan', 'structure', 'steps', 'how to', 'guide'];
    
    let model = 'gemini'; // default
    let reasoning = 'No specific keywords detected, using default model';
    
    if (researchKeywords.some(kw => query.toLowerCase().includes(kw))) {
      model = 'perplexity';
      reasoning = 'Research query detected, routing to Perplexity for live web search';
    } else if (planningKeywords.some(kw => query.toLowerCase().includes(kw))) {
      model = 'gemini';
      reasoning = 'Planning/structure query, Gemini excels at structured thinking';
    }
    
    res.json({ model, reasoning, confidence: 0.85 });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/export', (req, res) => {
  try {
    const userId = req.headers['x-user-id'] || 'default-user';
    const memories = exportAll(userId);
    
    res.setHeader('Content-Disposition', `attachment; filename="pik-export-${Date.now()}.json"`);
    res.json(memories);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(process.env.PORT || 3000, () => {
  console.log('PIK backend running on port', process.env.PORT || 3000);
});

module.exports = app;
```

**Ritwik tests locally:**
```bash
node src/server.js
# Test: curl -X POST http://localhost:3000/api/memory -H "Content-Type: application/json" -d '{"query":"Test memory"}'
```

**Commit:**
```bash
git add src/server.js
git commit -m "feat: create Express API routes (memory CRUD, router logic)"
```

### Phase 4: Frontend Scaffolding with Cursor (60 min)

**Sreekar uses Cursor to generate React components:**

**Cursor Prompt #1: QuickPopup Component**

```
Create a React component for PIK QuickPopup.

Requirements:
- Opens on Cmd+Shift+Space keyboard shortcut (hidden by default)
- Dark theme, glassmorphism effect (backdrop blur + semi-transparent bg)
- Components inside:
  1. Text input field (placeholder: "Ask anything...")
  2. Mic button (Voice icon, disabled for now)
  3. Menu button (hamburger)
  4. Submit button (Enter or Cmd+Enter)
  5. Status indicator (gray = idle, blue = thinking, green = ready)

State:
- isOpen (hidden/visible)
- query (text input value)
- status (idle, thinking, ready, error)

Behaviors:
- Listen for Cmd+Shift+Space, toggle isOpen
- On Submit: POST to backend /api/memory, then emit to parent
- Press Escape to close
- Auto-focus input when opened
- No TailwindCSS variables (use hex colors directly for MVP)

Styling: Dark theme (bg-slate-900, text-white), glassmorphism (backdrop-blur-xl)

Export as src/components/QuickPopup.tsx

Return full, working component.
```

**Sreekar gets generated component, saves to:**
```
src/
  components/
    QuickPopup.tsx
    ChatOverlay.tsx (generate next)
    ScreenshotButton.tsx
    AgentView.tsx
    ...
```

**Cursor Prompt #2: ChatOverlay Component**

```
Create React component for PIK ChatOverlay.

Requirements:
- Right-side panel, fixed position, ~400px wide
- Dark theme (matching QuickPopup)
- Sections:
  1. Header: "PIK Memory" + close button
  2. Chat history (list of messages)
     - User message (right-aligned, blue bg)
     - Assistant response (left-aligned, gray bg)
     - Timestamp + tag badges
  3. Input area at bottom (text input + send button)
  4. Scroll area (recent messages visible)

State:
- messages: Array<{id, role, content, tags, timestamp}>
- isOpen
- scrollPosition

Behaviors:
- New messages scroll to bottom auto
- Click message → highlight it
- Click tag → filter by that tag
- Close button → hide overlay

Styling: Dark glassmorphism, readable fonts

Export as src/components/ChatOverlay.tsx
```

**Sreekar iterates with Cursor until components look good.**

---

## DAY 2: INTEGRATION & CORE LOGIC

### Phase 1: Connect Frontend to Backend (90 min)

**Sreekar + Ritwik pair:**

**Cursor Prompt: API Client (Sreekar)**

```
Create React hook for PIK API calls.

Requirements:
- useMemoryAPI() hook
- Methods:
  1. saveMemory(query, tags) → POST /api/memory
  2. getMemories(limit) → GET /api/memory?limit=X
  3. deleteMemory(id) → DELETE /api/memory/:id
  4. routeQuery(query) → POST /api/route
  5. exportMemories() → POST /api/export

Error handling:
- Catch fetch errors
- Return {success: bool, data: ..., error: ...}
- Retry logic for network failures

Return src/hooks/useMemoryAPI.ts
```

**Sreekar generates hook, integrates into QuickPopup:**

```javascript
// src/components/QuickPopup.tsx
import { useMemoryAPI } from '../hooks/useMemoryAPI';

export function QuickPopup() {
  const [query, setQuery] = useState('');
  const { saveMemory, routeQuery } = useMemoryAPI();
  
  const handleSubmit = async () => {
    if (!query.trim()) return;
    
    // Route query to decide model
    const { model, reasoning } = await routeQuery(query);
    
    // Save to memory
    await saveMemory(query, model); // tags = model name
    
    // Notify parent/global state
    // (Will emit to ChatOverlay to display)
    
    setQuery('');
  };
  
  // ... rest of component
}
```

### Phase 2: Perplexity Integration (60 min)

**Cursor Prompt for Ritwik: Perplexity Wrapper**

```
Create Perplexity API client for PIK backend.

Requirements:
1. Call https://api.perplexity.ai/chat/completions
2. Model: pplx-7b-online (streaming-friendly)
3. Stream enabled (return partial responses)
4. Handle rate limits (429 response)
5. Retry logic (max 2 retries)
6. Timeout: 30 seconds
7. Return cleaned response text

Signature:
async function queryPerplexity(query: string): Promise<{response: string, sources: string[]}>

Error handling:
- Rate limit: Wait 60s, retry
- Timeout: Return "Perplexity unavailable, try again"
- Invalid key: Return "API key error"

Export as src/api/perplexity.js
```

**Ritwik generates:**

```javascript
// src/api/perplexity.js
const fetch = require('node-fetch');

async function queryPerplexity(query) {
  const apiKey = process.env.PERPLEXITY_API_KEY;
  const url = 'https://api.perplexity.ai/chat/completions';
  
  const payload = {
    model: 'pplx-7b-online',
    messages: [
      {
        role: 'user',
        content: query
      }
    ],
    stream: false, // Simplify for MVP (no streaming)
    max_tokens: 1000
  };
  
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload),
      timeout: 30000
    });
    
    if (response.status === 429) {
      throw new Error('Rate limited');
    }
    
    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }
    
    const data = await response.json();
    const responseText = data.choices[0].message.content;
    
    return {
      response: responseText,
      sources: [] // Could extract from response if available
    };
  } catch (err) {
    console.error('Perplexity error:', err.message);
    throw err;
  }
}

module.exports = { queryPerplexity };
```

**Add to backend route:**

```javascript
// src/server.js (add new route)
const { queryPerplexity } = require('./api/perplexity');

app.post('/api/perplexity', async (req, res) => {
  try {
    const { query } = req.body;
    const result = await queryPerplexity(query);
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});
```

**Ritwik tests:**
```bash
curl -X POST http://localhost:3000/api/perplexity \
  -H "Content-Type: application/json" \
  -d '{"query":"Latest AI breakthroughs 2026"}'
```

### Phase 3: Screenshot + OCR (90 min)

**Cursor Prompt for Sreekar: Screenshot Capture**

```
Create React component for PIK Screenshot Capture.

Requirements:
1. Button: "Capture Screen" with camera icon
2. On click: Opens native screenshot tool (navigator.mediaDevices or html2canvas)
3. Captured image → Post to backend POST /api/screenshot
4. Display returned OCR text in ChatOverlay
5. Auto-tag: #screenshot
6. Show loading state while processing

Alternative: Use html2canvas library to screenshot entire window

Export as src/components/ScreenshotButton.tsx
```

**Cursor Prompt for Ritwik: Backend OCR Endpoint**

```
Create Express endpoint for PIK screenshot OCR.

Requirements:
1. POST /api/screenshot
   - Receives: base64 image or multipart form
   - Extract text with Tesseract.js (npm install tesseract.js)
   - Summarize text with Gemini API (max 100 words)
   - Save to memory with tag #screenshot
   - Return: {text: string, summary: string, imageUrl: string}

2. Handle errors:
   - No image: 400 error
   - OCR fails: Return raw image, no text
   - Gemini fails: Return OCR text without summary

Export as src/routes/screenshot.js
```

**Ritwik generates OCR backend:**

```javascript
// src/routes/screenshot.js (simplified for MVP)
const router = require('express').Router();
const Tesseract = require('tesseract.js');
const { createMemory } = require('../db/memory');

router.post('/api/screenshot', async (req, res) => {
  try {
    const { image } = req.body; // base64 string
    
    if (!image) return res.status(400).json({ error: 'No image provided' });
    
    // OCR
    const result = await Tesseract.recognize(image, 'eng');
    const text = result.data.text;
    
    // Save to memory
    const userId = req.headers['x-user-id'] || 'default-user';
    createMemory(userId, text, '#screenshot', 'screenshot', { original_length: text.length });
    
    res.json({ text, summary: text.substring(0, 100) + '...' });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;
```

### Phase 4: Full Flow Test (60 min)

**All together:**

1. **User opens Quick Popup** (Cmd+Shift+Space)
2. **Types query:** "What's new in AI?"
3. **Hits Submit:**
   - Frontend POST /api/memory
   - Backend routes query → decides Perplexity
   - Shows decision in UI
   - Calls Perplexity API
   - Returns response → displayed in ChatOverlay
   - Saves response to memory

**Test Checklist:**
- [ ] QuickPopup opens
- [ ] Text input works
- [ ] Submit sends to backend
- [ ] Backend routing logic decides model correctly
- [ ] Perplexity API called and returns result
- [ ] Response shown in ChatOverlay
- [ ] Memory saved

---

## DAY 3: POLISH & DEPLOY

### Phase 1: Agent View Animation (60 min)

**Cursor Prompt for Sreekar: Agent View Component**

```
Create React component for PIK Agent View (thinking animation).

Requirements:
1. Shows fake cursor animation on mock screen
2. Status log on right side (list of actions)
   - "Analyzing query..."
   - "Routing to Perplexity..."
   - "Fetching research..."
   - "Summarizing..."
   - "Complete!"
3. Use Framer Motion for smooth cursor path animation
4. Duration: 3 seconds total
5. Loop: Run once, then show final result
6. Dark theme, glassmorphism

Export as src/components/AgentView.tsx

Return working component with example usage.
```

**Sreekar generates with Framer Motion animations.**

### Phase 2: Export Functionality (45 min)

**Cursor Prompt for Ritwik: Export Route**

```
Update backend to support session export.

Requirements:
1. GET /api/export
   - Returns all memories for user as JSON
   - File name: pik-session-{timestamp}.json
   - Format: {exported_at, user_id, memories: [...]}

2. Download headers:
   - Content-Disposition: attachment; filename=...

Export as part of src/server.js
```

**Sreekar adds Download button to ChatOverlay:**

```javascript
const handleExport = async () => {
  const response = await fetch('/api/export');
  const blob = new Blob([JSON.stringify(await response.json())], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `pik-export-${Date.now()}.json`;
  a.click();
};
```

### Phase 3: Final QA & Deployment (120 min)

**Hiren runs QA checklist:**

```
✅ FRONTEND QA (Vercel)
- [ ] QuickPopup keyboard shortcut works
- [ ] ChatOverlay displays messages
- [ ] Screenshot button visible
- [ ] Agent View animates
- [ ] Export button downloads JSON
- [ ] No console errors
- [ ] Mobile responsive (test on phone)
- [ ] Dark mode looks good
- [ ] Load time <2 seconds

✅ BACKEND QA (Railway)
- [ ] POST /api/memory saves (check DB)
- [ ] GET /api/memory returns data
- [ ] DELETE /api/memory/:id works
- [ ] POST /api/route makes decision
- [ ] POST /api/perplexity returns research
- [ ] POST /api/screenshot processes OCR
- [ ] POST /api/export downloads JSON
- [ ] No 500 errors in Sentry
- [ ] Response times <1 second

✅ INTEGRATION
- [ ] End-to-end flow works (query → response)
- [ ] Memory persists (close app, reopen, data still there)
- [ ] Multiple queries work in sequence
- [ ] Demo script runs without crashes

✅ DEPLOYMENT
- [ ] Frontend URL live (vercel domain or custom)
- [ ] Backend URL live (railway domain)
- [ ] No hardcoded API keys in code
- [ ] Env variables set correctly
- [ ] CI/CD pipeline green (no failed builds)
```

**Deploy with Hiren + Reyhan:**

```bash
# Frontend (Vercel)
cd pik-web
vercel deploy --prod

# Backend (Railway)
vercel link [railway-project]
# (or push to main branch if using GitHub auto-deploy)

# Verify live
curl https://[pik-backend-url]/api/memory
curl https://[pik-frontend-url]
```

### Phase 4: Beta Launch (Async, Arman leading)

**Send to first 100 users:**

Email template:
```
Subject: PIK is live—your personal AI OS 🚀

Hi [Name],

PIK is ready. Open it here: https://pik.ai/

It's simple:
1. Press Cmd+Shift+Space
2. Ask anything
3. PIK remembers

Features:
- Smart routing (research vs planning)
- Memory that sticks (no more lost context)
- Export anytime (your data, your call)

We're shipping as beta. Expect bugs, we expect feedback.

Questions? Reply to this email.

Excited,
Team PIK
```

---

## TECH STACK SUMMARY

| Layer | Tech | Why |
|-------|------|-----|
| **Frontend** | React 18 + Vite | Fast, modern, easy with Cursor |
| **Styling** | Tailwind CSS | Quick, dark mode built-in |
| **Animation** | Framer Motion | Smooth, lightweight |
| **State** | React hooks + Context | No Redux complexity |
| **Backend** | Express.js | Simple, boring (good for SHAIL) |
| **Database** | SQLite3 (better-sqlite3) | Local first, no external DB needed |
| **Deployment** | Vercel + Railway | Auto-deploy on git push, free tier works |
| **Research API** | Perplexity | Live web search, real-time |
| **Reasoning API** | Gemini | Strong reasoning, fallback model |
| **OCR** | Tesseract.js | Client-side, no server overhead |
| **Monitoring** | Sentry + PostHog | Error tracking + usage analytics |
| **Dev Tool** | Cursor | AI-powered scaffolding, 10x faster |

---

## CURSOR PROMPTING FORMULA

**Use this pattern for every Cursor generation:**

```
You are a [role: senior frontend/backend engineer].

Requirements:
1. [Specific requirement]
2. [Specific requirement]
3. [Specific requirement]

Edge cases:
- [Error scenario]
- [Performance scenario]

Return:
- Complete, working code (no TODOs)
- Comments on complex logic only
- Export ready to use

[Language/Framework]: [specific details]
```

**Why this works:**
- Clear role → Cursor adopts that expertise level
- Numbered requirements → Systematic coverage
- Edge cases → Handles error states
- Export → Ready to use immediately

---

## OUTCOME-DRIVEN BUILD PRINCIPLES

**1. Demo-First Development**

Every feature built = Must work in demo  
Demo = User opens PIK → Asks question → Gets answer → Sees memory

If feature doesn't support demo, it can wait (Day 4+).

**2. Shipping Over Perfection**

Good enough > perfect  
99% complete > blocked by last 1%  
Deploy, iterate, learn from users

**3. Sync Points, Not Sync Meetings**

9am standup (5 min, Slack)  
Async commits with clear messages  
No mid-day meetings unless truly blocked

**4. Outcome Metrics**

Success = "User signed up for beta"  
Not = "Code coverage 85%"  
Not = "All bugs fixed"  
Not = "Beautiful UI"

**5. Contingency Over Perfection**

Perplexity API down? Use Gemini.  
Deploy fails? Local server works for demo.  
Memory schema wrong? Migration script ready.

---

## POST-DEPLOYMENT (Day 4+)

Once beta ships:

1. **Collect feedback** from 100 users
2. **Prioritize:**
   - Critical bugs → fix immediately
   - Missing features requested by 10+ users → add
   - Nice-to-haves → backlog
3. **Iterate in 2-week cycles**
4. **Transition to paid tier** when ready (Day 10+)

---

**Estimated Hours:**

| Phase | Hours |
|-------|-------|
| Day 1 Scaffolding | 5 |
| Day 2 Integration | 5 |
| Day 3 Polish | 5 |
| **Total** | **15** |

**3 people × 5 hours = 15 hours team effort = realistic for 3-day sprint**

---

**Ship date:** January 23, 2026  
**Go-live time:** 2:00 PM IST  
**Beta users:** 100  
**Outcome:** Functioning PIK, real users, valuable feedback

Let's build.
