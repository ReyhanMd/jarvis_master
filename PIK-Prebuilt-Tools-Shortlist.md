# PIK BUILD: PREBUILT TOOLS & INTEGRATIONS SHORTLIST
## What You're Using + What You Should Add

**Status:** January 20, 2026 (Pre-MVP Build)

---

## PRIMARY TOOLS (Already Chosen)

### 1. **Cursor (AI-Powered IDE)** ✅ MANDATORY
- **Why:** 10x scaffolding speed with Cmd+K code generation
- **Usage:** Generate React components, Express routes, database schemas
- **Cost:** $20/month (Pro)
- **Alternative:** GitHub Copilot (slower, less integrated)

**How to use for PIK:**
```
Cmd+K → "Generate React QuickPopup component with dark theme"
Ctrl+K → "Create Express /api/memory route"
```

### 2. **SuperMemory by Dravyaa Shah** ✅ REFERENCE
- **Why:** Browser extension for memory capture (we're reimplementing as native app)
- **Usage:** Study their UX, memory tagging system, export flow
- **Cost:** Free (open source on GitHub)
- **Learning:** Their approach to memory + browser integration

**How to learn from it:**
- Clone: github.com/dravyaa/SuperMemory
- Read: Their memory schema + tagging philosophy
- Adapt: Apply their UX patterns to PIK (but better router + multi-model)

### 3. **Google Antigravity** (?)
**Status:** Not found / Unclear reference

Possible interpretations:
- Google's internal ML framework?
- Product code-name you heard?
- Confused with Google Cloud offerings?

**Action:** Clarify this. If you meant Google Cloud:
- **Google Cloud (Vertex AI):** For Gemini API, Cloud Storage
- **Cost:** Pay-as-you-go ($0.01-$0.10 per 1M tokens depending on model)

---

## TIER 1: ESSENTIAL PREBUILTS (MVP)

These are non-negotiable for shipping in 3 days.

### 1. **Perplexity API** ✅ ESSENTIAL
- **Purpose:** Research routing (live web search)
- **Cost:** Free tier exists, ~$0.005 per query at scale
- **Integration:** POST to `https://api.perplexity.ai/chat/completions`
- **Docs:** https://docs.perplexity.ai
- **What you need:**
  ```javascript
  // Backend code (Ritwik will handle)
  async function queryPerplexity(query) {
    const response = await fetch('https://api.perplexity.ai/chat/completions', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${PERPLEXITY_API_KEY}` },
      body: JSON.stringify({
        model: 'pplx-7b-online',
        messages: [{ role: 'user', content: query }],
        stream: false
      })
    });
    return response.json();
  }
  ```

### 2. **Gemini API** ✅ ESSENTIAL
- **Purpose:** Fallback reasoning + planning
- **Cost:** Free tier (up to 60 requests/min), then ~$0.002 per 1M tokens
- **Integration:** `https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent`
- **Docs:** https://ai.google.dev/docs
- **What you need:**
  ```javascript
  // Backend
  async function queryGemini(query) {
    const response = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=${GEMINI_API_KEY}`,
      {
        method: 'POST',
        body: JSON.stringify({
          contents: [{ parts: [{ text: query }] }]
        })
      }
    );
    return response.json();
  }
  ```

### 3. **Tesseract.js** ✅ ESSENTIAL
- **Purpose:** Screenshot OCR (text extraction)
- **Cost:** Free (open source)
- **Installation:** `npm install tesseract.js`
- **What you need:**
  ```javascript
  // Backend or frontend
  const Tesseract = require('tesseract.js');
  
  Tesseract.recognize(imageUrl, 'eng')
    .then(({ data: { text } }) => console.log(text))
  ```

### 4. **Better-SQLite3** ✅ ESSENTIAL
- **Purpose:** Local database (memory persistence)
- **Cost:** Free (open source)
- **Installation:** `npm install better-sqlite3`
- **What Ritwik uses:**
  ```javascript
  const Database = require('better-sqlite3');
  const db = new Database('pik.db');
  db.exec('CREATE TABLE memories (id, content, tags, ...)');
  ```

### 5. **Vercel** ✅ ESSENTIAL
- **Purpose:** Frontend hosting + auto-deploy
- **Cost:** Free tier (for this scale)
- **Setup:** Connect GitHub repo, auto-deploy on push
- **URL:** https://vercel.com

### 6. **Railway** ✅ ESSENTIAL
- **Purpose:** Backend hosting + database
- **Cost:** Free tier ($5/month credit)
- **Setup:** Connect GitHub, deploy Express app
- **URL:** https://railway.app

---

## TIER 2: OPTIONAL AUGMENTATIONS (Add if time permits)

These are nice-to-haves, but add serious value if integrated.

### 1. **Sentry (Error Tracking)** 🟡 HIGHLY RECOMMENDED
- **Purpose:** Monitor errors in production, get alerted
- **Cost:** Free tier (50k events/month)
- **Setup:** `npm install @sentry/react @sentry/node`
- **Why:** Catch bugs before users complain

**Add to backend:**
```javascript
import * as Sentry from "@sentry/node";
Sentry.init({ dsn: process.env.SENTRY_DSN });

app.use((err, req, res, next) => {
  Sentry.captureException(err);
  res.status(500).json({ error: 'Server error' });
});
```

### 2. **PostHog (Analytics)** 🟡 RECOMMENDED
- **Purpose:** Track feature usage, user behavior, retention
- **Cost:** Free tier (up to 1M events/month)
- **Setup:** `npm install posthog-js`
- **Why:** Understand what users actually do with PIK

**Add to frontend:**
```javascript
import posthog from 'posthog-js';
posthog.init(process.env.REACT_APP_POSTHOG_KEY, { api_host: 'https://us.posthog.com' });
```

**Dashboard:** See DAU, feature adoption, conversion funnels

### 3. **Stripe** 🟡 FUTURE (Post-MVP)
- **Purpose:** Payment processing (Pro tier, $9.99/month)
- **Cost:** 2.9% + $0.30 per transaction
- **Timeline:** Week 2 (after MVP shipped)
- **Why:** Convert early adopters to paying customers

**For now:** Just stub out pricing page. Stripe integration Day 4+.

### 4. **Framer Motion** ✅ INCLUDED
- **Purpose:** Smooth animations (Agent View)
- **Cost:** Free (open source)
- **Installation:** `npm install framer-motion`
- **Sreekar uses:**
  ```javascript
  import { motion } from "framer-motion";
  
  <motion.div animate={{ x: 100 }} transition={{ duration: 0.5 }} />
  ```

### 5. **Tailwind CSS** ✅ INCLUDED
- **Purpose:** Utility-first styling (dark theme)
- **Cost:** Free
- **Installation:** Already in Vite template
- **Usage:** `<div className="bg-slate-900 text-white dark:bg-slate-950">`

---

## TIER 3: FUTURE INTEGRATIONS (After MVP, Week 2+)

### 1. **Claude API** (Week 2)
- **Purpose:** Code generation + deep thinking queries
- **Cost:** Similar to Gemini
- **Why:** Users will ask for "Claude's take on this"
- **Routing:** Add keyword: "code, function, debug" → Claude

### 2. **Notion API** (Week 3)
- **Purpose:** Sync PIK memories to Notion database
- **Cost:** Free (API access included)
- **Why:** Researchers want persistent backup + organization
- **Feature:** Button: "Archive to Notion"

### 3. **Anthropic's Prompt Caching** (Week 3)
- **Purpose:** Cache long-context research sessions
- **Cost:** Included with Claude API
- **Why:** Faster, cheaper multi-turn conversations
- **Benefit:** Store 100k tokens of context, recall instantly

### 4. **LangChain** (Maybe Never)
- **Status:** SKIP for MVP
- **Why:** Adds complexity, PIK is intentionally lightweight
- **Alternative:** Build routing logic ourselves (simpler, faster)

### 5. **BrainSTEM Agent Framework** (Future)
- **Purpose:** Integrate with other agents
- **Timeline:** Month 2+
- **Why:** Let other AI agents query PIK's memory

### 6. **Replicate** (GPU inference)
- **Purpose:** Run local LLMs (Llama, Mistral)
- **Timeline:** When users want offline mode
- **Cost:** ~$0.001 per 1M tokens
- **Why:** Privacy-conscious users can opt in to local-only

---

## RECOMMENDED ADDITIONS (Not Built Into Your Request)

### For Quality Assurance

**1. Jest (Testing)**
- `npm install jest @testing-library/react`
- Write tests for router logic, memory CRUD
- Target: 80% coverage for critical paths
- **Cost:** Free

**2. Prettier (Code Formatting)**
- `npm install prettier`
- Enforce consistent code style
- Run on pre-commit hook
- **Cost:** Free

**3. ESLint (Code Linting)**
- `npm install eslint`
- Catch bugs before they ship
- **Cost:** Free

### For Performance

**1. Lighthouse CI**
- Automated performance testing
- Free tier on GitHub Actions
- Monitor page load times
- **Cost:** Free

**2. Bunjs (Faster bundling)**
- Alternative to Webpack (inside Vite)
- Already using Vite (faster than CRA)
- **Cost:** Free

### For Developer Experience

**1. GitHub Actions (CI/CD)**
- Already using (auto-deploy on push)
- Add: linting, testing before deploy
- **Cost:** Free (for public repo)

**2. Conventional Commits**
- Enforce commit message format
- `feat: add memory CRUD`, `fix: router bug`
- Generates changelog automatically
- **Cost:** Free

---

## INTEGRATION CHECKLIST (By Day)

### Day 1 Setup
- [ ] Cursor Pro installed ($20/month)
- [ ] Perplexity API key obtained
- [ ] Gemini API key obtained
- [ ] SQLite initialized (better-sqlite3)
- [ ] Tesseract.js ready for OCR
- [ ] Vercel project created
- [ ] Railway project created

### Day 2 Integration
- [ ] Perplexity calls working (test with sample query)
- [ ] Gemini calls working (test with sample query)
- [ ] Router logic implemented
- [ ] Sentry initialized (error tracking)
- [ ] PostHog initialized (analytics)

### Day 3 Polish
- [ ] Sentry dashboard shows 0 errors (or only expected)
- [ ] PostHog shows 100+ events (user interactions)
- [ ] Live Vercel + Railway URLs working
- [ ] Export functionality tested

### After MVP (Week 2+)
- [ ] Stripe integration (payments)
- [ ] Claude API integration (new queries)
- [ ] Notion sync beta

---

## API KEY MANAGEMENT (.env template)

Create `.env` file (never commit to git):

```env
# Perplexity
PERPLEXITY_API_KEY=pplx-xxxxxx

# Google Gemini
GEMINI_API_KEY=AIzaSyxxxxxxxxx

# Deployment
PORT=3000
VERCEL_URL=https://pik.vercel.app
RAILWAY_URL=https://pik-backend.railway.app

# Monitoring
SENTRY_DSN=https://xxx@sentry.io/xxx
REACT_APP_POSTHOG_KEY=phc_xxxxxxx

# (Future)
CLAUDE_API_KEY=sk-ant-xxxxxx
NOTION_API_KEY=secret_xxxxxxxx
STRIPE_API_KEY=sk_live_xxxxxxx
```

**Security rule:** Never commit .env to git. Use environment variables in CI/CD platforms (Vercel/Railway).

---

## COST BREAKDOWN (Year 1)

| Service | Cost | Notes |
|---------|------|-------|
| Cursor | $20/month | Essential for scaffolding |
| Perplexity API | $50-200/month | $0.005 per query, scales with users |
| Gemini API | $10-50/month | Free tier + pay-as-go |
| Tesseract.js | Free | Open source |
| Better-SQLite3 | Free | Open source |
| Vercel | Free-20/month | Free tier sufficient for MVP |
| Railway | Free-50/month | Free tier + $5 credit |
| Sentry | Free | Free tier (50k events) |
| PostHog | Free | Free tier (1M events) |
| Stripe | 2.9% + $0.30/transaction | Only if revenue exists |
| **TOTAL (MVP)** | **~$150/month** | For 1,000 users |
| **TOTAL (Scale, 50k users)** | **~$500/month** | Mostly API costs |

**Pricing reminder:** If 30% of users convert to Pro ($9.99/month):
- 1,000 users → 300 Pro → $3,000 MRR
- Net margin: ~$2,850/month (92%)

**At scale:**
- 50,000 users → 15,000 Pro → $150,000 MRR
- Cost: ~$500/month API
- Net margin: ~$149,500/month (99.7%)

---

## WHAT TO SKIP

### ❌ Do NOT Use
- **LangChain** (too much abstraction, not needed)
- **Anthropic's Function Calling** (overkill for MVP)
- **Kubernetes** (Railway handles scaling)
- **PostgreSQL** (SQLite is simpler, works great for v1)
- **GraphQL** (REST is fine, simpler)
- **Next.js** (Vite is faster for SPA)
- **Tailwind UI** (build own with Tailwind utilities)
- **Firebase** (Railway + Vercel better for this stack)

### 🟡 Use With Caution
- **Redux** (Context + hooks sufficient)
- **Electron** (start web-first, desktop later)
- **Kubernetes** (not needed, Railway auto-scales)
- **Docker Compose** (for local dev only)

---

## RECOMMENDED READING

From your attached files (to inform design):

1. **A Practical Guide for Designing Agentic AI Workflows** (your file 39)
   - Study their agent architecture patterns
   - Learn about memory interfaces
   - Understand routing strategies

2. **Step-GUI Technical Report** (your file 34)
   - UI automation patterns (Agent View animation reference)
   - Action planning logic (inform router)

3. **LongVideoAgent** (your file 31)
   - Multi-modality handling (future screenshot + video feature)
   - Reasoning patterns

4. **Quantigence Framework** (your file 38)
   - Multi-agent orchestration insights
   - State management between agents

---

## COMMAND REFERENCE (For Your Team)

### Initialize Frontend with Prebuilts
```bash
npm create vite@latest pik-web -- --template react
cd pik-web
npm install tailwind postcss autoprefixer framer-motion
npm install @testing-library/react jest
npm install prettier eslint
```

### Initialize Backend with Prebuilts
```bash
npm init -y
npm install express better-sqlite3 dotenv cors uuid
npm install @sentry/node
npm install --save-dev prettier eslint
```

### Run Locally
```bash
# Backend
node src/server.js

# Frontend
npm run dev

# Both: Use tmux or two terminals
```

### Deploy
```bash
# Vercel (frontend)
vercel deploy --prod

# Railway (backend)
vercel link [project-id]
# or push to GitHub for auto-deploy
```

---

## FINAL SHORTLIST (One-Page for Team)

**PIK MVP Uses:**
1. ✅ **Cursor** (scaffolding)
2. ✅ **Perplexity API** (research routing)
3. ✅ **Gemini API** (reasoning fallback)
4. ✅ **Tesseract.js** (OCR)
5. ✅ **Better-SQLite3** (local memory)
6. ✅ **Vercel** (frontend hosting)
7. ✅ **Railway** (backend hosting)
8. 🟡 **Sentry** (error tracking, add if time)
9. 🟡 **PostHog** (analytics, add if time)

**For Future (Week 2+):**
10. Claude API (new model)
11. Notion API (sync)
12. Stripe (payments)

**Skip For Now:**
- LangChain (complexity)
- PostgreSQL (use SQLite)
- GraphQL (use REST)
- Firebase (use Railway)

**Total First Month Cost:** ~$150 (Cursor $20 + APIs $80 + hosting free + Sentry/PostHog free)

---

**Ship PIK with boring, powerful tools. The outcome drives the choice, not the hype.**