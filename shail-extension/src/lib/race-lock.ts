import type { CaptureCandidate } from '../types/contracts';
import { sendCapture } from './capture';

/**
 * race-lock.ts — Manages the active double-capture race-lock.
 *
 * When both DOM scraping and API interception capture the same turn,
 * we delay the DOM capture by 1000ms. If the API capture arrives
 * during that window, the DOM capture is discarded.
 */

interface PendingCapture {
  candidate: CaptureCandidate;
  timeoutId: ReturnType<typeof setTimeout>;
}

// Key is `${conversationId}` (we rely on timestamp/turn-count logic to match)
const pendingDomCaptures = new Map<string, PendingCapture>();

/**
 * Submits a DOM-based capture into the race-lock delay buffer.
 * It will be sent to the backend after 1000ms unless an API capture cancels it.
 */
export function submitDomCaptureBuffer(candidate: CaptureCandidate) {
  if (!candidate.conversationId) {
    // If we don't have a conversation ID, we can't reliably deduplicate.
    // Just send it immediately.
    sendCapture(candidate).catch(console.error);
    return;
  }

  const key = candidate.conversationId;

  // Clear any existing pending DOM capture for this conversation
  // (Assuming rapid typing could trigger multiple, we only keep the latest)
  if (pendingDomCaptures.has(key)) {
    clearTimeout(pendingDomCaptures.get(key)!.timeoutId);
    pendingDomCaptures.delete(key);
  }

  const timeoutId = setTimeout(async () => {
    pendingDomCaptures.delete(key);
    try {
      await sendCapture(candidate);
    } catch (err) {
      console.error('Failed to send DOM capture from buffer', err);
    }
  }, 1000);

  pendingDomCaptures.set(key, { candidate, timeoutId });
}

/**
 * Submits an API-based capture. This immediately sends the API capture
 * and cancels any pending DOM capture for the same conversation.
 */
export async function submitApiCaptureBuffer(candidate: CaptureCandidate) {
  if (candidate.conversationId) {
    const key = candidate.conversationId;
    
    // Cancel the DOM capture if it's pending
    if (pendingDomCaptures.has(key)) {
      clearTimeout(pendingDomCaptures.get(key)!.timeoutId);
      pendingDomCaptures.delete(key);
      console.log(`[SHAIL Race-Lock] Discarded DOM capture for ${key} in favor of API capture.`);
    }
  }

  // Send the higher-quality API capture immediately
  try {
    await sendCapture(candidate);
  } catch (err) {
    console.error('Failed to send API capture', err);
  }
}

/**
 * Force sends any pending DOM capture immediately, bypassing the 1000ms buffer.
 * Used when the API parser explicitly fails and falls back to DOM.
 */
export function flushDomCaptureBuffer(conversationId: string) {
  const pending = pendingDomCaptures.get(conversationId);
  if (pending) {
    clearTimeout(pending.timeoutId);
    pendingDomCaptures.delete(conversationId);
    sendCapture(pending.candidate).catch(console.error);
  }
}
