import { startActiveCapture } from '../src/lib/active-capture-orchestrator';
import { extractConversationId } from '../src/lib/conversation-id';
import { PLATFORM_ADAPTERS } from '../src/lib/platform-adapters';
import { flushDomCaptureBuffer } from '../src/lib/race-lock';

export default defineContentScript({
  matches: ['https://claude.ai/*'],
  runAt: 'document_idle',

  main() {
    startActiveCapture(PLATFORM_ADAPTERS.claude, {
      isStreaming: () => !!(
        document.querySelector('button[aria-label="Stop"]') ||
        document.querySelector('[data-is-streaming="true"]') ||
        document.querySelector('.streaming-indicator')
      ),
      useRaceLock: true,
    });

    window.addEventListener('shail-api-parse-failed', ((e: CustomEvent) => {
      if (e.detail?.platform !== 'claude') return;
      const conversationId = extractConversationId(location.href, 'claude');
      if (conversationId) flushDomCaptureBuffer(conversationId);
    }) as EventListener);
  },
});
