import { buildAiCandidate, observeWithStability, sendCapture } from '../src/lib/capture';
import { scoreContent } from '../src/lib/importance';
import { showCapturePrompt } from '../src/lib/notify';

export default defineContentScript({
  matches: ['https://chat.openai.com/*', 'https://chatgpt.com/*'],
  runAt: 'document_idle',

  main() {
    // lastSeenText: text we have already PROCESSED (scored/shown widget for).
    //   Prevents re-triggering on the same response when the DOM re-renders.
    // lastCapturedText: text we have already SAVED.
    //   Prevents duplicate captures if the user saves via widget and the
    //   observer fires again before the next message.
    let lastSeenText     = '';
    let lastCapturedText = '';
    let stopObserver: (() => void) | null = null;

    function isConversationPage(): boolean {
      return /^\/c\/[a-z0-9-]+/i.test(location.pathname);
    }

    function getLastAssistantEl(): Element | null {
      const els = document.querySelectorAll("[data-message-author-role='assistant']");
      return els.length ? els[els.length - 1] : null;
    }

    function getLastUserText(): string {
      const els = document.querySelectorAll("[data-message-author-role='user']");
      return els.length ? (els[els.length - 1] as HTMLElement).innerText.trim() : '';
    }

    /** Collect the last N turns (user+assistant pairs) as a rich context block. */
    function buildConversationContext(maxTurns = 4): { userText: string; assistantText: string } {
      const userEls      = Array.from(document.querySelectorAll("[data-message-author-role='user']"));
      const assistantEls = Array.from(document.querySelectorAll("[data-message-author-role='assistant']"));

      // Zip into turn pairs (oldest first), then take the last maxTurns
      const turns: { user: string; assistant: string }[] = [];
      const count = Math.min(userEls.length, assistantEls.length);
      for (let i = 0; i < count; i++) {
        turns.push({
          user:      (userEls[i]      as HTMLElement).innerText.trim(),
          assistant: (assistantEls[i] as HTMLElement).innerText.trim(),
        });
      }
      const recent = turns.slice(-maxTurns);

      // Full conversation block (what goes into assistantText for storage)
      const fullContext = recent
        .map(t => `User: ${t.user}\n\nAssistant: ${t.assistant}`)
        .join('\n\n---\n\n');

      // The most recent user message (for the save prompt title)
      const latestUserText = recent.length ? recent[recent.length - 1].user : '';

      return { userText: latestUserText, assistantText: fullContext };
    }

    async function tryCapture() {
      if (!isConversationPage()) return;

      const assistantEl = getLastAssistantEl();
      if (!assistantEl) return;

      const assistantText = (assistantEl as HTMLElement).innerText.trim();
      if (!assistantText || assistantText === lastSeenText) return;

      // Guard: raw markdown syntax → wrong element (GPT picker / nav)
      if (/\]\(https?:\/\//.test(assistantText.slice(0, 200))) return;

      // Guard: streaming still in progress
      const stopBtn = document.querySelector(
        'button[aria-label="Stop generating"], button[data-testid="stop-button"]',
      );
      if (stopBtn) return;

      // Mark as seen so the observer doesn't re-fire for this response
      lastSeenText = assistantText;

      const { bucket } = scoreContent(assistantText);

      if (bucket === 'skip') return;

      const { userText, assistantText: conversationContext } = buildConversationContext(4);

      async function doCapture() {
        if (assistantText === lastCapturedText) return;
        lastCapturedText = assistantText;
        const candidate = await buildAiCandidate({
          sourceApp: 'chatgpt',
          userText,
          assistantText: conversationContext,
        });
        await sendCapture(candidate);
      }

      // Always show the prompt — never auto-save silently.
      // 'auto-save' and 'ask-user' both show the banner; 'skip' was filtered above.
      showCapturePrompt({
        title:     userText || document.title,
        sourceApp: 'chatgpt',
        onSave:    doCapture,
        onSkip:    () => {},
      });
    }

    function attachObserver() {
      stopObserver?.();
      if (!isConversationPage()) return;
      stopObserver = observeWithStability(document.body, tryCapture, 500);
    }

    attachObserver();

    // Re-attach on SPA navigation
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
