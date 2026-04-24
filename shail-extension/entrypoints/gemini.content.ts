import { buildAiCandidate, observeWithStability, sendCapture } from '../src/lib/capture';
import { scoreContent } from '../src/lib/importance';
import { showCapturePrompt } from '../src/lib/notify';

export default defineContentScript({
  matches: [
    'https://gemini.google.com/*',
    'https://bard.google.com/*',
  ],
  runAt: 'document_idle',

  main() {
    let lastSeenText     = '';
    let lastCapturedText = '';
    let stopObserver: (() => void) | null = null;

    const RESPONSE_SELECTORS = [
      'model-response .markdown',
      'model-response',
      '.model-response-text',
      '[class*="response-content"]',
      'ms-text-chunk',
    ];

    const QUERY_SELECTORS = [
      '.query-text',
      '.user-query-bubble-with-background',
      'query-text',
      '[class*="QueryText"]',
    ];

    function queryLast(selectors: string[]): HTMLElement | null {
      for (const sel of selectors) {
        const els = document.querySelectorAll(sel);
        if (els.length) return els[els.length - 1] as HTMLElement;
      }
      return null;
    }

    function isStreaming(): boolean {
      return !!(
        document.querySelector('.loading-indicator') ||
        document.querySelector('[aria-label="Stop"]') ||
        document.querySelector('mat-progress-bar')
      );
    }

    async function tryCapture() {
      if (isStreaming()) return;

      const responseEl = queryLast(RESPONSE_SELECTORS);
      if (!responseEl) return;

      const assistantText = responseEl.innerText.trim();
      if (!assistantText || assistantText === lastSeenText) return;

      lastSeenText = assistantText;

      const { bucket } = scoreContent(assistantText);
      if (bucket === 'skip') return;

      const queryEl  = queryLast(QUERY_SELECTORS);
      const userText = queryEl?.innerText.trim() ?? '';

      async function doCapture() {
        if (assistantText === lastCapturedText) return;
        lastCapturedText = assistantText;
        const candidate = await buildAiCandidate({ sourceApp: 'gemini', userText, assistantText });
        await sendCapture(candidate);
      }

      // Always show the prompt — never auto-save silently.
      showCapturePrompt({
        title:     userText || document.title,
        sourceApp: 'gemini',
        onSave:    doCapture,
        onSkip:    () => {},
      });
    }

    function attachObserver() {
      stopObserver?.();
      stopObserver = observeWithStability(document.body, tryCapture, 500);
    }

    attachObserver();

    let lastUrl = location.href;
    const navObserver = new MutationObserver(() => {
      if (location.href !== lastUrl) {
        lastUrl          = location.href;
        lastSeenText     = '';
        lastCapturedText = '';
        attachObserver();
      }
    });
    navObserver.observe(document.body, { childList: true, subtree: true });
  },
});
