# PIK: Complete Engineering Blueprint
## Outcome-Driven Build in 3 Days × 5 Hours = 15 Hours Total

**Status:** Production-Ready Architecture | Ready for Cursor Implementation  
**For:** Engineering Team (Sreekar, Ritwik, Shrikar, Hiren)  
**Launch Date:** 3 days from now  
**Target Outcome:** Functional demo with memory, routing, screen awareness, agent view

---

## Philosophy: Outcome-Driven (NOT Feature-Driven)

### Core Principle

**Every task asks:**
1. What outcome does the user experience? (not "what did we build?")
2. How do we know it works in 30 seconds? (testable, not aspirational)
3. What's the MINIMUM path to that outcome? (bias toward fake > perfect)
4. Can we deploy a working (imperfect) version today? (speed > perfection)

**Example:**
- ❌ Bad: "Build Agent View with real tool control"
- ✅ Good: "User sees PIK 'doing something' with narrated steps within 2 seconds"
  - Minimum: App screenshot + text log of fake actions + cursor animation = ship by hour 4 of Day 1

---

## Phase 0: Pre-Build (4 Hours, Parallel to Engineering)

### SHASHANK — Stack & Feasibility Locked (2 hrs)

**Deliverables (Paste into #engineering Slack):**

✅ **Memory Stack**: SQLite + local JSON (fallback) + Supermemory adapter  
✅ **Router**: Rules-based (research → Perplexity, planning → Gemini, reflection → local)  
✅ **OCR**: Tesseract.js browser-side + SmolDocling backup  
✅ **Model APIs**: Perplexity + Gemini (stubs OK for v1)  
✅ **Voice**: Web Speech API (browser native, no server)  
✅ **Agent Execution**: Fake cursor + JSON logs (real Playwright later)  

**No "figure this out during coding".**

### SARAN — Problem Locked (1.5 hrs)

**Pilots confirm:**
- ✅ "Context loss is #1 pain" (4/5 interviews)
- ✅ "Memory + multi-model is differentiator" (all agreed)
- ✅ "Would pay $10–15/mo" (3/4 said yes)

### REYHAN — Acceptance Criteria Locked (0.5 hrs)

**Posted in Notion:**

```
✅ DONE when:
- Quick Popup opens with keyboard shortcut, <100ms
- Memory saved → query 10 minutes later → recalled in response
- Router chooses Perplexity for "research" → response shows "[Routed to Perplexity]"
- Screenshot captured → OCR summary < 3 sec → shown in chat
- Agent View shows app + narrated steps + fake cursor animation
- All features work end-to-end in <3 min demo
```

---

## Phase 1: Build Sprint (15 Hours)

### **DAY 1 — CORE LOOP (5 hours)**

#### **Hour 0–1: Skeleton + Quick Popup UI**

**Owner:** SREEKAR (Frontend)

**Cursor Prompt Template:**

```
You are building PIK (Personal Intelligence Kernel) — a personal AI that 
remembers users and routes to the best model.

TASK 1: Initialize React + Express project

1. Create React app with Vite (fast dev)
   npx create-vite@latest pik-frontend --template react
   npm install

2. Create Express backend (single file, Node)
   mkdir pik-backend && cd pik-backend
   npm init -y && npm install express cors sqlite3

3. Wire dev server
   Frontend: npm run dev (port 3000)
   Backend: node server.js (port 5000)

OUTCOME: Repo skeleton ready, dev servers running

VERIFY:
- npm run dev launches both servers
- No errors in console
```

**Cursor Prompt 2:**

```
TASK 2: Build Quick Popup Component (React)

Requirements:
- Opens with keyboard shortcut (⌘ + Shift + Space on macOS, Ctrl+Shift+Space on Windows)
- Has text input box + mic icon + "+" menu button
- Status ring in corner (states: "listening" / "thinking" / "ready")
- Closes when user hits Escape or clicks outside
- Styled with glassmorphism (semi-transparent blur effect)

File: src/components/QuickPopup.jsx

Structure:
```tsx
export function QuickPopup() {
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState("ready"); // "listening" | "thinking" | "ready"

  // Keyboard shortcut handler
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === ' ') {
        e.preventDefault();
        setIsOpen(!isOpen);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const handleSubmit = async () => {
    setStatus("thinking");
    // TODO: Send input to backend
    setStatus("ready");
  };

  if (!isOpen) return null;

  return (
    <div className="popup-overlay" onClick={() => setIsOpen(false)}>
      <div className="popup-card" onClick={e => e.stopPropagation()}>
        <div className={`status-ring status-${status}`} />
        <input 
          value={input} 
          onChange={e => setInput(e.target.value)}
          placeholder="Ask PIK anything..."
        />
        <button onClick={() => setStatus("listening")}>🎤</button>
        <button>+</button>
      </div>
    </div>
  );
}
```

OUTCOME: Quick Popup opens/closes with keyboard shortcut

VERIFY:
- Keyboard shortcut opens popup
- Closes on Escape
- Input box accepts text
```

**Deliverable:** Quick Popup component + CSS (glassmorphism styling)

---

#### **Hour 1–2: Chat Overlay Panel**

**Owner:** SREEKAR (Frontend)

**Cursor Prompt:**

```
TASK 3: Build Chat Overlay Panel (React)

Requirements:
- Right-side vertical panel (320px wide)
- Shows message history (scrollable)
- User messages: blue bubbles, right-aligned
- Assistant messages: gray bubbles, left-aligned
- Shows memory references inline: "[Recalled from memory: your project uses ROS2]"
- Expandable code blocks (syntax highlighted)
- File drag-and-drop zone for uploads
- Collapses to corner when minimized

File: src/components/ChatOverlay.jsx

Message structure:
```tsx
const messages = [
  { 
    sender: "user", 
    text: "How do I use ROS2 with my project?",
    timestamp: "10:15 AM"
  },
  {
    sender: "assistant",
    text: "Based on your project (web app with Electron), here's...",
    memoryRefs: ["project:web-app-electron", "skill:ros2-basics"],
    model: "Perplexity", // Which model answered
    timestamp: "10:16 AM"
  }
];
```

Render:
- Message bubbles with sender distinction
- Memory refs as small tags under assistant messages
- Code blocks with copy button + syntax highlight (use highlight.js or Prism)
- Drag-drop zone at bottom
- Scroll to newest message automatically

OUTCOME: Chat panel displays messages with memory refs and code formatting

VERIFY:
- Messages show correctly
- Code blocks render with syntax highlighting
- Memory refs display as tags
- Drag-drop zone visible
```

**Deliverable:** Chat Overlay component + CSS

---

#### **Hour 2–3: Backend Memory CRUD API**

**Owner:** SHRIKAR (Backend)

**Cursor Prompt:**

```
TASK 4: Build Memory CRUD Endpoints (Express + SQLite)

File: server.js

Requirements:
1. SQLite database initialization
   - Table: memories
   - Columns: id (uuid), title, content, tags (JSON array), scope (life|project|session), created_at
   - Auto-create DB on startup

2. Endpoints:
   POST /memory
   - Body: { title, content, tags[], scope }
   - Response: { id, created_at, ...input }
   - Action: Insert into DB

   GET /memory?project=STRING
   - Returns: [ { id, title, content, tags, created_at }, ... ]
   - Filter by project scope or life scope

   DELETE /memory/:id
   - Response: { success: true }

3. Error handling:
   - 400 if missing title/content
   - 500 if DB fails (log error)

Code structure:
```js
const express = require('express');
const sqlite3 = require('sqlite3').verbose();
const { v4: uuidv4 } = require('uuid');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(express.json());

// SQLite setup
const db = new sqlite3.Database('./pik.db');
db.run(`
  CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT,
    scope TEXT DEFAULT 'life',
    created_at TEXT
  )
`);

// POST /memory
app.post('/memory', (req, res) => {
  const { title, content, tags = [], scope = 'life' } = req.body;
  if (!title || !content) return res.status(400).send("Missing fields");
  
  const id = uuidv4();
  const created_at = new Date().toISOString();
  db.run(
    "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?)",
    [id, title, content, JSON.stringify(tags), scope, created_at],
    (err) => {
      if (err) return res.status(500).send(err.message);
      res.json({ id, title, content, tags, scope, created_at });
    }
  );
});

// GET /memory
app.get('/memory', (req, res) => {
  const { project } = req.query;
  const query = project 
    ? "SELECT * FROM memories WHERE scope = 'project' OR scope = 'life'"
    : "SELECT * FROM memories";
  
  db.all(query, (err, rows) => {
    if (err) return res.status(500).send(err.message);
    res.json(rows.map(r => ({ ...r, tags: JSON.parse(r.tags) })));
  });
});

// DELETE /memory/:id
app.delete('/memory/:id', (req, res) => {
  db.run("DELETE FROM memories WHERE id = ?", [req.params.id], (err) => {
    if (err) return res.status(500).send(err.message);
    res.json({ success: true });
  });
});

app.listen(5000, () => console.log('PIK backend running on :5000'));
```

OUTCOME: Memory endpoints working, can save/retrieve/delete memories

VERIFY:
- POST /memory saves to DB
- GET /memory returns saved memories
- DELETE /memory removes entry
- Test with curl or Postman
```

**Deliverable:** Memory CRUD API working

---

#### **Hour 3–4: Wire Popup to Backend**

**Owner:** SREEKAR (Frontend) + SHRIKAR (Backend)

**Cursor Prompt:**

```
TASK 5: Connect Quick Popup to Backend

Requirements:
1. When user types message + hits Enter:
   - Send to backend POST /chat
   - Show "thinking" status
   - Receive response
   - Display in Chat Overlay
   - Extract memory references from response

2. "Add to memory" button in chat:
   - User clicks on message
   - Modal opens: Title, Tags, Content (pre-filled)
   - Click "Save" → POST /memory
   - Show confirmation toast

Backend needs new endpoint:
POST /chat
- Body: { prompt, memoryContext, routerMode: "auto" | "manual" }
- Response: { textOutput, modelUsed, memory_refs: [], timestamp }
- For now: use stub response (no real API calls)

Frontend changes:
- Quick Popup sends input to POST /chat
- Receives response
- Adds to message history
- Shows in Chat Overlay

Stub response example:
{
  textOutput: "Here's how to use ROS2...",
  modelUsed: "Perplexity (stub)",
  memory_refs: ["project:web-app", "skill:ros2"],
  timestamp: "2026-01-20T10:16:00Z"
}

OUTCOME: Type message in Quick Popup → appears in Chat Overlay

VERIFY:
- Input message appears in chat
- Backend stub response comes back
- Chat shows memory references
```

**Deliverable:** Chat flow working (stub backend)

---

#### **Hour 4–5: Integration Test + Polish**

**Owner:** REYHAN (QA/Integration)

**Checklist:**

```
✅ Quick Popup opens with keyboard shortcut
✅ Input message appears in Chat Overlay
✅ Backend stub response appears in chat
✅ Memory refs show as tags
✅ "Add to memory" button saves to SQLite
✅ Subsequent query recalls memory
✅ Code blocks render correctly
✅ No console errors
✅ Responsive on 1920x1080 viewport

Polish:
✅ Status ring animates (spinning while thinking)
✅ Message timestamps show relative ("2 min ago")
✅ Smooth animations (fade-in, slide-up)
✅ Accessible: keyboard navigation, ARIA labels
```

**Deliverable:** Day 1 complete, demo-ready (no real AI yet)

---

### **DAY 2 — INTELLIGENCE (5 hours)**

#### **Hour 0–1: Router Logic**

**Owner:** SHRIKAR (Backend)

**Cursor Prompt:**

```
TASK 6: Build Router (Intent Classifier)

Requirements:
- Classify user intent: "research" | "planning" | "reflection"
- Route to: Perplexity | Gemini | local-stub
- Add manual override toggle

Backend endpoint:
POST /router
- Body: { prompt, mode: "auto" | "manual", selectedModel?: "perplexity" | "gemini" }
- Response: { modelToUse, confidence, reasoning }

Logic (simple rules):
- If prompt contains: "research", "find", "search", "latest" → Perplexity
- If prompt contains: "plan", "design", "how to", "strategy" → Gemini
- Else → local-stub

For v1: Just return routing decision (don't call real APIs yet)

Code:
```js
const classify_intent = (prompt) => {
  const research_keywords = ['research', 'find', 'search', 'latest', 'current', 'recent'];
  const planning_keywords = ['plan', 'design', 'how to', 'strategy', 'build', 'create'];
  
  const is_research = research_keywords.some(k => prompt.toLowerCase().includes(k));
  const is_planning = planning_keywords.some(k => prompt.toLowerCase().includes(k));
  
  if (is_research) return { model: 'Perplexity', confidence: 0.8 };
  if (is_planning) return { model: 'Gemini', confidence: 0.8 };
  return { model: 'local-stub', confidence: 0.5 };
};

app.post('/router', (req, res) => {
  const { prompt, mode = 'auto', selectedModel } = req.body;
  
  if (mode === 'manual' && selectedModel) {
    return res.json({ modelToUse: selectedModel, confidence: 1.0 });
  }
  
  const { model, confidence } = classify_intent(prompt);
  res.json({ modelToUse: model, confidence });
});
```

OUTCOME: POST /router returns routing decision

VERIFY:
- "research AI trends" → returns Perplexity
- "plan my day" → returns Gemini
- Manual override works
```

**Deliverable:** Router working (logs which model chosen)

---

#### **Hour 1–2: Memory Retrieval (Search)**

**Owner:** SHRIKAR (Backend)

**Cursor Prompt:**

```
TASK 7: Memory Search with Relevance

Requirements:
- When user sends a prompt, search memories for relevant entries
- Return top-3 relevant memories
- Simple relevance: tag/keyword overlap + recency

Backend:
POST /memory/search
- Body: { query: string }
- Response: { memories: [ { id, title, content, relevance: 0–1 }, ... ] }

Algorithm:
1. Extract keywords from query
2. Find memories where tags or title contain keywords
3. Score by: keyword_matches + recency_bonus
4. Return top 3

Code:
```js
app.post('/memory/search', (req, res) => {
  const { query } = req.body;
  const keywords = query.toLowerCase().split(' ').filter(w => w.length > 2);
  
  db.all("SELECT * FROM memories", (err, rows) => {
    if (err) return res.status(500).send(err.message);
    
    const scored = rows.map(row => {
      const tags = JSON.parse(row.tags || '[]');
      const matches = keywords.filter(k => 
        row.title.toLowerCase().includes(k) || 
        tags.some(t => t.toLowerCase().includes(k))
      ).length;
      
      const age_days = (Date.now() - new Date(row.created_at)) / (1000 * 60 * 60 * 24);
      const recency_bonus = 1 - Math.min(age_days / 30, 0.5); // decay over 30 days
      
      return { ...row, tags, relevance: matches + recency_bonus * 0.5 };
    });
    
    const top3 = scored.sort((a, b) => b.relevance - a.relevance).slice(0, 3);
    res.json({ memories: top3.filter(m => m.relevance > 0) });
  });
});
```

OUTCOME: Memory search returns relevant past entries

VERIFY:
- Save memory about "ROS2 project"
- Query "How do I use ROS?" → returns that memory
- Relevance score reflects recency
```

**Deliverable:** Memory search working

---

#### **Hour 2–3: Screen Capture + OCR Pipeline**

**Owner:** SREEKAR (Frontend)

**Cursor Prompt:**

```
TASK 8: Screenshot Capture + Tesseract OCR

Requirements:
1. Frontend: "Send screen" button in Chat Overlay
2. Capture current browser viewport (or active window if desktop app)
3. Send image to backend
4. Backend runs Tesseract OCR
5. Summarize text (<50 words)
6. Return summary to chat
7. User can "Add summary to memory"

Frontend (React):
```tsx
const handleSendScreen = async () => {
  const canvas = await html2canvas(document.body, { 
    width: window.innerWidth,
    height: window.innerHeight
  });
  const blob = canvas.toBlob(blob => {
    const formData = new FormData();
    formData.append('image', blob, 'screenshot.png');
    
    fetch('http://localhost:5000/ocr', {
      method: 'POST',
      body: formData
    })
    .then(r => r.json())
    .then(data => {
      // Display summary in chat
      addMessage({
        sender: 'assistant',
        text: `Screenshot captured at ${new Date().toLocaleTimeString()}\\n\\nSummary: ${data.summary}`,
        type: 'screen-capture'
      });
    });
  });
};
```

Backend (Node + Tesseract.js):
```js
const Tesseract = require('tesseract.js');
const multer = require('multer');
const upload = multer({ storage: multer.memoryStorage() });

app.post('/ocr', upload.single('image'), async (req, res) => {
  try {
    const { data: { text } } = await Tesseract.recognize(
      req.file.buffer,
      'eng'
    );
    
    // Simple summarization: first N words + key terms
    const words = text.split(' ');
    const summary = words.slice(0, 50).join(' ');
    
    res.json({ full_text: text, summary });
  } catch (err) {
    res.status(500).send(err.message);
  }
});
```

Install: `npm install html2canvas tesseract.js multer`

OUTCOME: Button captures screen → OCR summary appears in chat

VERIFY:
- Click "Send screen" button
- Screenshot uploaded to backend
- OCR text extracted
- Summary displayed in chat < 5 sec
```

**Deliverable:** Screen capture + OCR working

---

#### **Hour 3–4: Agent View (Fake Cursor + Logs)**

**Owner:** SREEKAR (Frontend)

**Cursor Prompt:**

```
TASK 9: Agent View (Simulated)

Requirements:
1. Show app screenshot (user's current screen or mock)
2. Overlay text log of "actions PIK is taking"
3. Fake cursor animation following a pre-coded path
4. Looks like PIK is "doing something"

React Component: src/components/AgentView.jsx

Structure:
```tsx
export function AgentView({ isActive }) {
  const [logs, setLogs] = useState([
    { time: '10:16:00', action: 'Analyzing screenshot...' },
    { time: '10:16:01', action: 'Found error message: "Connection timeout"' },
    { time: '10:16:02', action: 'Navigating to help page...' },
  ]);
  
  if (!isActive) return null;
  
  return (
    <div className="agent-view">
      {/* App screenshot background */}
      <img src="current-app.png" alt="App" className="app-screenshot" />
      
      {/* Fake cursor with animation */}
      <div className="fake-cursor" />
      
      {/* Action log overlay */}
      <div className="action-log">
        {logs.map((log, i) => (
          <div key={i} className="log-entry">
            <span className="time">{log.time}</span>
            <span className="action">{log.action}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

CSS:
```css
.agent-view {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: #0f0f0f;
}

.app-screenshot {
  width: 100%;
  height: 100%;
  opacity: 0.8;
  object-fit: cover;
}

.fake-cursor {
  position: fixed;
  width: 16px;
  height: 16px;
  background: red;
  border-radius: 50%;
  animation: move-cursor 8s ease-in-out infinite;
  pointer-events: none;
}

@keyframes move-cursor {
  0% { left: 100px; top: 100px; }
  50% { left: 800px; top: 300px; }
  100% { left: 100px; top: 100px; }
}

.action-log {
  position: fixed;
  right: 20px;
  bottom: 20px;
  width: 300px;
  max-height: 400px;
  background: rgba(0, 0, 0, 0.9);
  color: #0f0;
  font-family: monospace;
  padding: 16px;
  border-radius: 8px;
  overflow-y: auto;
  border: 1px solid #0f0;
}

.log-entry {
  font-size: 12px;
  margin-bottom: 8px;
  line-height: 1.5;
}

.time { color: #888; margin-right: 8px; }
.action { color: #0f0; }
```

OUTCOME: Agent View shows app + narrated actions + fake cursor

VERIFY:
- Agent View modal opens when feature is triggered
- Cursor animates across screen
- Action log updates in real-time
```

**Deliverable:** Agent View mock working

---

#### **Hour 4–5: Toggles + Usage Meter**

**Owner:** SREEKAR (Frontend)

**Cursor Prompt:**

```
TASK 10: Toggles & Usage Meter

Requirements:
1. Toggles (visible in Chat Overlay or settings):
   - Memory ON/OFF
   - Screen-aware ON/OFF
   - Router AUTO/MANUAL
   
2. Usage Meter:
   - Show API calls count
   - Show tokens used / tier limit
   - Visual bar (green → yellow → red)

React component:

```tsx
export function ControlsPanel() {
  const [controls, setControls] = useState({
    memory: true,
    screenAware: true,
    router: 'auto' // 'auto' | 'manual'
  });
  
  const [usage, setUsage] = useState({
    calls: 125,
    tokens: 45000,
    limit: 100000,
    tier: 'Builder'
  });
  
  const usagePercent = (usage.tokens / usage.limit) * 100;
  const usageColor = usagePercent < 50 ? 'green' : usagePercent < 80 ? 'orange' : 'red';
  
  return (
    <div className="controls-panel">
      <h3>Settings</h3>
      
      {/* Toggles */}
      <label>
        <input 
          type="checkbox" 
          checked={controls.memory}
          onChange={e => setControls({...controls, memory: e.target.checked})}
        />
        Memory: {controls.memory ? 'ON' : 'OFF'}
      </label>
      
      <label>
        <input 
          type="checkbox" 
          checked={controls.screenAware}
          onChange={e => setControls({...controls, screenAware: e.target.checked})}
        />
        Screen Aware: {controls.screenAware ? 'ON' : 'OFF'}
      </label>
      
      <label>
        Router:
        <select value={controls.router} onChange={e => setControls({...controls, router: e.target.value})}>
          <option value="auto">Auto</option>
          <option value="manual">Manual</option>
        </select>
      </label>
      
      {/* Usage Meter */}
      <div className="usage-meter">
        <p>Monthly Usage ({usage.tier} Tier)</p>
        <div className="meter-bar">
          <div className="meter-fill" style={{
            width: usagePercent + '%',
            backgroundColor: usageColor
          }} />
        </div>
        <p>{usage.tokens} / {usage.limit} tokens</p>
      </div>
    </div>
  );
}
```

OUTCOME: Toggles control feature flags, meter shows usage

VERIFY:
- Toggle switches work
- Usage meter displays correctly
- Tier info shows
```

**Deliverable:** Controls + Usage Meter working

---

### **DAY 3 — FINALIZE & TEST (5 hours)**

#### **Hour 0–1: Real API Integration Stubs**

**Owner:** SHRIKAR (Backend)

**Task:** Replace hardcoded responses with API stubs

```
POST /chat now routes through:
1. Router (classify intent)
2. Memory search (find relevant past entries)
3. Route to Perplexity / Gemini / local
4. (For now: return stub response with [model] tag)

POST /chat request:
{
  prompt: "How do I use ROS2 with my project?",
  memoryContext: ["project:web-app", "skill:basics"],
  routerMode: "auto"
}

Response:
{
  textOutput: "[Routed to Perplexity (stub)] Here's how to use ROS2...",
  modelUsed: "Perplexity",
  memoryRefs: ["project:web-app-electron"],
  timestamp: "2026-01-20T10:16:00Z",
  confidence: 0.85
}
```

**Deliverable:** Backend routes through full pipeline (stubs OK)

---

#### **Hour 1–2: Export Session + Developer Mode**

**Owner:** SREEKAR (Frontend) + SHRIKAR (Backend)

**Cursor Prompt:**

```
TASK 11: Export Session to JSON

Requirements:
- Button: "Export session" in settings
- Downloads JSON with all chat + memory for that session
- Useful for debugging

Backend:
GET /export-session?sessionId=STRING
- Response: { sessionId, createdAt, messages: [...], memories: [...] }

Frontend:
- Click button → triggers download
- File: pik-session-{date}.json

Test:
- Have a conversation
- Click export
- Verify JSON contains messages + memories
```

**Deliverable:** Export working

---

#### **Hour 2–3: End-to-End Integration Test**

**Owner:** REYHAN (QA)

**Test Scenario:**

```
Scenario: User uses PIK for first time

1. Open PIK (keyboard shortcut)
2. Ask: "How do I set up Electron + React?"
3. Verify:
   ✅ Popup opens instantly
   ✅ Message appears in Chat Overlay
   ✅ Router classifies as "planning" → routes to Gemini
   ✅ Stub response appears: "[Routed to Gemini] Here's how..."
   ✅ Can click "Add to memory"
   ✅ Memory saved to SQLite

4. Send screenshot
5. Verify:
   ✅ Screenshot button visible
   ✅ Captured viewport sent to backend
   ✅ OCR runs < 3 sec
   ✅ Summary appears in chat
   ✅ Can add summary to memory

6. Ask similar question 5 minutes later
7. Verify:
   ✅ Memory recalled: "[Recalled from memory: Electron + React setup]"
   ✅ Response includes memory in context
   ✅ User knows PIK "remembered"

8. Toggle "Memory OFF"
9. Verify:
   ✅ Next response does NOT include memory
   ✅ Toggle works

10. Click "Agent View"
11. Verify:
    ✅ Shows app screenshot
    ✅ Fake cursor animates
    ✅ Action log narrates steps
    ✅ Feels like PIK is "doing something"

12. Export session
13. Verify:
    ✅ JSON file downloads
    ✅ Contains all messages + memories

RESULT: ✅ Full workflow works end-to-end
```

**Deliverable:** All features integrated + tested

---

#### **Hour 3–4: Performance & Polish**

**Owner:** SREEKAR (Frontend) + HIREN (Deployment)

```
Checklist:
✅ Quick Popup opens < 100ms (measure with DevTools)
✅ Chat messages appear < 500ms
✅ Memory search < 300ms
✅ OCR < 3 sec
✅ Agent View animates smoothly (60 FPS)
✅ No console errors
✅ Responsive: 1920x1080, 1440x900, 768x1024
✅ Keyboard accessible (Tab, Enter, Escape)
✅ ARIA labels for screen readers

Polish:
✅ Status ring animation (spinning, pulsing)
✅ Message fade-in animations
✅ Hover states on buttons
✅ Loading spinners
✅ Toast notifications for success/error
✅ Empty state messages ("No memories yet")
✅ Dark mode by default (light mode later)
```

**Deliverable:** Polished, production-ready UI

---

#### **Hour 4–5: Demo Script + Deploy to Staging**

**Owner:** REYHAN (Product) + HIREN (Deployment)

**Demo Script (3 minutes):**

```
[0:00-0:30] Show Quick Popup
- "Press ⌘+Shift+Space..."
- Popup appears (instant)
- Show status ring states

[0:30-1:00] Memory + Router
- Type: "How do I use ROS2?"
- Router logs "[Routed to Gemini]"
- Response includes memory: "[Recalled: your project uses ROS2]"
- Click "Add response to memory"

[1:00-1:30] Screen Awareness
- Type: "What error is this?"
- Click "Send screen"
- Screenshot captured + OCR summary < 3 sec
- Summary appears in chat

[1:30-2:00] Agent View
- Click "Show Agent View"
- App screen + narrated actions + fake cursor
- "PIK is analyzing the code, found the issue, navigating to docs..."

[2:00-2:30] Toggles + Export
- Toggle "Memory OFF"
- Ask same question → NO memory recall
- Toggle back ON
- Click "Export session"
- JSON downloads

[2:30-3:00] Closing
- "PIK is your personal AI that remembers, routes to the best model, and guides you. Available next week."
```

**Deploy to Staging:**
- Frontend: Vercel
- Backend: Railway or Heroku free tier
- Database: SQLite (can migrate to cloud later)

**Deliverable:** Live demo + staging deployment

---

## Summary: 15-Hour Build Plan

| Phase | Tasks | Hours | Owner | Outcome |
|-------|-------|-------|-------|---------|
| **Day 1** | Skeleton + Popup + Chat + Memory API + Router | 5 | Sreekar, Shrikar | Full chat loop working |
| **Day 2** | Memory search + OCR + Agent View + Toggles | 5 | Sreekar, Shrikar | All features implemented |
| **Day 3** | Integration + Testing + Polish + Deploy | 5 | Reyhan, Hiren | Production-ready demo |

---

## Acceptance Criteria (FINAL)

```
✅ PASS if:

Quick Popup
- Opens with keyboard shortcut < 100ms
- Closes on Escape
- Input sends to backend

Chat Overlay
- Messages display correctly
- Memory refs shown as tags
- Code blocks render with syntax highlighting

Memory
- Saved to SQLite
- Retrieved on similar queries
- Can be deleted/edited

Router
- Classifies research → Perplexity
- Classifies planning → Gemini
- Manual override works

Screen Awareness
- "Send screen" button present
- Screenshot captured + OCR < 3 sec
- Summary appears in chat
- Can add to memory

Agent View
- Shows app screenshot
- Cursor animates
- Action log displays
- Looks professional

Toggles
- Memory ON/OFF works
- Screen-aware ON/OFF works
- Router AUTO/MANUAL works

Usage Meter
- Shows tokens used / limit
- Visual bar changes color

Export
- "Export session" downloads JSON
- JSON valid + debuggable

Demo
- Full workflow works in 3 minutes
- Ready to show to pilots
```

---

## Pre-Build Coordination (Parallel to Engineering)

**Week before:**
- [ ] Shashank: Stack + Feasibility locked (2 hrs)
- [ ] Saran: Problem validation done (1.5 hrs)
- [ ] Reyhan: Acceptance criteria posted in Notion (0.5 hrs)

**Day of:**
- [ ] Standup: 9 AM (15 min)
- [ ] Standup: 2 PM (15 min)
- [ ] Standup: 5 PM (15 min)

**Day after:**
- [ ] Demo to Arman + Priyank (30 min)
- [ ] Feedback loop (1 hr)
- [ ] Fix critical issues (2 hrs)
- [ ] Ready for pilots (Wednesday morning)

---

**Document Version:** 1.0  
**Last Updated:** January 20, 2026  
**Status:** Ready for Cursor Implementation  
**Next Step:** Kick off Day 1 build tomorrow 9 AM