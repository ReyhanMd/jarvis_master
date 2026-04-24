import { buildAiCandidate, observeWithStability, sendCapture } from '../src/lib/capture';
import { scoreContent } from '../src/lib/importance';
import { showCapturePrompt } from '../src/lib/notify';

export default defineContentScript({
  matches: [
    'https://www.perplexity.ai/*',
    'https://perplexity.ai/*',
  ],
  runAt: 'document_idle',

  main() {
    let lastSeenText     = '';
    let lastCapturedText = '';
    let stopObserver: (() => void) | null = null;

    const ANSWER_SELECTORS = [
      '[class*="prose"]',
      '.answer-content',
      '[data-testid="answer"]',
      '[class*="AnswerBody"]',
      '.col-span-8 .prose',
    ];

    const QUERY_SELECTORS = [
      '[class*="QueryText"]',
      '.query-display',
      '[data-testid="query"]',
      'h1.line-clamp-2',
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
        document.querySelector('[aria-label="Stop"]') ||
        document.querySelector('.loading-animation') ||
        document.querySelector('[class*="StopButton"]')
      );
    }

    async function tryCapture() {
      if (isStreaming()) return;

      const answerEl = queryLast(ANSWER_SELECTORS);
      if (!answerEl) return;

      const assistantText = answerEl.innerText.trim();
      if (!assistantText || assistantText === lastSeenText) return;

      lastSeenText = assistantText;

      const { bucket } = scoreContent(assistantText);
      if (bucket === 'skip') return;

      const queryEl  = queryLast(QUERY_SELECTORS);
      const userText = queryEl?.innerText.trim() ?? document.title;

      async function doCapture() {
        if (assistantText === lastCapturedText) return;
        lastCapturedText = assistantText;
        const candidate = await buildAiCandidate({ sourceApp: 'perplexity', userText, assistantText });
        await sendCapture(candidate);
      }

      // Always show the prompt — never auto-save silently.
      showCapturePrompt({
        title:     userText || document.title,
        sourceApp: 'perplexity',
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
