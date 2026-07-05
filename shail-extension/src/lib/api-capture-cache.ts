import type { CaptureCandidate, SourceApp } from '../types/contracts';

const KEY = 'shail_api_session_capture_cache';
const TTL_MS = 10 * 60 * 1000;

interface CachedApiCapture {
  candidate: CaptureCandidate;
  cachedAt: number;
}

function cacheKey(sourceApp: SourceApp, conversationId: string): string {
  return `${sourceApp}:${conversationId}`;
}

async function readCache(): Promise<Record<string, CachedApiCapture>> {
  try {
    const stored = await chrome.storage.local.get(KEY);
    const cache = (stored[KEY] as Record<string, CachedApiCapture>) ?? {};
    const now = Date.now();
    for (const [key, entry] of Object.entries(cache)) {
      if (!entry?.cachedAt || now - entry.cachedAt > TTL_MS) {
        delete cache[key];
      }
    }
    return cache;
  } catch {
    return {};
  }
}

async function writeCache(cache: Record<string, CachedApiCapture>): Promise<void> {
  try {
    await chrome.storage.local.set({ [KEY]: cache });
  } catch {
    // API-first is an optimization. DOM scroll remains the fallback.
  }
}

export async function saveApiSessionCapture(candidate: CaptureCandidate): Promise<void> {
  if (!candidate.conversationId || candidate.captureMode !== 'retroactive') return;
  const cache = await readCache();
  cache[cacheKey(candidate.sourceApp, candidate.conversationId)] = {
    candidate,
    cachedAt: Date.now(),
  };
  await writeCache(cache);
}

export async function getApiSessionCapture(
  sourceApp: SourceApp,
  conversationId: string,
): Promise<CaptureCandidate | null> {
  const cache = await readCache();
  return cache[cacheKey(sourceApp, conversationId)]?.candidate ?? null;
}
