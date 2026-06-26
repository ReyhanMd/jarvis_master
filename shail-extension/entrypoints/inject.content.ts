/**
 * inject.content.ts — listens for INJECT_TEXT messages from the sidepanel
 * and inserts text into the page's AI composer.
 *
 * The API interceptor is installed by api-interceptor-main.content.ts in the
 * main world. This isolated script only receives and parses the forwarded
 * CustomEvent payloads.
 *
 * Registered on all AI sites (and a fallback <all_urls> catch-all so the
 * sidepanel's sendMessage never throws "Could not establish connection").
 */
import { injectText } from '../src/lib/inject';
import { parseApiPayload, parseApiSessionPayload } from '../src/lib/api-parsers';
import { saveApiSessionCapture } from '../src/lib/api-capture-cache';
import { submitApiCaptureBuffer } from '../src/lib/race-lock';
import type { SourceApp } from '../src/types/contracts';

export default defineContentScript({
  matches: [
    'https://chat.openai.com/*',
    'https://chatgpt.com/*',
    'https://claude.ai/*',
    'https://gemini.google.com/*',
    'https://www.perplexity.ai/*',
    'https://perplexity.ai/*',
    'https://grok.com/*',
    'https://x.ai/*',
    '<all_urls>',
  ],
  runAt: 'document_idle',

  main() {
    // ── Text injection handler (existing) ──────────────────────────────
    browser.runtime.onMessage.addListener((message: unknown) => {
      if (
        typeof message === 'object' &&
        message !== null &&
        (message as Record<string, unknown>).type === 'INJECT_TEXT'
      ) {
        const text = ((message as Record<string, unknown>).payload as Record<string, unknown>)?.text as string ?? '';
        const ok = injectText(text);
        return Promise.resolve({ ok });
      }
    });

    // ── Forward API intercept events to race-lock buffer ────────────────
    window.addEventListener('shail-api-intercept', (async (event: CustomEvent) => {
      try {
        const { platform, url, payload } = event.detail;
        const sessionCandidate = await parseApiSessionPayload(platform as SourceApp, url, payload);
        if (sessionCandidate) {
          await saveApiSessionCapture(sessionCandidate);
        }
        const candidate = await parseApiPayload(platform as SourceApp, url, payload);
        if (candidate) {
          await submitApiCaptureBuffer(candidate);
        }
      } catch (err) {
        console.error('[SHAIL API Interceptor] parse failed:', err);
      }
    }) as unknown as EventListener);
  },
});
