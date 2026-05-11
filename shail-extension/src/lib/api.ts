import type {
  CaptureCandidate,
  CaptureResult,
  ContextBundle,
  EventType,
  GuidancePlan,
  GuidanceRequest,
  MemoryRecord,
  SearchRequest,
  SourceApp,
  StatsResult,
} from '../types/contracts';

// ─── Ascent types ─────────────────────────────────────────────────────────────

export interface TodoItem {
  id: string;
  text: string;
  completed: boolean;
  order: number;
}

export interface DeliverableItem {
  id: string;
  text: string;
  description: string;
  completed: boolean;
  order: number;
  todos: TodoItem[];
  memory_ids: string[];
}

export interface AscentSummary {
  id: string;
  name: string;
  description: string;
  status: string;
  progress: number;
  deliverable_count: number;
  todo_count: number;
  todos_completed: number;
  created_at: string;
}

export interface AscentDetail extends AscentSummary {
  deliverables: DeliverableItem[];
}

export interface AscentListResponse {
  items: AscentSummary[];
  total: number;
  active_count: number;
  limit: number;
  tier: string;
}

export interface RouteCluster {
  label: string;
  axis: 'tag' | 'source';
  count: number;
  latest_ts: string;
  sample_titles: string[];
}

export interface HorizonItem {
  label: string;
  memory_count: number;
  suggested_name: string;
  suggested_description: string;
  sample_titles: string[];
}

// ─── Local backend config ─────────────────────────────────────────────────────
// Primary uses localhost. Brave (and some hardened browsers) block localhost
// from extension service workers — 127.0.0.1 bypasses that restriction.
const LOCAL_BASE   = 'http://localhost:8000/browser';
const LOCAL_BASE_FB = 'http://127.0.0.1:8000/browser'; // Brave fallback
const AUTH_BASE    = 'http://localhost:8000/auth';
const AUTH_BASE_FB = 'http://127.0.0.1:8000/auth';
const HEALTH_URL   = 'http://localhost:8000/health';
const HEALTH_URL_FB = 'http://127.0.0.1:8000/health';

/** Single source of truth for "is the backend reachable?".
 *
 * Sprint 1 fix: previously returned ok:true on any HTTP 200, even when
 * /health reported chroma_ready:false (e.g. embedding model not loaded).
 * Captures would silently 500 after the popup said "online". Now we
 * distinguish:
 *   ok:true              — chroma + embedder both ready, captures will work
 *   ok:false, degraded   — backend reachable but a dep is down (orange)
 *   ok:false             — backend unreachable (red)
 */
export async function pingBackend(): Promise<{
  ok: boolean;
  degraded?: boolean;
  chroma_ready?: boolean;
  embedder_ready?: boolean;
  ollama_reachable?: boolean;
}> {
  const tryUrl = async (url: string) => {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), 2000);
    const res = await fetch(url, { signal: controller.signal });
    clearTimeout(t);
    if (!res.ok) throw new Error('not_ok');
    return res.json().catch(() => ({}));
  };
  try {
    let json: Record<string, unknown>;
    try {
      json = await tryUrl(HEALTH_URL);
    } catch {
      json = await tryUrl(HEALTH_URL_FB); // Brave fallback
    }
    const ready = !!(json.chroma_ready && json.embedder_ready);
    return { ok: ready, degraded: !ready, ...json };
  } catch {
    return { ok: false };
  }
}

// ─── Auth key helpers (chrome.storage.sync for cross-browser sync) ────────────

export async function getApiKey(): Promise<string | null> {
  try {
    const result = await browser.storage.sync.get('shail_api_key');
    return (result['shail_api_key'] as string) ?? null;
  } catch {
    // Sync storage unavailable (e.g. in content script context)
    return null;
  }
}

export async function setAuthCredentials(apiKey: string, userId: string): Promise<void> {
  await browser.storage.sync.set({ shail_api_key: apiKey, shail_user_id: userId });
}

export async function clearAuthCredentials(): Promise<void> {
  await browser.storage.sync.remove(['shail_api_key', 'shail_user_id']);
  // Also clear local cache so next open re-fetches from backend
  await browser.storage.local.remove('shail_doc_index');
}

export async function getUserId(): Promise<string | null> {
  try {
    const result = await browser.storage.sync.get('shail_user_id');
    return (result['shail_user_id'] as string) ?? null;
  } catch {
    return null;
  }
}

// ─── Core fetch (local backend) ───────────────────────────────────────────────

async function localFetch<T>(path: string, init?: RequestInit, base = LOCAL_BASE): Promise<T> {
  const apiKey = await getApiKey();

  const attempt = async (baseUrl: string): Promise<T> => {
    const controller = new AbortController();
    const timeoutId  = setTimeout(() => controller.abort(), 8000);
    try {
      const res = await fetch(`${baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey ? { 'Authorization': `Bearer ${apiKey}` } : {}),
          ...(init?.headers ?? {}),
        },
      });
      clearTimeout(timeoutId);
      if (res.status === 401) throw new Error('NOT_SIGNED_IN');
      if (res.status === 404) throw new Error('MEMORY_NOT_FOUND');
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`SHAIL ${path} → ${res.status}: ${body.slice(0, 200)}`);
      }
      if (res.status === 204) return undefined as T;
      return res.json() as Promise<T>;
    } catch (err) {
      clearTimeout(timeoutId);
      const msg = (err as Error).message ?? '';
      if ((err as Error).name === 'AbortError') throw new Error('BACKEND_TIMEOUT');
      if (/failed to fetch|networkerror|load failed/i.test(msg)) throw new Error('BACKEND_OFFLINE');
      throw err;
    }
  };

  // Primary attempt
  try {
    return await attempt(base);
  } catch (err) {
    // Brave (and some hardened browsers) block localhost from service workers.
    // Retry with 127.0.0.1 before surfacing BACKEND_OFFLINE to the user.
    if ((err as Error).message === 'BACKEND_OFFLINE') {
      const fallback = base === LOCAL_BASE ? LOCAL_BASE_FB
                     : base === AUTH_BASE  ? AUTH_BASE_FB
                     : null;
      if (fallback) {
        return await attempt(fallback);
      }
    }
    throw err;
  }
}

/** Turns a raw caught error into a short user-facing message. */
export function userFacingError(err: unknown): string {
  const msg = (err as Error)?.message ?? 'Unknown error';
  if (msg === 'BACKEND_OFFLINE' || /failed to fetch|networkerror|load failed/i.test(msg))
    return 'SHAIL offline — start the backend app';
  if (msg === 'BACKEND_TIMEOUT')
    return 'Backend timeout — is the app running?';
  if (msg === 'MEMORY_NOT_FOUND')
    return 'Memory not found';
  if (msg === 'NOT_SIGNED_IN')
    return 'Not signed in — open Settings to log in';
  if (/5\d\d/.test(msg))
    return 'Backend error — check the terminal for logs';
  return msg.length > 80 ? msg.slice(0, 77) + '…' : msg;
}

// ─── Local doc index helper ───────────────────────────────────────────────────

interface DocIndexEntry {
  id:        string;
  customId?: string;
  sourceApp: string;
  sourceUrl: string;
  title:     string;
  timestamp: string;
  eventType: string;
  pinned?:   boolean;
}

function indexEntryToRecord(e: DocIndexEntry): MemoryRecord {
  return {
    id:        e.id,
    customId:  e.customId ?? e.id,
    eventType: e.eventType as EventType,
    sourceApp: e.sourceApp as SourceApp,
    sourceUrl: e.sourceUrl,
    title:     e.title,
    summary:   e.title || e.sourceUrl,
    timestamp: e.timestamp,
    tags:      [],
    pinned:    e.pinned ?? false,
  };
}

// ─── Content utilities (kept for sidepanel inject formatter) ──────────────────

/**
 * Strips the "[sourceApp] Title\n\n" capture header then cleans markdown
 * syntax so the result is safe to display as plain text or inject into
 * an AI composer.
 */
export function cleanContentForDisplay(raw: string): string {
  const bodyStart = raw.indexOf('\n\n');
  const body = bodyStart > 0 ? raw.slice(bodyStart + 2) : raw;

  return body
    .replace(/!\[.*?\]\(https?:\/\/[^)]+\)/g, '')           // strip ![...](url)
    .replace(/\[([^\]]*)\]\(https?:\/\/[^)]+\)/g, '$1')     // [text](url) → text
    .replace(/\n{3,}/g, '\n\n')                              // collapse blank lines
    .trim();
}

// ─── API ──────────────────────────────────────────────────────────────────────

export const api = {

  /** Ingest a capture into local memory via the SHAIL backend. */
  async capture(payload: CaptureCandidate): Promise<CaptureResult> {
    const result = await localFetch<{ memoryId: string; status: string; summary?: string }>(
      '/capture',
      { method: 'POST', body: JSON.stringify(payload) },
    );
    return {
      memoryId: result.memoryId,
      status:   result.status as 'created' | 'duplicate' | 'denied',
      summary:  result.summary,
    };
  },

  async captureV2(payload: CaptureCandidate): Promise<CaptureResult> {
    const result = await localFetch<{ memoryId: string; status: string; summary?: string }>(
      '/capture/v2',
      { method: 'POST', body: JSON.stringify(payload) },
    );
    return {
      memoryId: result.memoryId,
      status: result.status as 'created' | 'duplicate' | 'denied',
      summary: result.summary,
    };
  },

  /**
   * Search memories.
   *
   * Empty query  → browse mode: calls POST /browser/search with query:"" so the
   *                backend returns all memories in the user's namespace, newest
   *                first. Falls back to shail_doc_index if backend is unreachable.
   *
   * Non-empty query → semantic search via ChromaDB KNN, keyword-boosted client-side.
   */
  async search(payload: SearchRequest): Promise<ContextBundle> {
    const isEmpty = !payload.query?.trim();
    let items: MemoryRecord[] = [];

    if (isEmpty) {
      // ── Browse: always try backend first so signed-in users see all their
      // memories across devices, not just what the local index happened to cache.
      try {
        const resp = await localFetch<{ items: MemoryRecord[]; total: number }>(
          '/search',
          { method: 'POST', body: JSON.stringify({ query: '', k: 100, after: payload.after ?? undefined }) },
        );
        items = resp.items;
      } catch (err) {
        const msg = (err as Error).message ?? '';
        if (msg !== 'BACKEND_OFFLINE' && msg !== 'BACKEND_TIMEOUT') throw err;
        // Backend unreachable — fall back to local index cache
        const stored = await browser.storage.local.get('shail_doc_index');
        const index  = (stored['shail_doc_index'] as DocIndexEntry[]) ?? [];
        items = index
          .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
          .map(indexEntryToRecord);
      }
    } else {
      // ── Search: call backend ──────────────────────────────────────────────
      const resp = await localFetch<{ items: MemoryRecord[]; total: number }>(
        '/search',
        { method: 'POST', body: JSON.stringify({ query: payload.query.trim(), k: 30, after: payload.after ?? undefined }) },
      );
      items = resp.items;
      // Results from backend already sorted by relevance score — preserve order.
      // Apply a small keyword boost to lift exact title matches even higher.
      const q     = payload.query.trim().toLowerCase();
      const words = q.split(/\s+/).filter(Boolean);
      if (items.length > 1) {
        const scored = items.map((r, i) => {
          const title   = (r.title   || '').toLowerCase();
          const summary = (r.summary || '').toLowerCase();
          let boost = 0;
          if (title === q)            boost += 1000;
          else if (title.includes(q)) boost +=  500;
          else for (const w of words) if (title.includes(w)) boost += 50;
          if (summary.includes(q)) boost += 20;
          return { r, score: (r.score ?? 0) * 100 + boost, i };
        });
        scored.sort((a, b) => b.score - a.score || a.i - b.i);
        items = scored.map(x => x.r);
      }
    }

    // Source filter (client-side)
    if (payload.filters?.sourceApp) {
      items = items.filter(r => r.sourceApp === payload.filters!.sourceApp);
    }

    // Deduplicate by id
    const seen = new Set<string>();
    items = items.filter(r => {
      const key = r.id || r.customId;
      if (!key) return true;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    const injectionText = items
      .slice(0, 3)
      .map(m => `--- ${m.title || m.sourceApp} ---\n${m.summary}`)
      .join('\n\n');

    return { query: payload.query, answer: '', items, injectionText };
  },

  /**
   * Popup stats — computed entirely from the local shail_doc_index.
   * ZERO network calls. Popup opens instantly.
   */
  async stats(): Promise<StatsResult> {
    const stored = await browser.storage.local.get('shail_doc_index');
    const index  = (stored['shail_doc_index'] as DocIndexEntry[]) ?? [];

    const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
    const memoriesThisWeek = index.filter(e => e.timestamp >= weekAgo).length;

    const counts: Partial<Record<SourceApp, number>> = {};
    for (const e of index) {
      const src = e.sourceApp as SourceApp;
      counts[src] = (counts[src] ?? 0) + 1;
    }
    const topSource =
      (Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] as SourceApp) ?? null;

    const sorted  = [...index].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    const recent  = sorted.slice(0, 3).map(indexEntryToRecord);

    return {
      memoriesThisWeek,
      topSource,
      lastCaptured:    recent[0] ?? null,
      recentCaptures:  recent,
    };
  },

  /** Delete a memory from local storage via the SHAIL backend. */
  async deleteMemory(id: string): Promise<void> {
    await localFetch<{ ok: boolean; id: string }>(
      `/memories/${id}`,
      { method: 'DELETE' },
    );
  },

  /**
   * Pin / unpin or update tags on a memory.
   * Week 1: persists to local shail_doc_index only (no backend PATCH yet).
   * The record is returned with the patch applied so the UI can update immediately.
   */
  async patchMemory(
    id: string,
    patch: Partial<Pick<MemoryRecord, 'pinned' | 'tags'>>,
    currentRecord?: MemoryRecord,
  ): Promise<MemoryRecord> {
    // Update local index
    const stored = await browser.storage.local.get('shail_doc_index');
    const index  = (stored['shail_doc_index'] as DocIndexEntry[]) ?? [];
    const idx    = index.findIndex(e => e.id === id);
    if (idx >= 0) {
      if (patch.pinned !== undefined) index[idx].pinned = patch.pinned;
      await browser.storage.local.set({ shail_doc_index: index });
    }
    const base = currentRecord ?? {
      id, customId: id, eventType: 'page_visit' as EventType, sourceApp: 'web' as SourceApp,
      sourceUrl: '', title: '', summary: '', timestamp: new Date().toISOString(),
      tags: [], pinned: false,
    };
    return {
      ...base,
      ...(patch.pinned !== undefined ? { pinned: patch.pinned } : {}),
      ...(patch.tags   !== undefined ? { tags:   patch.tags   } : {}),
    };
  },

  /**
   * Fetch the FULL stored content for a single memory (detail view).
   * Calls GET /browser/memories/:id on the local backend.
   */
  async getFullContent(id: string): Promise<{ content: string; eventType: EventType }> {
    const item = await localFetch<{
      id: string; eventType: string; content?: string; summary: string;
    }>(`/memories/${id}`);
    return {
      content:   item.content ?? item.summary ?? '',
      eventType: (item.eventType as EventType) ?? 'page_visit',
    };
  },

  /** Ghost cursor guidance — Phase 6, connect to local backend at /browser/guidance. */
  guidance(_payload: GuidanceRequest): Promise<GuidancePlan> {
    return Promise.reject(new Error('Guidance not implemented yet'));
  },

  // ── Ascents ───────────────────────────────────────────────────────────────

  async listAscents(): Promise<AscentListResponse> {
    return localFetch<AscentListResponse>('/ascents', undefined, 'http://localhost:8000/browser');
  },

  async getAscent(id: string): Promise<AscentDetail> {
    return localFetch<AscentDetail>(`/ascents/${id}`, undefined, 'http://localhost:8000/browser');
  },

  async toggleTodo(ascentId: string, todoId: string, completed: boolean): Promise<AscentDetail> {
    return localFetch<AscentDetail>(
      `/ascents/${ascentId}/todos/${todoId}`,
      { method: 'PUT', body: JSON.stringify({ completed }) },
      'http://localhost:8000/browser',
    );
  },

  // ── Routes + Horizon ──────────────────────────────────────────────────────

  async routes(): Promise<{ routes: RouteCluster[] }> {
    return localFetch<{ routes: RouteCluster[] }>('/routes');
  },

  async horizon(): Promise<{ items: HorizonItem[] }> {
    return localFetch<{ items: HorizonItem[] }>('/horizon');
  },

  // ── Auth ──────────────────────────────────────────────────────────────────

  async register(
    email: string,
    password: string,
    name: string = '',
  ): Promise<{ user_id: string; api_key: string; email: string; name: string }> {
    const controller = new AbortController();
    const timeoutId  = setTimeout(() => controller.abort(), 8000);
    try {
      const res = await fetch(`${AUTH_BASE}/register`, {
        method: 'POST',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, name }),
      });
      clearTimeout(timeoutId);
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        const detail = (() => { try { return JSON.parse(body).detail ?? body; } catch { return body; } })();
        throw new Error(detail || `Register failed: ${res.status}`);
      }
      return res.json();
    } catch (err) {
      clearTimeout(timeoutId);
      const msg = (err as Error).message ?? '';
      if ((err as Error).name === 'AbortError') throw new Error('BACKEND_TIMEOUT');
      if (/failed to fetch|networkerror|load failed/i.test(msg)) throw new Error('BACKEND_OFFLINE');
      throw err;
    }
  },

  async login(
    email: string,
    password: string,
  ): Promise<{ user_id: string; api_key: string; email: string; name: string }> {
    const controller = new AbortController();
    const timeoutId  = setTimeout(() => controller.abort(), 8000);
    try {
      const res = await fetch(`${AUTH_BASE}/login`, {
        method: 'POST',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      clearTimeout(timeoutId);
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        const detail = (() => { try { return JSON.parse(body).detail ?? body; } catch { return body; } })();
        throw new Error(detail || `Login failed: ${res.status}`);
      }
      return res.json();
    } catch (err) {
      clearTimeout(timeoutId);
      const msg = (err as Error).message ?? '';
      if ((err as Error).name === 'AbortError') throw new Error('BACKEND_TIMEOUT');
      if (/failed to fetch|networkerror|load failed/i.test(msg)) throw new Error('BACKEND_OFFLINE');
      throw err;
    }
  },

  async authMe(): Promise<{ user_id: string; email: string; name: string; created_at: string }> {
    return localFetch('/me', undefined, AUTH_BASE);
  },

  async addKey(label: string): Promise<{ key: string; label: string }> {
    return localFetch('/keys', { method: 'POST', body: JSON.stringify({ label }) }, AUTH_BASE);
  },

  // ── Capture settings ──────────────────────────────────────────────────────

  async captureSettings(): Promise<{ capture_enabled: boolean; blocked_domains: string[]; ollama_model: string; external_api_key: string }> {
    return localFetch('/capture-settings');
  },

  async putCaptureSettings(body: { blocked_domains?: string[]; capture_enabled?: boolean; ollama_model?: string }): Promise<void> {
    await localFetch('/capture-settings', { method: 'PUT', body: JSON.stringify(body) });
  },

  // ── Google OAuth helpers ──────────────────────────────────────────────────

  /** Returns the Google OAuth start URL for the given state token. */
  googleStartUrl(state: string): string {
    return `http://localhost:8000/auth/google/start?state=${encodeURIComponent(state)}`;
  },

  /**
   * Single poll of the Google token endpoint.
   * Returns the token payload on 200, null on 204 (still waiting).
   * Throws on error.
   */
  async pollGoogleToken(
    state: string,
  ): Promise<{ email: string; name: string; api_key: string; user_id: string } | null> {
    const controller = new AbortController();
    const timeoutId  = setTimeout(() => controller.abort(), 5000);
    try {
      const res = await fetch(
        `http://localhost:8000/auth/google/token?state=${encodeURIComponent(state)}`,
        { signal: controller.signal },
      );
      clearTimeout(timeoutId);
      if (res.status === 204) return null;  // still waiting
      if (!res.ok) throw new Error(`Google token poll failed: ${res.status}`);
      return res.json();
    } catch (err) {
      clearTimeout(timeoutId);
      const msg = (err as Error).message ?? '';
      if ((err as Error).name === 'AbortError') throw new Error('BACKEND_TIMEOUT');
      if (/failed to fetch|networkerror|load failed/i.test(msg)) throw new Error('BACKEND_OFFLINE');
      throw err;
    }
  },
};

// ─── Inject formatter ─────────────────────────────────────────────────────────

/**
 * Parses the raw stored document content string and returns labelled sections.
 *
 * AI captures are stored as:
 *   "[chatgpt] Title\n\nUser: {question}\n\nAssistant: {answer}"
 *
 * Web captures are stored as:
 *   "[web] Title\n\n{article text}"
 */
function parseStoredContent(raw: string): {
  title:         string;
  userText:      string;
  assistantText: string;
  pageText:      string;
} {
  const nlnl   = raw.indexOf('\n\n');
  const header = nlnl > 0 ? raw.slice(0, nlnl) : '';
  const body   = nlnl > 0 ? raw.slice(nlnl + 2) : raw;

  const titleMatch    = header.match(/^\[\w+\]\s+(.+)/);
  const title         = titleMatch?.[1]?.trim() ?? '';

  const userMatch      = body.match(/^User:\s*([\s\S]*?)(?=\n\nAssistant:|$)/);
  const assistantMatch = body.match(/\n\nAssistant:\s*([\s\S]*)$/s);

  const userText      = userMatch?.[1]?.trim()      ?? '';
  const assistantText = assistantMatch?.[1]?.trim() ?? '';
  const pageText      = (!userText && !assistantText) ? body.trim() : '';

  return { title, userText, assistantText, pageText };
}

/**
 * Formats a full stored document into clean inject text for an AI composer.
 * Trims content to 4000 chars so we don't overwhelm context windows.
 */
export function formatFullInject(
  rawContent:  string,
  eventType:   EventType,
  sourceLabel: string,
): string {
  const MAX_CONTENT = 4000;
  const { title, userText, assistantText, pageText } = parseStoredContent(rawContent);

  if (eventType === 'ai_conversation') {
    const answerRaw     = assistantText || rawContent.slice(0, MAX_CONTENT);
    const truncated     = answerRaw.length > MAX_CONTENT;
    const answerDisplay = answerRaw.slice(0, MAX_CONTENT) + (truncated ? '\n[… truncated]' : '');

    const lines = [`--- Memory from ${sourceLabel} ---`, ''];
    if (userText) lines.push(`Question: ${userText}`, '');
    lines.push('Answer:', answerDisplay, '', '---');
    return lines.join('\n');
  } else {
    const bodyRaw     = pageText || rawContent.slice(0, MAX_CONTENT);
    const truncated   = bodyRaw.length > MAX_CONTENT;
    const bodyDisplay = bodyRaw.slice(0, MAX_CONTENT) + (truncated ? '\n[… truncated]' : '');

    return [
      `--- Saved article: ${title || 'Web page'} ---`,
      '',
      bodyDisplay,
      '',
      '---',
    ].join('\n');
  }
}
