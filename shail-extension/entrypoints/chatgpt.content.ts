import { startActiveCapture } from '../src/lib/active-capture-orchestrator';
import { extractConversationId } from '../src/lib/conversation-id';
import { PLATFORM_ADAPTERS } from '../src/lib/platform-adapters';
import { flushDomCaptureBuffer } from '../src/lib/race-lock';

export default defineContentScript({
  matches: ['https://chat.openai.com/*', 'https://chatgpt.com/*'],
  runAt: 'document_idle',

  main() {
    startActiveCapture(PLATFORM_ADAPTERS.chatgpt, {
      isEligible: () => /^\/c\/[a-z0-9-]+/i.test(location.pathname),
      isStreaming: () => !!document.querySelector(
        'button[aria-label="Stop generating"], button[data-testid="stop-button"]',
      ),
      useRaceLock: true,
    });

    window.addEventListener('shail-api-parse-failed', ((e: CustomEvent) => {
      if (e.detail?.platform !== 'chatgpt') return;
      const conversationId = extractConversationId(location.href, 'chatgpt');
      if (conversationId) flushDomCaptureBuffer(conversationId);
    }) as EventListener);
  },
});
