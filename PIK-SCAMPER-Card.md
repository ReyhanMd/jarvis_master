# PIK: SCAMPER ADAPTATION REFERENCE CARD
## For Quick Decisions During Sprint

---

## SCAMPER CHEAT SHEET

**Use this when you hit a roadblock: "Should we build X or adapt Y?"**

### SUBSTITUTE (Replace one element)

```
QUESTION: What if API is slow?
SUBSTITUTE: Swap Perplexity → Gemini (instant)

QUESTION: What if Vercel deployment fails?
SUBSTITUTE: Deploy to Netlify instead (same frontend, different host)

QUESTION: What if SQLite corrupts?
SUBSTITUTE: Swap local DB → JSON file (same persistence, simpler)

ACTION: Use this when PRIMARY tool fails
TIME: < 5 minutes to switch
RISK: Low (both solutions work)
```

### COMBINE (Add elements together)

```
QUESTION: Should we add monitoring?
COMBINE: Sentry (errors) + PostHog (analytics) + Railway (logs)

QUESTION: Should we add more features?
COMBINE: Keep core 6, add voice input layer → future

QUESTION: Should we combine models?
COMBINE: Perplexity + Gemini in one router (already doing this)

ACTION: Use this when you have extra capacity
TIME: > 30 minutes per feature
RISK: Medium (scope creep)
```

### ADAPT (Repurpose existing)

```
QUESTION: Can we use SHAIL routing in PIK?
ADAPT: YES! Use SHAIL keyword-based router directly

QUESTION: Can we reuse SHAIL memory schema?
ADAPT: YES! Memories table works identically

QUESTION: Can we adapt Cursor prompts?
ADAPT: YES! Use our Cursor library per person

ACTION: Use this for pre-existing components
TIME: < 10 minutes to integrate
RISK: Low (proven to work)
```

### MODIFY (Change existing)

```
QUESTION: Should we modify Tailwind colors?
MODIFY: YES, but only after MVP ships

QUESTION: Should we modify DB schema?
MODIFY: NO (current schema is perfect for MVP)

QUESTION: Should we modify API routes?
MODIFY: Only if tests catch bugs

ACTION: Use this sparingly (changes can break)
TIME: 15-30 minutes per modification
RISK: High (regression bugs)
```

### PUT TO NEW USE (Repurpose for different context)

```
QUESTION: Can we use localStorage for offline mode?
PUT TO NEW USE: YES! Cache memories locally, sync when online

QUESTION: Can we use memory table for search?
PUT TO NEW USE: YES! Add search index on Day 4

QUESTION: Can we use Sentry for performance tracking?
PUT TO NEW USE: YES! Already monitoring response times

ACTION: Use this for Day 2+ features
TIME: 30-60 minutes per new use case
RISK: Medium (need to test thoroughly)
```

### ELIMINATE (Remove)

```
QUESTION: Do we need LangChain?
ELIMINATE: YES, delete it (not needed, keep simple)

QUESTION: Do we need PostgreSQL?
ELIMINATE: YES, SQLite is better for MVP

QUESTION: Do we need authentication?
ELIMINATE: YES, skip for MVP (add Day 5+)

QUESTION: Do we need beautiful animations?
ELIMINATE: YES, skip (functional design is enough)

ACTION: Use this to cut scope + ship faster
TIME: 0 minutes (faster by NOT building)
RISK: Low (scope reduction is always safe)
```

### REVERSE/RETHINK (Do opposite)

```
QUESTION: Instead of calling Perplexity API, use local AI?
REVERSE: NO (local AI slower, API faster for MVP)

QUESTION: Instead of storing in SQLite, use file system?
REVERSE: NO (DB faster, more reliable)

QUESTION: Instead of Cmd+Shift+Space, use button?
REVERSE: YES (button is fallback if shortcut fails)

ACTION: Use this to explore alternatives
TIME: 5-10 minutes per option
RISK: Medium (might discover better solution)
```

---

## QUICK DECISION MATRIX

**"Should we build X or adapt Y?"**

```
┌─────────────────────────────────────────────────────────────┐
│ DECISION TREE: What to Build vs What to Adapt              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Does component exist?                                       │
│ ├─ YES (Perplexity, Gemini, Cursor, Vercel, Railway)      │
│ │  └─ ADAPT it (use as-is or modify minimally)            │
│ │                                                           │
│ └─ NO (custom router, memory display, export)             │
│    └─ BUILD it (code new, test thoroughly)               │
│                                                             │
│ Does component work for MVP?                               │
│ ├─ YES → Keep it, ship faster                              │
│ │                                                           │
│ └─ NO → Replace it (SUBSTITUTE)                           │
│    ├─ API too slow? → Use Gemini                          │
│    ├─ Deployment fails? → Use different host              │
│    └─ Database corrupts? → Reset file + restart           │
│                                                             │
│ Is there time for extra features?                          │
│ ├─ YES (>30 min) → COMBINE features (voice, Claude)      │
│ │                                                           │
│ └─ NO (< 30 min) → ELIMINATE features (trim scope)        │
│    ├─ Cut: Voice input (add Day 4)                        │
│    ├─ Cut: Claude integration (add Week 2)                │
│    ├─ Cut: Notion sync (add Week 3)                       │
│    └─ Ship: Core 6 features only                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## FAILSAFE FLOWCHART

**"What do I do when X breaks?"**

```
┌─────────────────────────────────────────────────────────────┐
│ PROBLEM: Something isn't working                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Step 1: Check where error is?                              │
│ ├─ Browser console? → Frontend issue (Sreekar)            │
│ ├─ Sentry dashboard? → Backend issue (Ritwik)             │
│ ├─ Vercel logs? → Deployment issue (Hiren)                │
│ └─ Railway logs? → Deployment issue (Hiren)               │
│                                                             │
│ Step 2: Is it Tier 1 (< 5 min fix) or Tier 2+ (> 5 min)?│
│ │                                                           │
│ ├─ Tier 1: Quick fix                                       │
│ │  ├─ Missing env var? → Add to Vercel/Railway            │
│ │  ├─ Console error? → Fix code locally, push             │
│ │  ├─ API timeout? → Increase timeout (1 line change)     │
│ │  └─ FIX TIME: < 5 min                                    │
│ │                                                           │
│ └─ Tier 2: Fallback strategy                               │
│    ├─ Perplexity down? → Use Gemini (router logic)         │
│    ├─ Deploy fails? → Revert to last working version       │
│    ├─ API slow? → Show spinner + cache response            │
│    ├─ Shortcut fails? → Use button fallback                │
│    └─ FIX TIME: 5-30 min                                   │
│                                                             │
│ Step 3: Have I tried the failsafe?                         │
│ ├─ YES → Working? → Ship it (temporary fix)                │
│ │                                                           │
│ └─ NO → Try failsafe strategy (see below)                  │
│                                                             │
│ Step 4: Still broken?                                      │
│ ├─ Call team Slack: "Blocked on [X], need help"          │
│ ├─ Max wait: 15 minutes                                    │
│ └─ If not resolved: Implement workaround, document        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## ADAPTATION PATHS (By Component)

### BACKEND (Ritwik)

```
ISSUE → ADAPT STRATEGY → TIME → OUTCOME

Perplexity timeout
→ Router switches to Gemini (1 line change)
→ 1 minute
→ User gets response (reasoning instead of research)

Express port conflict
→ Change PORT env var (5000 → 5001)
→ 2 minutes
→ API listens on new port, update frontend

SQLite file corrupted
→ Delete ./data/pik.db (schema recreates)
→ 2 minutes
→ API restarts, memories reset (acceptable)

Sentry not reporting
→ Check DSN, redeploy with correct key
→ 5 minutes
→ Errors start appearing in dashboard

API response slow (>5s)
→ Add response caching + lower timeout
→ 15 minutes
→ Same UX, better performance
```

### FRONTEND (Sreekar)

```
ISSUE → ADAPT STRATEGY → TIME → OUTCOME

Cmd+Shift+Space conflicts
→ Add QueryFAB button (Floating Action Button)
→ 10 minutes
→ Users can click button if shortcut fails

API timeout
→ Show "Generating..." message + increase timeout
→ 5 minutes
→ User knows app is working, less frustration

Memory list too slow
→ Paginate results (load 20 at a time)
→ 20 minutes
→ Faster rendering, better UX

localStorage full
→ Implement cache eviction (delete oldest)
→ 15 minutes
→ Keeps 1000 recent memories, deletes old ones

Export not working
→ Check Blob creation, test locally with console
→ 10 minutes
→ Usually simple typo or format issue
```

### INFRASTRUCTURE (Hiren)

```
ISSUE → ADAPT STRATEGY → TIME → OUTCOME

Vercel build fails
→ Check env var, add VITE_API_URL, redeploy
→ 5 minutes
→ Build succeeds, frontend live

Railway deployment fails
→ Check logs, restart container, redeploy
→ 5 minutes
→ API recovers (usually memory issue)

API env var wrong
→ Update in Railway dashboard, trigger redeploy
→ 2 minutes
→ API connects to correct external services

Monitoring not active
→ Verify Sentry DSN, re-deploy with correct key
→ 5 minutes
→ Errors start appearing in Sentry

Database out of space
→ Railway auto-scales storage (no action)
→ 1 minute (automatic)
→ App keeps running, zero downtime
```

---

## DECISION FRAMEWORK: "Build New or Use Existing?"

```
┌────────────────────────────────────────────────┐
│ COMPONENT DECISION TABLE                       │
├────────────────────────────────────────────────┤
│                                                │
│ Component          │ Exists? │ Use? │ Time   │
│ ──────────────────┼─────────┼──────┼────── │
│ Express API        │ YES     │ YES  │ 0 min │
│ SQLite DB          │ YES     │ YES  │ 0 min │
│ Perplexity API     │ YES     │ YES  │ 0 min │
│ Gemini API         │ YES     │ YES  │ 0 min │
│ Vercel hosting     │ YES     │ YES  │ 0 min │
│ Railway hosting    │ YES     │ YES  │ 0 min │
│ Cursor scaffolding │ YES     │ YES  │ 0 min │
│ React components   │ NO      │ BUILD│ 4 hrs │
│ Query router       │ YES*    │ ADAPT│ 1 hr  │
│ Memory display     │ NO      │ BUILD│ 3 hrs │
│ Authentication     │ YES     │ SKIP │ ----- │
│ Payment processing │ YES     │ SKIP │ ----- │
│ Analytics          │ YES     │ SKIP │ ----- │
│                                                │
│ *From SHAIL framework                         │
│                                                │
└────────────────────────────────────────────────┘
```

---

## CURSOR PROMPT DECISION TREE

**"Which Cursor prompt should I use?"**

```
What are you building?

├─ Backend scaffolding
│  └─ PROMPT 1: Backend Scaffold (Express boilerplate)
│
├─ Database schema
│  └─ PROMPT 2: SQLite Schema (tables, indexes)
│
├─ Perplexity integration
│  └─ PROMPT 3: Perplexity Integration + Router
│
├─ Export functionality
│  └─ PROMPT 4: Export Endpoint (JSON download)
│
├─ Error handling
│  └─ PROMPT 5: Error Handling + Sentry
│
├─ React UI
│  └─ PROMPT 1: React Scaffold + Dark Theme
│
├─ API integration
│  └─ PROMPT 2: API Hooks + Backend Integration
│
├─ Memory management
│  └─ PROMPT 3: Memory List + Export
│
├─ Keyboard shortcut
│  └─ PROMPT 4: Keyboard Shortcut + Popup
│
├─ Error handling
│  └─ PROMPT 5: Error Handling + Toast
│
├─ Vercel deployment
│  └─ PROMPT 1: Vercel Config
│
├─ Railway deployment
│  └─ PROMPT 2: Railway Config
│
├─ CI/CD pipeline
│  └─ PROMPT 3: GitHub Actions CI/CD
│
├─ Error monitoring
│  └─ PROMPT 4: Sentry Integration
│
└─ Monitoring dashboard
   └─ PROMPT 5: Monitoring Dashboard (runbook)
```

---

## EMERGENCY ROLLBACK PROCEDURES

**"Everything is broken, what do I do?"**

### Scenario 1: Frontend Won't Load

```
PROBLEM: pik.vercel.app shows 404 or blank page

IMMEDIATE ACTIONS:
1. Check Vercel dashboard → Build status (red?)
2. If red: Check build logs (missing env var?)
3. Add missing env var to Vercel
4. Trigger redeploy (click "Redeploy" button)
5. If still broken: Revert to last working build

ROLLBACK COMMAND:
→ Vercel dashboard → "Deployments" tab
→ Click last working deployment
→ Click "Promote to Production"
→ Your app is live again (2 minutes total)

RECOVERY TIME: 2-5 minutes
RESULT: App back online, investigating ongoing
```

### Scenario 2: Backend API Down

```
PROBLEM: pik-api.railway.app returns 500 or timeout

IMMEDIATE ACTIONS:
1. Check Railway dashboard → Service status (yellow?)
2. Check Railway logs → Look for errors
3. If crash: Click "Restart" button in Railway
4. If out of memory: Increase Railway memory (1 click)
5. If deploy failed: Revert to last working version

ROLLBACK COMMAND:
→ Railway dashboard → "Deployments" tab
→ Click last working deployment
→ Click "Deploy" (re-runs last working)
→ API comes back online (2 minutes)

RECOVERY TIME: 2-5 minutes
RESULT: API responding, investigating ongoing
```

### Scenario 3: Database Corrupted

```
PROBLEM: Queries return garbage or "DB locked" error

IMMEDIATE ACTIONS:
1. SSH into Railway (if possible) or use Railway terminal
2. Delete ./data/pik.db (or backup to ./data/pik.db.bak)
3. Restart Railway service
4. Schema auto-recreates
5. Memory starts fresh (acceptable for MVP)

ROLLBACK COMMAND:
→ Railway terminal:
   rm -f ./data/pik.db
   npm start (restarts service)
→ Schema recreates, app back online (1 minute)

RECOVERY TIME: 1 minute
RESULT: Database reset, memories lost (acceptable), app restored
```

### Scenario 4: Both Services Down

```
PROBLEM: Vercel AND Railway both broken (rare)

IMMEDIATE ACTIONS:
1. Don't panic—this is what failsafes are for
2. Frontend: Revert to last known-good version
3. Backend: Revert to last known-good version
4. If reverts don't work: Deploy to fallback hosts
   - Frontend: Netlify (different host)
   - Backend: Heroku (different host)
5. Update URLs in DNS (or hardcode new URLs)

DEPLOYMENT COMMAND:
→ For Frontend (Netlify):
   npm run build
   netlify deploy --prod --dir=dist
   
→ For Backend (Heroku):
   npm start
   heroku deploy (if configured)

RECOVERY TIME: 15-30 minutes (new hosts)
RESULT: App live on different infrastructure, zero data loss
```

---

## MONITORING DASHBOARD CHECKLIST

**Check these every 30 minutes during sprint:**

```
☐ VERCEL (Frontend Status)
  ├─ Build status: Green or Red?
  ├─ Deployment: Latest from main?
  ├─ URL reachable: pik.vercel.app loads?
  └─ Error rate: Check Vercel analytics (should be 0%)

☐ RAILWAY (Backend Status)
  ├─ Service status: Running or Crashed?
  ├─ CPU usage: < 80% or high?
  ├─ Memory usage: < 512MB or high?
  ├─ HTTP status: All 200 or errors?
  └─ Uptime: 100% or drops?

☐ SENTRY (Error Tracking)
  ├─ Recent errors: Any new ones?
  ├─ Error trend: Increasing or stable?
  ├─ Critical errors: Any 5xx status codes?
  └─ Alert fired: Did team get notified?

☐ API PERFORMANCE
  ├─ Response time: < 1 second or > 1 second?
  ├─ Query success rate: > 95% or lower?
  ├─ Timeout rate: < 1% or higher?
  └─ Database queries: < 100ms or slower?
```

---

## TEAM COMMUNICATION PROTOCOL

**How to communicate blockers without meetings:**

```
BLOCKER URGENCY SCALE:

🔴 CRITICAL (Kill the demo)
   → DM person directly + Slack @channel
   → Phone call if no response in 5 min
   → Example: "API broken, Perplexity failing"
   
🟡 URGENT (Demo works but degraded)
   → Slack message in #pik channel
   → Wait 15 min for response
   → If blocked: Implement workaround
   → Example: "Queries taking 10 seconds"

🟢 NORMAL (Can work around)
   → Slack thread (not urgent)
   → Response by EOD is fine
   → Example: "Should we use green or blue button?"

ESCALATION PATH:
No response in 15 min → DM person directly
No response in 30 min → Call person
No resolution in 45 min → Reyhan makes decision

BLOCKING QUESTIONS:
- What info do you need from me?
- What's the time estimate?
- What's the workaround if this takes too long?
```

---

**Print this. Reference during sprint. Share with team.**

**Questions? Slack Reyhan.**

**No time for meetings. Move fast. Communicate async.**

**See you at SHIP 🚀**
