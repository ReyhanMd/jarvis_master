import type { SourceApp } from '../types/contracts';

const PATTERNS: Partial<Record<SourceApp, RegExp>> = {
  chatgpt:    /\/c\/([a-z0-9-]+)/i,
  claude:     /\/chat\/([a-z0-9-]+)/i,
  gemini:     /\/app\/([a-z0-9-]+)/i,
  perplexity: /\/search\/([a-z0-9-]+)/i,
  grok:       /\/(?:chat|conversation)\/([a-z0-9-]+)/i,
};

/**
 * Extract the provider-specific conversation UUID from the current URL.
 * Returns null if no UUID is present (e.g. brand-new chat, root page).
 * When null, callers fall back to the legacy content-fingerprint customId.
 */
export function extractConversationId(url: string, sourceApp: SourceApp): string | null {
  const pattern = PATTERNS[sourceApp];
  if (!pattern) return null;
  try {
    const path = new URL(url).pathname;
    const match = path.match(pattern);
    return match?.[1] ?? null;
  } catch {
    return null;
  }
}

interface TempConversationRecord {
  id: string;
  createdAt: string;
  lastUrl: string;
}

export interface ConversationIdentity {
  conversationId: string;
  temporary: boolean;
  previousConversationId?: string;
}

const TEMP_KEY = 'shail_temporary_conversations';
const TEMP_TTL_MS = 12 * 60 * 60 * 1000;

async function readTempRecords(): Promise<Record<string, TempConversationRecord>> {
  try {
    const stored = await chrome.storage.local.get(TEMP_KEY);
    const records = (stored[TEMP_KEY] as Record<string, TempConversationRecord>) ?? {};
    const now = Date.now();
    for (const [key, record] of Object.entries(records)) {
      const created = Date.parse(record.createdAt);
      if (!Number.isFinite(created) || now - created > TEMP_TTL_MS) {
        delete records[key];
      }
    }
    return records;
  } catch {
    return {};
  }
}

async function writeTempRecords(records: Record<string, TempConversationRecord>): Promise<void> {
  try {
    await chrome.storage.local.set({ [TEMP_KEY]: records });
  } catch {
    // Temporary IDs are a continuity aid. Capture should still proceed if
    // browser storage is unavailable in the content-script context.
  }
}

export async function resolveConversationIdentity(
  url: string,
  sourceApp: SourceApp,
): Promise<ConversationIdentity> {
  const stable = extractConversationId(url, sourceApp);
  const records = await readTempRecords();
  const previous = records[sourceApp]?.id;

  if (stable) {
    if (previous) {
      delete records[sourceApp];
      await writeTempRecords(records);
      return { conversationId: stable, temporary: false, previousConversationId: previous };
    }
    return { conversationId: stable, temporary: false };
  }

  if (previous) {
    records[sourceApp] = { ...records[sourceApp], lastUrl: url };
    await writeTempRecords(records);
    return { conversationId: previous, temporary: true };
  }

  const id = `temp:${sourceApp}:${crypto.randomUUID()}`;
  records[sourceApp] = { id, createdAt: new Date().toISOString(), lastUrl: url };
  await writeTempRecords(records);
  return { conversationId: id, temporary: true };
}
