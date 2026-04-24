import { sha256 } from './crypto';
import type { CaptureCandidate, SourceApp } from '../types/contracts';

/**
 * Builds a stable SHA-256 customId for deduplication.
 * Combines url + calendar date + a content fingerprint so the same page
 * visited twice on the same day produces the same ID.
 */
export async function makeCaptureId(
  url: string,
  contentFingerprint = '',
): Promise<string> {
  const date = new Date().toDateString(); // e.g. "Mon Apr 13 2026"
  return sha256(url + date + contentFingerprint.slice(0, 80));
}

/**
 * Sends a CaptureCandidate to the background service worker.
 * Silently drops the message if the extension context is invalidated
 * (e.g. user navigated away mid-capture).
 */
export async function sendCapture(candidate: CaptureCandidate): Promise<void> {
  try {
    await browser.runtime.sendMessage({ type: 'CAPTURE', payload: candidate });
  } catch {
    // Extension context invalidated or background not ready — ignore silently
  }
}

/**
 * Builds a CaptureCandidate for an AI conversation turn.
 */
export async function buildAiCandidate(opts: {
  sourceApp: SourceApp;
  userText: string;
  assistantText: string;
}): Promise<CaptureCandidate> {
  const url = window.location.href;
  const customId = await makeCaptureId(url, opts.assistantText);
  return {
    customId,
    eventType: 'ai_conversation',
    sourceApp: opts.sourceApp,
    sourceUrl: url,
    timestamp: new Date().toISOString(),
    title: document.title,
    userText: opts.userText,
    assistantText: opts.assistantText,
  };
}

/**
 * Debounced MutationObserver that fires `onStable` once DOM stops changing.
 * Returns a cleanup function.
 */
export function observeWithStability(
  root: Element | Document,
  onStable: () => void,
  stabilityMs = 500,
): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null;

  const observer = new MutationObserver(() => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(onStable, stabilityMs);
  });

  observer.observe(root, {
    childList: true,
    subtree: true,
    characterData: true,
  });

  return () => {
    if (timer) clearTimeout(timer);
    observer.disconnect();
  };
}
