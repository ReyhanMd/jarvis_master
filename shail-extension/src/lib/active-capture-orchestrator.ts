import {
  buildAiCandidate,
  isCaptureAllowed,
  makeCaptureId,
  observeWithStability,
  sendCapture,
} from './capture';
import { sha256 } from './crypto';
import { resolveConversationIdentity } from './conversation-id';
import { scoreContent } from './importance';
import { submitDomCaptureBuffer } from './race-lock';
import type { CaptureResult, CaptureSegment } from '../types/contracts';
import type { PlatformAdapter, StructuredMessage } from './platform-adapters';

export const KEY_CAPTURE = 'shail_capture_enabled';
export const KEY_PAUSED_CONVOS = 'shail_paused_conversations';
export const KEY_EXCLUDED_CHATS = 'shail_excluded_chats';
export const KEY_ACTIVE_CAPTURE = 'shail_active_capture';

export type CapturePolicy = 'capturing' | 'paused' | 'excluded';

interface ActiveCaptureOptions {
  isEligible?: () => boolean;
  isStreaming?: () => boolean;
  useRaceLock?: boolean;
  maxTurns?: number;
}

function normalizedUrl(): string {
  return location.href.split('#')[0].split('?')[0];
}

function storageList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter(v => typeof v === 'string') : [];
}

async function readStringList(key: string): Promise<string[]> {
  const result = await browser.storage.local.get(key);
  return storageList(result[key]);
}

async function writeStringList(key: string, list: string[]): Promise<void> {
  await browser.storage.local.set({ [key]: Array.from(new Set(list)) });
}

export async function chatFingerprint(adapter: PlatformAdapter): Promise<string> {
  const chatId = adapter.getChatID() || normalizedUrl();
  return sha256(`${adapter.detectPlatform()}:${chatId}`);
}

export async function getCapturePolicy(adapter: PlatformAdapter): Promise<CapturePolicy> {
  const [capturePrefs, paused, excluded, allowed] = await Promise.all([
    browser.storage.local.get(KEY_CAPTURE),
    readStringList(KEY_PAUSED_CONVOS),
    readStringList(KEY_EXCLUDED_CHATS),
    isCaptureAllowed(location.href),
  ]);

  const enabled = (capturePrefs[KEY_CAPTURE] as boolean | undefined) ?? true;
  const fp = await chatFingerprint(adapter);

  if (!allowed || excluded.includes(fp)) return 'excluded';
  if (!enabled || paused.includes(fp)) return 'paused';
  return 'capturing';
}

export async function shouldCaptureConversation(adapter: PlatformAdapter): Promise<boolean> {
  return (await getCapturePolicy(adapter)) === 'capturing';
}

export async function isConversationExcluded(adapter: PlatformAdapter): Promise<boolean> {
  const excluded = await readStringList(KEY_EXCLUDED_CHATS);
  return excluded.includes(await chatFingerprint(adapter));
}

export async function setConversationPaused(adapter: PlatformAdapter, paused: boolean): Promise<void> {
  const fp = await chatFingerprint(adapter);
  const list = await readStringList(KEY_PAUSED_CONVOS);
  const next = paused ? [...list, fp] : list.filter(id => id !== fp);
  await writeStringList(KEY_PAUSED_CONVOS, next);
}

export async function setConversationExcluded(adapter: PlatformAdapter, excluded: boolean): Promise<void> {
  const fp = await chatFingerprint(adapter);
  const list = await readStringList(KEY_EXCLUDED_CHATS);
  const next = excluded ? [...list, fp] : list.filter(id => id !== fp);
  await writeStringList(KEY_EXCLUDED_CHATS, next);
  if (excluded) {
    const paused = await readStringList(KEY_PAUSED_CONVOS);
    await writeStringList(KEY_PAUSED_CONVOS, paused.filter(id => id !== fp));
  }
}

function emitBarEvent(adapter: PlatformAdapter, detail: Record<string, unknown>) {
  window.dispatchEvent(new CustomEvent('shail-capture-event', {
    detail: {
      platform: adapter.sourceApp,
      title: adapter.detectChatTitle(),
      ...detail,
    },
  }));
}

function renderedTranscript(users: StructuredMessage[], assistants: StructuredMessage[], maxTurns: number): {
  assistantText: string;
  userText: string;
  segments: CaptureSegment[];
  turnCount: number;
  latestAssistantText: string;
} | null {
  if (!assistants.length) return null;

  const start = 0;
  const chunks: string[] = [];
  const segments: CaptureSegment[] = [];

  for (let i = start; i < assistants.length; i += 1) {
    const user = users[Math.min(i, Math.max(users.length - 1, 0))];
    const assistant = assistants[i];
    if (user?.text) chunks.push(`User: ${user.text}`);
    if (assistant?.text) chunks.push(`Assistant: ${assistant.text}`);
    if (user?.segments) segments.push(...user.segments);
    if (assistant?.segments) segments.push(...assistant.segments);
  }

  const latestAssistant = assistants[assistants.length - 1];
  const latestUser = users[Math.min(assistants.length - 1, Math.max(users.length - 1, 0))];

  return {
    assistantText: chunks.join('\n\n---\n\n').trim() || latestAssistant.text,
    userText: latestUser?.text || '',
    segments,
    turnCount: Math.max(users.length, assistants.length),
    latestAssistantText: latestAssistant.text,
  };
}

async function updateActiveCaptureCache(
  adapter: PlatformAdapter,
  state: string,
  turnCount: number,
  result?: CaptureResult | null,
) {
  const identity = await resolveConversationIdentity(location.href, adapter.sourceApp);
  const conversationId = identity.conversationId;
  const memoryId = result?.memoryId;
  await browser.storage.local.set({
    [KEY_ACTIVE_CAPTURE]: {
      state,
      platform: adapter.sourceApp,
      title: adapter.detectChatTitle(),
      turnCount,
      progressValue: 0,
      conversationId,
      memoryId,
      sourceUrl: location.href,
      updatedAt: new Date().toISOString(),
    },
  });
}

export function startActiveCapture(adapter: PlatformAdapter, options: ActiveCaptureOptions = {}) {
  let lastUrl = location.href;
  let lastSeenText = '';
  let lastCapturedText = '';
  let capturedTurnCount = 0;
  let stopObserver: (() => void) | null = null;
  const maxTurns = options.maxTurns ?? 10;

  async function tryCapture() {
    if (options.isEligible && !options.isEligible()) return;

    const policy = await getCapturePolicy(adapter);
    emitBarEvent(adapter, { state: policy === 'capturing' ? 'listening' : policy, turnCount: capturedTurnCount });
    if (policy !== 'capturing') return;

    if (options.isStreaming?.()) return;

    const messages = adapter.extractMessages(document);
    const users = messages.filter(m => m.role === 'user');
    const assistants = messages.filter(m => m.role === 'assistant');
    const transcript = renderedTranscript(users, assistants, maxTurns);
    if (!transcript?.latestAssistantText) return;

    if (/\]\(https?:\/\//.test(transcript.latestAssistantText.slice(0, 200))) return;
    if (transcript.latestAssistantText === lastSeenText) return;
    lastSeenText = transcript.latestAssistantText;

    const { bucket } = scoreContent(transcript.latestAssistantText);
    if (bucket === 'skip') return;

    const identity = await resolveConversationIdentity(location.href, adapter.sourceApp);
    const conversationId = identity.conversationId;
    if (!conversationId) {
      const cid = await makeCaptureId(location.href, transcript.assistantText);
      const stored = await browser.storage.local.get('shail_doc_index');
      const index = (stored['shail_doc_index'] as Array<{ customId?: string }>) ?? [];
      if (index.some(e => e.customId === cid)) return;
    }

    if (transcript.latestAssistantText === lastCapturedText) return;
    lastCapturedText = transcript.latestAssistantText;
    capturedTurnCount = transcript.turnCount;

    if (!await shouldCaptureConversation(adapter)) {
      emitBarEvent(adapter, { state: await getCapturePolicy(adapter), turnCount: capturedTurnCount });
      return;
    }

    emitBarEvent(adapter, { state: 'capturing', turnCount: transcript.turnCount });
    await updateActiveCaptureCache(adapter, 'CAPTURING', transcript.turnCount);

    try {
      const candidate = await buildAiCandidate({
        sourceApp: adapter.sourceApp,
        userText: transcript.userText,
        assistantText: transcript.assistantText,
        conversationId,
        conversationIdTemporary: identity.temporary,
        previousConversationId: identity.previousConversationId,
        segments: transcript.segments,
        title: adapter.detectChatTitle(),
      });
      candidate.turnCount = transcript.turnCount;

      if (options.useRaceLock ?? true) {
        submitDomCaptureBuffer(candidate);
        await updateActiveCaptureCache(adapter, 'LISTENING', transcript.turnCount);
        emitBarEvent(adapter, { state: 'captured', turnCount: transcript.turnCount });
      } else {
        const result = await sendCapture(candidate);
        await updateActiveCaptureCache(adapter, 'LISTENING', transcript.turnCount, result);
        emitBarEvent(adapter, {
          state: 'captured',
          turnCount: transcript.turnCount,
          memoryId: result?.memoryId,
        });
      }
    } catch {
      emitBarEvent(adapter, { state: 'error', turnCount: transcript.turnCount });
      await updateActiveCaptureCache(adapter, 'ERROR', transcript.turnCount);
    }
  }

  function attachObserver() {
    stopObserver?.();
    if (options.isEligible && !options.isEligible()) return;
    stopObserver = observeWithStability(document.body, tryCapture, 500);
    window.setTimeout(() => { tryCapture().catch(() => {}); }, 800);
  }

  attachObserver();

  const navObserver = new MutationObserver(() => {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    lastSeenText = '';
    lastCapturedText = '';
    capturedTurnCount = 0;
    attachObserver();
  });
  navObserver.observe(document.body, { childList: true, subtree: true });

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes[KEY_CAPTURE] || changes[KEY_PAUSED_CONVOS] || changes[KEY_EXCLUDED_CHATS]) {
      tryCapture().catch(() => {});
    }
  });
}
