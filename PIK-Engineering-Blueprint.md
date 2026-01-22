# PIK: Engineering Blueprint & 3-Day Build Plan
## Build with Cursor IDE + Prebuilt Ecosystem

**Objective:** Outcome-driven build of PIK MVP in 3 days, 5 hours/day, shipping to 100 beta users by day 4.

**Core Principle:** Leverage EVERYTHING prebuilt. Don't reinvent. Assemble.

---

## PART 1: PREBUILT TOOLS & INTEGRATIONS

### A. Core Infrastructure

#### 1. **SuperMemory** (By Dravya Shah)
- **What:** Production-grade semantic memory for LLM apps
- **Why:** We don't build memory from scratch. SuperMemory is proven at scale.
- **Integration:**
  - API endpoint for saving memories (local wrapper)
  - Semantic search via embeddings
  - Tagging and scoping
- **Cost:** Free tier covers v1 (1M tokens, basic features)
- **Repo:** https://github.com/omnistrate/supermemory
- **Docs:** https://supermemory.ai/docs
- **Status:** ✅ Production-ready

#### 2. **Cursor IDE** (With Claude Integration)
- **Why:** AI-powered code generation, instant scaffolding, Cmd+K magic
- **Setup:**
  - Create `.cursor` config in repo (rules for code generation)
  - Set Claude API key for Cursor Chat
  - Pre-write prompts for common patterns (see Prompts section below)
- **Usage:**
  - "Generate React component for Quick Popup"
  - "Write Node backend for memory CRUD"
  - "Create SuperMemory integration layer"
- **Advantage:** 10x faster scaffolding than manual typing
- **Cost:** Cursor is free + Claude API (included in existing budget)
- **Docs:** https://docs.cursor.sh

#### 3. **Google Antigravity** (Future Option)
- **What:** Google's agent framework (emerging, December 2025+)
- **Status:** NOT YET used in v1 (monitor for future Agent View)
- **Reason:** v1 Agent View is simulated (fake cursor), not real action
- **Future:** When v2 needs true automation, Antigravity becomes orchestration layer
- **Note:** Keep architecture open for easy swap-in

---

### B. Orchestration & Routing

#### 4. **LangChain.js** (Optional Defer)
- **Recommendation:** NOT v1. Direct API calls are simpler.
- **Why:** LangChain adds abstraction layer. v1 just needs Perplexity + Gemini APIs.
- **v1.1+:** Introduce if we add 5+ models or complex chains
- **Setup:** Already defined in tech stack, skip for now

#### 5. **AutoGen** (Microsoft)
- **Status:** Monitor only. Not for v1.
- **Why:** AutoGen is for multi-agent collaboration. PIK v1 is single orchestrator + multiple models.
- **Future:** When PIK becomes SHAIL full system, AutoGen becomes orchestration backbone

#### 6. **Model Context Protocol (MCP)**
- **What:** Anthropic's standard for grounding AI in external knowledge
- **v1 Implementation:**
  - MCP server for SuperMemory (so Claude/Gemini can query memory)
  - MCP server for local files (so models can read user documents)
  - NIST database MCP (for research routing—future)
- **Benefit:** Model agnostic. Same interface for all APIs.
- **Docs:** https://modelcontextprotocol.io
- **Priority:** Medium (can add day 2 if time allows)

---

### C. Frontend & UI Components

#### 7. **React + Vite** (Scaffolding)
- **Template:** `npm create vite@latest pik-frontend -- --template react`
- **Component libraries:**
  - **Shadcn/UI** (headless, tailwind-based): Quick UI components
  - **Framer Motion** (animation): Smooth transitions, fake cursor paths
  - **TailwindCSS** (styling): Responsive, dark mode built-in
- **Reason:** All battle-tested, minimal dependencies, runs fast
- **Setup time:** 15 minutes (Cursor scaffolds 80%)

#### 8. **Tesseract.js** (OCR, Free)
- **What:** Client-side OCR for screenshot parsing
- **Why:** No backend needed. Privacy. Free.
- **Usage:** User clicks "Send Screen", Tesseract extracts text, summary sent to chat
- **Trade-off:** Slower than server OCR, but good enough for MVP
- **Docs:** https://tesseract.projectnaptha.com
- **Bundle size:** ~3MB (acceptable)

#### 9. **Web Speech API** (Voice, Native)
- **What:** Browser's native voice input/output
- **Why:** Free, no external dependency
- **Limitations:** Works best Chrome/Edge, limited voice customization
- **v1 Implementation:** Push-to-talk button, basic TTS
- **v1.1+:** Upgrade to PlayHT or Elevenlabs if needed
- **Docs:** https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API

---

### D. Backend & Database

#### 10. **SQLite** (Local, Zero-Ops)
- **What:** File-based database, runs on device or simple VPS
- **Why:** Zero maintenance, perfect for MVP, scales to 100K users easily
- **Setup:** `npm install sqlite3` or use `better-sqlite3` for sync operations
- **Schema:** Memory table, session table, user preferences
- **v1 Implementation:** All data local. Cloud backup optional via Stripe webhook later.

#### 11. **Drizzle ORM** (Optional, Lightweight)
- **What:** Type-safe database access for Node
- **Alternative:** Raw SQL (simpler for small schema)
- **v1 Recommendation:** Raw SQL or `better-sqlite3` + no ORM (faster onboarding)
- **Later:** Add Drizzle if schema grows complex

#### 12. **Node.js + Express** (Minimal Backend)
- **Setup:** `npm init -y && npm install express cors dotenv`
- **Routes needed (v1):**
  - POST `/memory` (save)
  - GET `/memory?project=X` (retrieve)
  - DELETE `/memory/:id` (delete)
  - POST `/route` (model routing decision)
  - POST `/screenshot` (OCR)
  - POST `/export` (JSON export)
- **Middleware:** CORS, auth token (user session)
- **Deployment:** Vercel (serverless) or Railway (easier)

---

### E. API Integrations (Already Existing)

#### 13. **Perplexity API**
- **Status:** Ready. Already integrated in many PIK demos.
- **Setup:** API key from Perplexity dashboard
- **Endpoint:** `curl -X POST https://api.perplexity.ai/chat/completions`
- **Model:** `pplx-7b-online` (research optimized)
- **Rate limit:** Generous free tier, scale on demand

#### 14. **Google Gemini API**
- **Status:** Ready. Free tier available.
- **Setup:** Google Cloud project, enable Gemini API, get key
- **Endpoint:** `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash`
- **Model:** `gemini-2.0-flash` (reasoning, fast)
- **Rate limit:** 60 requests/minute on free tier

#### 15. **OpenAI/ChatGPT API** (Optional)
- **Status:** Ready but expensive
- **v1 Decision:** Skip. Use Perplexity + Gemini only.
- **Reason:** Perplexity ≈ research, Gemini ≈ reasoning. Two models enough for MVP.
- **v1.1+:** Add if needed

---

### F. Hosting & DevOps

#### 16. **Vercel** (Frontend)
- **Why:** Zero-config React deployment, free tier sufficient
- **Setup:** `vercel --prod`
- **Features:** Auto-scaling, SSL, global CDN
- **Cost:** Free for this scale

#### 17. **Railway** (Backend) OR **Heroku**
- **Why:** Simple postgres + Node deployment, free tier for v1
- **Setup:** Push to GitHub, auto-deploy
- **Alternative:** Simple VPS (DigitalOcean $4/month) if you want full control
- **Cost:** Free tier covers 100 users

#### 18. **GitHub** (Version Control)
- **Setup:** `git init && git remote add origin <repo>`
- **Workflow:** Trunk-based development (all PRs to main, ship daily)
- **Why:** Cursor integrates seamlessly, easier handoff between team

---

### G. Monitoring & Analytics

#### 19. **Sentry** (Error Tracking, Free)
- **Why:** Catch bugs in production before users complain
- **Setup:** `npm install @sentry/react @sentry/tracing`
- **Cost:** Free tier = 5K events/month

#### 20. **PostHog** (Product Analytics, Free)
- **Why:** Understand how users actually use PIK
- **Setup:** 2-line integration in React
- **Dashboards:** Feature adoption, retention, NPS tracking
- **Cost:** Free tier = 1M events/month

---

## PART 2: PREBUILT TOOLS SUMMARY TABLE

| Tool | Purpose | Cost | v1? | Status | Reason |
|------|---------|------|-----|--------|--------|
| **SuperMemory** | Semantic memory core | Free tier | ✅ | Ready | Production proven |
| **Cursor** | IDE + code generation | Free + API | ✅ | Ready | 10x scaffolding speed |
| **React + Vite** | Frontend framework | Free | ✅ | Ready | Battle-tested |
| **Shadcn/UI** | Component library | Free | ✅ | Ready | Minimal deps |
| **TailwindCSS** | Styling | Free | ✅ | Ready | Dark mode built-in |
| **Tesseract.js** | OCR | Free | ✅ | Ready | Client-side, privacy |
| **Web Speech API** | Voice I/O | Free | ✅ | Ready | Browser native |
| **SQLite** | Database | Free | ✅ | Ready | Zero-ops |
| **Express** | Backend framework | Free | ✅ | Ready | Minimal overhead |
| **Perplexity API** | Research LLM | Free tier | ✅ | Ready | Live data access |
| **Gemini API** | Reasoning LLM | Free tier | ✅ | Ready | Fast, smart |
| **Vercel** | Frontend hosting | Free | ✅ | Ready | Deploy in seconds |
| **Railway** | Backend hosting | Free tier | ✅ | Ready | Zero config |
| **GitHub** | Version control | Free | ✅ | Ready | Cursor integration |
| **Sentry** | Error tracking | Free tier | ✅ | Ready | Production safety |
| **PostHog** | Analytics | Free tier | ✅ | Ready | User insights |
| **LangChain.js** | Orchestration | Free | ❌ | Defer | Complexity not needed v1 |
| **AutoGen** | Multi-agent | Free | ❌ | Monitor | Future (SHAIL phase) |
| **Google Antigravity** | Agent framework | TBD | ❌ | Emerging | Not ready, monitor |
| **MCP** | Knowledge grounding | Free | 🟡 | Partial | Day 2 if time |

---

## PART 3: CURSOR USAGE PATTERNS FOR PIK BUILD

### How to Use Cursor Effectively (Proactive Guide)

#### Pattern 1: Component Scaffolding
```
Cmd+K in Cursor:

"Generate a React component for PIK Quick Popup. 
- Keyboard shortcut: Cmd+Shift+Space
- Shows text input, mic button, menu button
- Dark theme, glassmorphism
- Tailwind CSS only, no component library
- Export as ./src/components/QuickPopup.tsx"

Result: Full working component, includes:
- State management (React.useState)
- Keyboard listeners
- Smooth animations with Framer Motion
- Copy-paste ready
- Time saved: 20 mins → 2 mins
```

#### Pattern 2: API Integration
```
Cmd+K:

"Write a Node.js function to call Perplexity API for research queries.
- Endpoint: https://api.perplexity.ai/chat/completions
- Model: pplx-7b-online
- Stream enabled
- Error handling for rate limits
- Export as ./src/api/perplexity.js"

Result: Production-ready function with:
- Streaming support
- Retry logic
- Proper error messages
- Ready to wire into backend
```

#### Pattern 3: Database Schema & CRUD
```
Cmd+K:

"Create SQLite schema and CRUD functions for PIK memory.
- Table: memories (id, user_id, content, tags, created_at, project_id)
- Functions: createMemory, getMemory, updateMemory, deleteMemory
- Use better-sqlite3
- Include search by tags and project
- Export as ./src/db/memory.js"

Result: Full data layer ready to integrate with Express routes.
```

#### Pattern 4: Backend Routes
```
Cmd+K:

"Create Express.js routes for PIK backend:
- POST /api/memory (save)
- GET /api/memory?project=X&tags=Y (retrieve)
- DELETE /api/memory/:id (delete)
- POST /api/route (model selection)
- Include auth token middleware
- Error handling
- Export as ./src/routes/api.js"

Result: All 4 core routes, ready to mount in Express app.
```

#### Pattern 5: State & Hooks
```
Cmd+K:

"Create a custom React hook usePIKMemory for managing
persistent memory state in React components.
- fetch, save, delete operations
- Loading and error states
- Debounced search
- Export as ./src/hooks/usePIKMemory.ts"

Result: Reusable state management, use in Chat Overlay and Agent View.
```

#### Pattern 6: Testing
```
Cmd+K:

"Write Jest tests for memory CRUD functions.
- Test createMemory with valid/invalid input
- Test retrieval with tags
- Test deletion
- Mock SQLite
- Export as ./src/db/__tests__/memory.test.js"

Result: Test suite ready to integrate with CI/CD.
```

---

## PART 4: 3-DAY BUILD PLAN (15 Hours Total)

### **DAY 1: FOUNDATIONS (5 Hours)**
**Goal:** Working UI skeleton + memory backend ready

#### Hour 0-1: Repo Setup & Scaffolding
- [ ] Create monorepo: `pik-frontend` + `pik-backend`
- [ ] `npm create vite@latest pik-frontend -- --template react`
- [ ] Install deps: `shadcn-ui`, `tailwindcss`, `framer-motion`
- [ ] Backend: `npm init && npm install express cors dotenv better-sqlite3`
- [ ] Git init, first commit

**Time saved by Cursor:** 30 mins → 5 mins

#### Hour 1-2: Quick Popup UI Component
**Cursor Cmd+K:** Generate QuickPopup React component
- Text input + mic button
- Dark theme, glassmorphism
- Keyboard shortcut handler (Cmd+Shift+Space)
- State: `text`, `isOpen`, `isListening`

**Output:** `./src/components/QuickPopup.tsx` (production-ready, 150 lines)

#### Hour 2-3: Chat Overlay UI Component
**Cursor Cmd+K:** Generate ChatOverlay component
- Right-side panel
- Chat bubbles (user + AI)
- Scroll history
- Input box at bottom
- File drag-drop (prepare for screenshots)

**Output:** `./src/components/ChatOverlay.tsx` (production-ready, 200 lines)

#### Hour 3-4: SuperMemory Backend Integration
**Cursor Cmd+K:** Generate SQLite memory layer
- Schema: `memories (id, user_id, content, tags, created_at, project_id)`
- CRUD functions: `createMemory`, `getMemory`, `deleteMemory`, `searchMemory`
- Integration with SuperMemory API wrapper

**Output:** `./src/db/memory.js` (production-ready, 100 lines)

#### Hour 4-5: Express Routes for Memory
**Cursor Cmd+K:** Generate backend routes
- POST `/api/memory` → createMemory
- GET `/api/memory?project=X` → searchMemory
- DELETE `/api/memory/:id` → deleteMemory
- POST `/api/session` → create session for user

**Output:** `./src/routes/memory.js` (production-ready, 80 lines)

**Deliverable:** 
- ✅ Quick Popup opens on Cmd+Shift+Space
- ✅ Chat Overlay shows on right (mockup)
- ✅ Memory CRUD tested with Postman
- ✅ Repo ready for team (scaffold is 90% done)

---

### **DAY 2: INTELLIGENCE (5 Hours)**
**Goal:** Model routing working + screenshot pipeline ready

#### Hour 0-1: Model Router Logic
**Cursor Cmd+K:** Generate intent classifier
- Rules-based: if keywords `search, find, latest` → Perplexity
- If `plan, structure, steps` → Gemini
- Default → Gemini (reasoning)
- Add confidence scores

**Output:** `./src/api/router.js` (production-ready, 80 lines)

#### Hour 1-2.5: Perplexity API Integration
**Cursor Cmd+K:** Generate Perplexity wrapper
- Call Perplexity endpoint
- Handle streaming
- Fallback if rate limited
- Return structured response

**Output:** `./src/api/perplexity.js` (production-ready, 100 lines)

**Test:** Call with sample query "What's new in AI?" → verify response

#### Hour 2.5-4: Screenshot + OCR Pipeline
**Cursor Cmd+K:** Generate screenshot capture + Tesseract.js integration
- Frontend: Capture screenshot with html2canvas
- Send to backend
- OCR extraction via Tesseract.js
- Summary via Gemini (100-word summary)
- Save to memory with tag `screenshot-context`

**Output:** 
- `./src/components/ScreenshotButton.tsx`
- `./src/api/ocr.js`
- `./src/routes/screenshot.js`

#### Hour 4-5: Wire Everything Together
- Connect QuickPopup input → Router → Perplexity/Gemini → ChatOverlay response
- Add memory retrieval to Chat (prepend context to prompt)
- Test end-to-end flow:
  1. Type query in Quick Popup
  2. Router picks model
  3. Memory context added
  4. Response in Chat Overlay
  5. Save to memory button

**Deliverable:**
- ✅ Router makes model decisions
- ✅ Perplexity API calls work
- ✅ Screenshot capture works
- ✅ OCR returns summaries
- ✅ End-to-end chat flow works

---

### **DAY 3: POLISH & AGENT VIEW (5 Hours)**
**Goal:** Simulated Agent View ready + deployment ready

#### Hour 0-1: Simulated Agent View Component
**Cursor Cmd+K:** Generate Agent View UI
- Screen mockup (placeholder image or user-provided)
- Action log pane (right side)
- Fake cursor animation
- Status: "Checking Perplexity...", "Searching memory...", "Summarizing..."

**Output:** `./src/components/AgentView.tsx` (production-ready, 150 lines)

#### Hour 1-2: UI Polish & Dark Mode
**Cursor Cmd+K:** Improve styling
- Ensure glassmorphism on popup
- Smooth transitions
- Mobile responsive
- Dark mode verified (already in Tailwind)
- Accessibility: ARIA labels, keyboard navigation

**Output:** Updated components with accessibility audit

#### Hour 2-3: Export & Developer Mode
**Cursor Cmd+K:** Generate session export
- POST `/api/export` → downloads JSON of entire session
- Includes: messages, memory, metadata
- Include dev tools: show request/response logs

**Output:** `./src/components/ExportButton.tsx` + `./src/routes/export.js`

#### Hour 3-4: Deployment Prep
- [ ] Add `.env.example`
- [ ] Write quick start README
- [ ] Deploy frontend to Vercel: `vercel --prod`
- [ ] Deploy backend to Railway
- [ ] Test live (frontend → backend API calls)
- [ ] Add Sentry error tracking
- [ ] Add PostHog analytics

**Output:**
- Frontend live at: `https://pik-frontend.vercel.app`
- Backend live at: `https://pik-backend.railway.app`

#### Hour 4-5: Demo Script & QA
- Write 3-minute demo script:
  1. Show Quick Popup keyboard shortcut
  2. Ask research query, show Perplexity results
  3. Show memory persisting across sessions
  4. Show screenshot context
  5. Show Agent View narration
- QA checklist:
  - [ ] No console errors
  - [ ] All routes respond
  - [ ] Memory persists after refresh
  - [ ] OCR works on screenshots
  - [ ] Deployment doesn't timeout

**Deliverable:**
- ✅ Agent View component working
- ✅ Live deployments working
- ✅ Demo script ready
- ✅ Beta-ready product

---

## PART 5: OUTCOME METRICS (By End of Day 3)

### Technical
- **Code quality:** 0 critical errors, <5 warnings
- **Performance:** Quick Popup opens in <500ms, chat response <3s
- **Reliability:** 99%+ uptime, zero unhandled exceptions

### Product
- **Feature parity:** All 5 core features working (Popup, Chat, Memory, Router, Agent View)
- **UX:** Can complete a full flow (ask → route → remember → retrieve) in <2 minutes
- **Deployment:** Live on Vercel + Railway, publicly accessible

### Team
- **Clarity:** Everyone knows what they're building and why
- **Handoff:** Code is well-commented, easy for new engineer to understand
- **Documentation:** README + API docs for future team

---

## PART 6: CURSOR WORKFLOW CHECKLIST

Before Each Day, Use Cursor to:

1. **Open command palette (Cmd+K)** with single request:
   ```
   "I'm building PIK, a personal AI OS. Here's what I need today:
   - [Component 1]
   - [Component 2]
   - [API Integration]
   - [Database layer]
   
   Generate all these as separate files, production-ready, with comments.
   Use React + Node + SQLite. Deploy to Vercel + Railway."
   ```

2. **Have Cursor generate the scaffolding** (10-15 mins, usually)

3. **Copy generated code into files**

4. **Manual QA:** Does it work? Need tweaks?

5. **Commit to Git**

6. **Move to next task**

---

## APPENDIX: Cursor Configuration for PIK

Create `.cursor` in repo root:

```yaml
# PIK Cursor Rules
rules:
  - name: "PIK Architecture"
    description: "Always follow PIK design: local-first, memory-centric, lightweight"
    patterns:
      - "prefer React hooks over class components"
      - "use SQLite for data, avoid cloud unless necessary"
      - "keep frontend bundle <3MB"
      - "comment all external API calls with rate limits"

  - name: "API Naming"
    patterns:
      - "Perplexity calls = research/search intent"
      - "Gemini calls = reasoning/planning intent"
      - "Memory calls = persistence layer"

  - name: "Error Handling"
    patterns:
      - "Wrap all API calls in try/catch"
      - "Provide user-friendly error messages"
      - "Log errors to Sentry"

globals:
  apiKey: ${PERPLEXITY_API_KEY}
  geminiKey: ${GEMINI_API_KEY}
  database: "sqlite:///pik.db"
  environment: ${NODE_ENV}
```

---

**Build Status:** Ready for Kick-Off  
**Estimated Ship Date:** January 23, 2026 (Day 3 completion)  
**Team:** See delegation document (separate)