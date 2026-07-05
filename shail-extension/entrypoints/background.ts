import { api } from '../src/lib/api';
import type {
  BackgroundMessage,
  BackgroundResponse,
  CaptureResult,
  SitePolicy,
} from '../src/types/contracts';

// ─── Storage keys ─────────────────────────────────────────────────────────────

const KEY_POLICIES      = 'shail_policies';
const KEY_CAPTURE       = 'shail_capture_enabled';
const KEY_DOC_INDEX     = 'shail_doc_index';      // local list of saved document IDs
const MAX_INDEX_SIZE    = 200;                     // keep last 200 documents

// ─── Local document index ─────────────────────────────────────────────────────

interface DocIndexEntry {
  id:        string;
  customId?: string;   // SHA-256 fingerprint — used for exact dedup before API call
  sourceApp: string;
  sourceUrl: string;
  title:     string;
  timestamp: string;
  eventType: string;
}

async function storeDocumentId(docId: string, payload: import('../src/types/contracts').CaptureCandidate): Promise<void> {
  const result = await browser.storage.local.get(KEY_DOC_INDEX);
  const index: DocIndexEntry[] = (result[KEY_DOC_INDEX] as DocIndexEntry[]) ?? [];

  // Avoid duplicates
  if (index.some(e => e.id === docId)) return;

  index.unshift({
    id:        docId,
    customId:  payload.customId,   // store fingerprint for pre-API dedup
    sourceApp: payload.sourceApp,
    sourceUrl: payload.sourceUrl,
    title:     payload.title ?? '',
    timestamp: payload.timestamp,
    eventType: payload.eventType,
  });

  // Keep max 200
  if (index.length > MAX_INDEX_SIZE) index.splice(MAX_INDEX_SIZE);

  // Also update shail_recent_saves so popup dedup check is instant on next open
  const recResult = await browser.storage.local.get('shail_recent_saves');
  const recSaves = (recResult['shail_recent_saves'] as Array<{ url: string; timestamp: string }>) ?? [];
  recSaves.unshift({ url: payload.sourceUrl, timestamp: payload.timestamp });

  await browser.storage.local.set({
    [KEY_DOC_INDEX]: index,
    shail_recent_saves: recSaves.slice(0, 200),
  });
}

function captureOutcome(
  status: CaptureResult['status'],
  reason?: string,
  memoryId?: string,
  summary?: string,
): BackgroundResponse {
  if (status === 'error') {
    return { ok: false, error: reason || 'Capture failed' };
  }
  return {
    ok: true,
    data: {
      status,
      ...(memoryId ? { memoryId } : {}),
      ...(summary ? { summary } : {}),
      ...(reason ? { reason } : {}),
    },
  };
}

// ─── Badge helpers ────────────────────────────────────────────────────────────

let badgeClearTimer: ReturnType<typeof setTimeout> | null = null;

function showCaptureBadge() {
  browser.action.setBadgeText({ text: '✓' });
  browser.action.setBadgeBackgroundColor({ color: '#22c55e' });
  if (badgeClearTimer) clearTimeout(badgeClearTimer);
  badgeClearTimer = setTimeout(() => {
    browser.action.setBadgeText({ text: '' });
  }, 3000);
}

function showErrorBadge() {
  browser.action.setBadgeText({ text: '!' });
  browser.action.setBadgeBackgroundColor({ color: '#ef4444' });
  if (badgeClearTimer) clearTimeout(badgeClearTimer);
  badgeClearTimer = setTimeout(() => {
    browser.action.setBadgeText({ text: '' });
  }, 4000);
}

// ─── Storage helpers ──────────────────────────────────────────────────────────

async function getCaptureEnabled(): Promise<boolean> {
  const result = await browser.storage.local.get(KEY_CAPTURE);
  return (result[KEY_CAPTURE] as boolean) ?? true;
}

async function getCachedPolicies(): Promise<SitePolicy[]> {
  const result = await browser.storage.local.get(KEY_POLICIES);
  return (result[KEY_POLICIES] as SitePolicy[]) ?? [];
}

async function updateCaptureStateCache(
  memoryId: string,
  payload: import('../src/types/contracts').CaptureCandidate,
): Promise<void> {
  if (payload.eventType !== 'ai_conversation') return;

  await browser.storage.local.set({
    shail_active_capture: {
      state: 'LISTENING',
      platform: payload.sourceApp,
      title: payload.title ?? '',
      turnCount: payload.turnCount ?? 0,
      progressValue: 0,
      conversationId: payload.conversationId,
      memoryId,
      sourceUrl: payload.sourceUrl,
      updatedAt: new Date().toISOString(),
    },
  });

  try {
    const surface = await api.captureState({ memoryId });
    const stored = await browser.storage.local.get('shail_capture_state_cache');
    const cache = (stored['shail_capture_state_cache'] as Record<string, unknown>) ?? {};
    cache[memoryId] = surface;
    await browser.storage.local.set({
      shail_capture_state_cache: cache,
      shail_active_capture: {
        state: 'LISTENING',
        platform: payload.sourceApp,
        title: surface.title || payload.title || '',
        turnCount: payload.turnCount ?? 0,
        progressValue: 0,
        conversationId: surface.conversation_id || payload.conversationId,
        memoryId,
        sourceUrl: surface.source_url || payload.sourceUrl,
        backendState: surface,
        updatedAt: surface.updated_at,
      },
    });
  } catch {
    // Backend state may not be queryable immediately after queued ingest.
  }
}

// ─── Policy check ─────────────────────────────────────────────────────────────

function isDomainDenied(url: string, policies: SitePolicy[]): boolean {
  try {
    const hostname = new URL(url).hostname;
    const match = policies.find(p =>
      hostname === p.domain || hostname.endsWith(`.${p.domain}`)
    );
    return match?.policy === 'DENY';
  } catch {
    return false;
  }
}

// ─── Message handler ──────────────────────────────────────────────────────────

async function handleMessage(
  message: BackgroundMessage,
  sender: chrome.runtime.MessageSender,
): Promise<BackgroundResponse> {
  switch (message.type) {
    case 'CAPTURE': {
      const isManualSave = message.payload.captureInitiator === 'manual';
      // ── Dedup: check local index before hitting the API ────────────────────
      // Two signals:
      //   1. customId match   — exact same capture (url + date + content hash)
      //   2. sourceUrl match  — same web page already saved on a previous day
      //      (web page captures only; AI convos on the same URL differ by content)
      {
        const dupStored = await browser.storage.local.get(KEY_DOC_INDEX);
        const dupIndex  = (dupStored[KEY_DOC_INDEX] as DocIndexEntry[]) ?? [];
        const { customId, sourceUrl, eventType } = message.payload;

        // conversationId captures use a stable customId per conversation.
        // Backend handles upsert idempotently — skip the local ring for these.
        const hasConversationId = !!(message.payload as { conversationId?: string }).conversationId;

        const isDuplicate =
          !isManualSave && !hasConversationId && (
            // Exact fingerprint match (covers all event types)
            (customId && dupIndex.some(e => e.customId === customId)) ||
            // URL match for page visits (same page across different days)
            (eventType === 'page_visit' &&
              dupIndex.some(e => e.sourceUrl === sourceUrl && e.eventType === 'page_visit'))
          );

        if (isDuplicate) {
          return captureOutcome('duplicate', 'Already saved locally');
        }
      }

      // AI content scripts now score content before sending CAPTURE, so only
      // genuinely valuable content reaches here. Keep a safety floor for the
      // universal (web page) adapter which uses a simpler quality check.
      const contentLength = (
        message.payload.assistantText ?? message.payload.pageContent ?? ''
      ).trim().length;
      if (contentLength < (isManualSave ? 10 : 80)) {
        return captureOutcome('denied', 'Not enough readable content to save');
      }

      const policies = await getCachedPolicies();
      if (isDomainDenied(message.payload.sourceUrl, policies)) {
        return captureOutcome('denied', 'This site is blocked by capture policy');
      }

      const captureEnabled = await getCaptureEnabled();
      if (!captureEnabled && !isManualSave) {
        return captureOutcome('denied', 'Active capture is paused');
      }

      try {
        const result = await api.capture(message.payload);
        if (result.memoryId && result.status !== 'denied' && result.status !== 'duplicate' && result.status !== 'error') {
          showCaptureBadge();
          // ── Store document ID locally so the popup/sidepanel browse is instant
          await storeDocumentId(result.memoryId, message.payload);
          await updateCaptureStateCache(result.memoryId, message.payload);
        }
        // Clear any previous error on success
        await browser.storage.local.remove('shail_last_capture_error');
        if (!result.memoryId && result.status !== 'duplicate') {
          return captureOutcome(result.status, result.reason ?? 'Capture did not create a backend memory');
        }
        return captureOutcome(
          result.status === 'created' ? 'saved' : result.status,
          result.reason,
          result.memoryId,
          result.summary,
        );
      } catch (err) {
        showErrorBadge();
        const rawMsg    = (err as Error).message ?? '';
        const isOffline = rawMsg === 'BACKEND_OFFLINE' || rawMsg === 'BACKEND_TIMEOUT';
        const friendlyMsg =
          rawMsg === 'BACKEND_OFFLINE'
            ? 'SHAIL backend is offline — capture queued, will retry'
            : rawMsg === 'BACKEND_TIMEOUT'
            ? 'Backend timeout — capture queued, will retry'
            : rawMsg;
        // If the backend was unreachable, queue the capture for later drain.
        if (isOffline) {
          try {
            const { enqueue } = await import('../src/lib/offlineQueue');
            await enqueue(message.payload);
          } catch (qErr) {
            console.warn('[SHAIL] queue enqueue failed:', qErr);
          }
        }
        // Store the error so the Options page can surface it
        await browser.storage.local.set({
          shail_last_capture_error: {
            message: friendlyMsg,
            timestamp: new Date().toISOString(),
          },
        });
        if (isOffline) {
          // Treat queued captures as a soft success so the popup does not
          // flash a red error — they will drain when the backend comes back.
          return captureOutcome('offline_queued', friendlyMsg);
        }
        return { ok: false, error: friendlyMsg };
      }
    }

    case 'SEARCH': {
      try {
        const bundle = await api.search(message.payload);
        return { ok: true, data: bundle };
      } catch (err) {
        return { ok: false, error: (err as Error).message };
      }
    }

    case 'OPEN_SIDEPANEL': {
      // Set focus flag synchronously before the open call
      browser.storage.local.set({ shail_focus_search: true });
      if (sender.tab?.id) {
        chrome.sidePanel.open({ tabId: sender.tab.id }).catch(() => {
          if (sender.tab?.windowId) {
            chrome.sidePanel.open({ windowId: sender.tab.windowId }).catch(() => {});
          }
        });
      } else {
        // Fallback: open on active window
        chrome.windows.getCurrent(w => {
          if (w?.id) chrome.sidePanel.open({ windowId: w.id }).catch(() => {});
        });
      }
      return { ok: true, data: null };
    }

    case 'GET_POLICIES': {
      const policies = await getCachedPolicies();
      return { ok: true, data: policies };
    }

    case 'FETCH_ASCENT': {
      try {
        const data = await api.getAscent(message.payload.id);
        return { ok: true, data };
      } catch (err) {
        return { ok: false, error: (err as Error).message };
      }
    }

    case 'TOGGLE_TODO': {
      try {
        const { ascentId, todoId, completed } = message.payload;
        const data = await api.toggleTodo(ascentId, todoId, completed);
        return { ok: true, data };
      } catch (err) {
        return { ok: false, error: (err as Error).message };
      }
    }

    case 'START_BULK_CYCLE': {
      startBulkCycle(message.payload.urls);
      return { ok: true, data: null };
    }

    case 'CACHE_EVICTION': {
      try {
        const payload = message.payload as { keys?: string[]; action?: string; id?: string };
        const action = payload.action;
        const id = payload.id;

        const stored = await browser.storage.local.get([KEY_DOC_INDEX, 'shail_recent_saves']);
        let index = (stored[KEY_DOC_INDEX] as DocIndexEntry[]) ?? [];
        let recentSaves = (stored['shail_recent_saves'] as Array<{ url: string; timestamp: string }>) ?? [];

        if (action === 'clear') {
          index = [];
          recentSaves = [];
        } else if (action === 'delete' && id) {
          const entry = index.find(e => e.id === id || e.customId === id);
          if (entry) {
            recentSaves = recentSaves.filter(s => s.url !== entry.sourceUrl);
          }
          index = index.filter(e => e.id !== id && e.customId !== id);
        }

        await browser.storage.local.set({
          [KEY_DOC_INDEX]: index,
          shail_recent_saves: recentSaves
        });
      } catch (err) {
        console.warn('[SHAIL] Cache eviction sync failed:', err);
      }
      return { ok: true, data: null };
    }

    case 'DELETE_TRANSCRIPT_KEEP_BLUEPRINT': {
      try {
        const { memoryId, policy } = message.payload;
        await api.setRetention(memoryId, policy);
        try {
          const surface = await api.captureState({ memoryId });
          const stored = await browser.storage.local.get('shail_capture_state_cache');
          const cache = (stored['shail_capture_state_cache'] as Record<string, unknown>) ?? {};
          cache[memoryId] = surface;
          await browser.storage.local.set({ shail_capture_state_cache: cache });
        } catch {
          // Non-critical; UI will refresh from backend on next open/focus.
        }
        return { ok: true, data: null };
      } catch (err) {
        return { ok: false, error: (err as Error).message };
      }
    }

    default:
      return { ok: false, error: 'Unknown message type' };
  }
}

// ─── Background Bulk Cycler ───────────────────────────────────────────────────

async function waitTabComplete(tabId: number, timeoutMs = 12000): Promise<boolean> {
  return new Promise((resolve) => {
    let timer: any = null;

    const listener = (id: number, info: { status?: string }) => {
      if (id === tabId && info.status === 'complete') {
        cleanup();
        resolve(true);
      }
    };

    const cleanup = () => {
      chrome.tabs.onUpdated.removeListener(listener);
      if (timer) clearTimeout(timer);
    };

    chrome.tabs.onUpdated.addListener(listener);

    timer = setTimeout(() => {
      cleanup();
      resolve(false);
    }, timeoutMs);
  });
}

let isCycling = false;
async function startBulkCycle(urls: string[]) {
  if (isCycling) return;
  isCycling = true;

  try {
    await browser.storage.local.set({
      shail_bulk_status: {
        isCycling: true,
        completedCount: 0,
        totalInQueue: urls.length,
        currentUrl: urls[0]
      }
    });

    const tab = await browser.tabs.create({ active: false, url: urls[0] });
    if (!tab.id) return;

    for (let i = 0; i < urls.length; i++) {
      const url = urls[i];

      await browser.storage.local.set({
        shail_bulk_status: {
          isCycling: true,
          completedCount: i,
          totalInQueue: urls.length,
          currentUrl: url
        }
      });

      let success = false;
      let retries = 3;
      let delay = 1000;

      while (retries > 0 && !success) {
        try {
          await browser.tabs.update(tab.id, { url });
          await waitTabComplete(tab.id, 12000);
          await new Promise(r => setTimeout(r, 4000));

          await browser.tabs.sendMessage(tab.id, { type: 'TRIGGER_SCROLL_PUMP' });
          await new Promise(r => setTimeout(r, 15000));
          success = true;
        } catch (e) {
          retries--;
          console.warn(`[SHAIL] Bulk cycle error on ${url}, retries left: ${retries}`, e);
          if (retries > 0) {
            await new Promise(r => setTimeout(r, delay));
            delay *= 2;
          }
        }
      }
    }

    await browser.tabs.remove(tab.id);
  } catch (err) {
    console.error('[SHAIL] Bulk cycle error:', err);
  } finally {
    isCycling = false;
    await browser.storage.local.set({
      shail_bulk_status: {
        isCycling: false,
        completedCount: urls.length,
        totalInQueue: urls.length,
        currentUrl: ''
      }
    });
  }
}


// ─── Background entry ─────────────────────────────────────────────────────────

export default defineBackground(() => {
  // Ensure side panel is enabled globally
  chrome.sidePanel.setOptions({ enabled: true });

  // Central message bus
  browser.runtime.onMessage.addListener(
    (message: unknown, sender, sendResponse) => {
      handleMessage(message as BackgroundMessage, sender)
        .then(sendResponse)
        .catch(err =>
          sendResponse({ ok: false, error: (err as Error).message })
        );
      return true; // keep channel open for async response
    }
  );

  // Open sidepanel when user clicks the extension icon
  browser.action.onClicked.addListener(async (tab) => {
    if (tab.id) {
      await browser.sidePanel.open({ tabId: tab.id });
    }
  });

  // Ctrl+Space (manifest command) → open side panel + signal search focus.
  // CRITICAL: Do NOT use async/await here — Chrome only propagates the user
  // gesture to synchronous code. Using await before sidePanel.open() silently
  // drops the call. Use .then() chains to stay in the gesture context.
  // ── Periodic offline-queue drain ────────────────────────────────────────
  // Every 30 s, ping the backend; if up, drain pending captures.
  const drainTick = async () => {
    try {
      const { pingBackend } = await import('../src/lib/api');
      const { drain, size } = await import('../src/lib/offlineQueue');
      const queued = await size();
      if (queued === 0) return;
      const health = await pingBackend();
      if (!health.ok) return;
      await drain(async (payload) => { await api.capture(payload); });
    } catch (err) {
      console.warn('[SHAIL] drain tick failed:', err);
    }
  };
  setInterval(drainTick, 30_000);
  // Kick once at startup so the badge clears fast after a restart
  setTimeout(drainTick, 3_000);

  browser.commands.onCommand.addListener((command) => {
    if (command === 'open-sidepanel') {
      // Signal sidepanel to auto-focus search (fire-and-forget)
      browser.storage.local.set({ shail_focus_search: true });

      // Open side panel — try tabId first, fall back to windowId
      browser.tabs.query({ active: true, currentWindow: true }).then(tabs => {
        const tab = tabs[0];
        if (!tab) return;

        if (tab.id) {
          chrome.sidePanel.open({ tabId: tab.id }).catch(() => {
            // tabId rejected (e.g. chrome:// page) — try window-level
            if (tab.windowId) {
              chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => {});
            }
          });
        } else if (tab.windowId) {
          chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => {});
        }
      });
    }
  });
});
