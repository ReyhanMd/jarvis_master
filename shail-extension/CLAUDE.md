# SHAIL Memory Watchdog — Browser Extension

## What this is
A Chrome extension (WXT + React + TypeScript) that passively captures AI conversations and web browsing, stores them in Supermemory, and lets you search + inject context back into any AI chat.

## Tech stack
- **WXT** v0.20.20 — extension framework (Chrome MV3)
- **React** + **TypeScript** — all UI (popup, sidepanel, overlays)
- **Tailwind CSS** — styling
- **lucide-react** — icons
- **@mozilla/readability** — universal web page content extraction
- **Supermemory API** — memory storage + search engine
- **Base44** — backend serverless functions + web dashboard

## Project structure
```
entrypoints/
  background.ts          — service worker: message router, API calls, badge
  content/
    chatgpt.ts           — MutationObserver capture for ChatGPT
    claude-ai.ts         — capture for Claude.ai
    gemini.ts            — capture for Gemini
    perplexity.ts        — capture for Perplexity
    universal.ts         — Readability.js capture for all other pages
  popup/
    index.html + main.tsx + style.css
  sidepanel/
    index.html + main.tsx + style.css
  options/
    index.html + main.tsx + style.css
  overlays/
    quick-query/index.ts — Alt+Space floating panel (shadow DOM)
    guide-cursor/renderer.ts — SVG ring + TTS ghost cursor
src/
  types/contracts.ts     — all shared TypeScript types
  lib/
    api.ts               — typed wrappers for Base44 API calls
    crypto.ts            — SHA-256 dedup helper
```

## Environment variables
```
VITE_SHAIL_API_BASE=https://<your-base44-url>
```

## Base44 API endpoints (backend — build in Base44 dashboard)
| Method | Path | Purpose |
|--------|------|---------|
| GET | /browser/me | Returns user's supermemory_api_key + plan |
| POST | /browser/capture | Ingest CaptureCandidate → Supermemory |
| POST | /browser/search | Search memories → ContextBundle |
| POST | /browser/guidance | Screenshot + DOM → GuidancePlan (ghost cursor) |
| GET | /browser/stats | Capture counts for popup stats cards |
| DELETE | /browser/memories/:id | Delete a memory |

## Build phases
- **Phase 0** — Foundation (DONE): React, Tailwind, types, permissions, CLAUDE.md
- **Phase 1** — Background worker: message routing, API calls, badge
- **Phase 2** — Capture layer: site adapters + universal.ts
- **Phase 3** — Popup UI: stats cards, last 3 captures, open sidepanel
- **Phase 4** — Sidepanel: search, memory cards, inject/copy/pin/delete
- **Phase 5** — Context inject adapters: resolveComposer + injectText per site
- **Phase 6** — Overlays: quick-query panel + ghost cursor renderer
- **Phase 7** — Options page: site policies, capture toggle
- **Phase 8** — Ship: icons, zip, Chrome Web Store

## Key types (src/types/contracts.ts)
- `CaptureCandidate` — what content scripts send to background
- `MemoryRecord` — what comes back from search
- `ContextBundle` — search result with injectionText
- `GuidancePlan` / `GuidanceStep` — ghost cursor steps
- `BackgroundMessage` — typed message bus between content ↔ background

## Dev commands
```bash
npm run dev      # Chrome hot-reload dev mode
npm run build    # Production build
npm run zip      # Package for Chrome Web Store
npm run compile  # TypeScript type check only
```

## Permissions (wxt.config.ts)
- tabs, activeTab, storage, scripting, sidePanel
- host_permissions: <all_urls>
- commands: Alt+Space → open-quick-query
