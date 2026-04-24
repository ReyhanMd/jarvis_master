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

// ─── Local backend config ─────────────────────────────────────────────────────
// The SHAIL backend (jarvis_master) runs on localhost:8000.
const LOCAL_BASE   = 'http://localhost:8000/browser';
const AUTH_BASE    = 'http://localhost:8000/auth';

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
  const controller = new AbortController();
  const timeoutId  = setTimeout(() => controller.abort(), 8000);

  // Inject API key if available (from storage.sync — cross-browser)
  const apiKey = await getApiKey();

  try {
    const res = await fetch(`${base}${path}`, {
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

  /**
   * Search memories.
   *
   * Empty query → browse mode: reads from shail_doc_index in local storage.
   *               ZERO network calls. Always instant.
   *
   * Non-empty query → semantic search via SHAIL backend (Gemini + ChromaDB KNN).
   *                   Returns results sorted by relevance score descending.
   */
  async search(payload: SearchRequest): Promise<ContextBundle> {
    const isEmpty = !payload.query?.trim();
    let items: MemoryRecord[] = [];

    if (isEmpty) {
      // ── Browse: read from local index (no network) ────────────────────────
      const stored = await browser.storage.local.get('shail_doc_index');
      const index  = (stored['shail_doc_index'] as DocIndexEntry[]) ?? [];
      items = index
        .slice(0, 50)
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
        .map(indexEntryToRecord);
    } else {
      // ── Search: call backend ──────────────────────────────────────────────
      const resp = await localFetch<{ items: MemoryRecord[]; total: number }>(
        '/search',
        { method: 'POST', body: JSON.stringify({ query: payload.query.trim(), k: 30 }) },
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
