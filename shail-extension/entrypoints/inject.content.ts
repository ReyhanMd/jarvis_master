/**
 * inject.content.ts — listens for INJECT_TEXT messages from the sidepanel
 * and inserts text into the page's AI composer.
 *
 * Registered on all AI sites (and a fallback <all_urls> catch-all so the
 * sidepanel's sendMessage never throws "Could not establish connection").
 */
import { injectText } from '../src/lib/inject';

export default defineContentScript({
  matches: [
    'https://chat.openai.com/*',
    'https://chatgpt.com/*',
    'https://claude.ai/*',
    'https://gemini.google.com/*',
    'https://www.perplexity.ai/*',
    'https://perplexity.ai/*',
    '<all_urls>',
  ],
  runAt: 'document_idle',

  main() {
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
  },
});
