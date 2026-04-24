import { buildAiCandidate, observeWithStability, sendCapture } from '../src/lib/capture';
import { scoreContent } from '../src/lib/importance';
import { showCapturePrompt } from '../src/lib/notify';

export default defineContentScript({
  matches: ['https://claude.ai/*'],
  runAt: 'document_idle',

  main() {
    let lastSeenText     = '';
    let lastCapturedText = '';
    let stopObserver: (() => void) | null = null;

    const ASSISTANT_SELECTORS = [
      '.font-claude-message',
      '[data-testid="assistant-message"]',
      '.assistant-message',
      '[class*="AssistantMessage"]',
    ];

    const USER_SELECTORS = [
      '[data-testid="user-message"]',
      '.human-turn p',
      '[class*="HumanMessage"]',
      '[class*="UserMessage"]',
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
        document.querySelector('button[aria-label="Stop"]') ||
        document.querySelector('[data-is-streaming="true"]') ||
        document.querySelector('.streaming-indicator')
      );
    }

    async function tryCapture() {
      if (isStreaming()) return;

      const assistantEl = queryLast(ASSISTANT_SELECTORS);
      if (!assistantEl) return;

      const assistantText = assistantEl.innerText.trim();
      if (!assistantText || assistantText === lastSeenText) return;

      lastSeenText = assistantText;

      const { bucket } = scoreContent(assistantText);
      if (bucket === 'skip') return;

      const userEl  = queryLast(USER_SELECTORS);
      const userText = userEl?.innerText.trim() ?? '';

      async function doCapture() {
        if (assistantText === lastCapturedText) return;
        lastCapturedText = assistantText;
        const candidate = await buildAiCandidate({ sourceApp: 'claude', userText, assistantText });
        await sendCapture(candidate);
      }

      // Always show the prompt — never auto-save silently.
      showCapturePrompt({
        title:     userText || document.title,
        sourceApp: 'claude',
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
