import { startActiveCapture } from '../src/lib/active-capture-orchestrator';
import { extractConversationId } from '../src/lib/conversation-id';
import { PLATFORM_ADAPTERS } from '../src/lib/platform-adapters';
import { flushDomCaptureBuffer } from '../src/lib/race-lock';

export default defineContentScript({
  matches: [
    'https://gemini.google.com/*',
    'https://bard.google.com/*',
  ],
  runAt: 'document_idle',

  main() {
    startActiveCapture(PLATFORM_ADAPTERS.gemini, {
      isStreaming: () => !!(
        document.querySelector('.loading-indicator') ||
        document.querySelector('[aria-label="Stop"]') ||
        document.querySelector('mat-progress-bar')
      ),
      useRaceLock: true,
    });

    window.addEventListener('shail-api-parse-failed', ((e: CustomEvent) => {
      if (e.detail?.platform !== 'gemini') return;
      const conversationId = extractConversationId(location.href, 'gemini');
      if (conversationId) flushDomCaptureBuffer(conversationId);
    }) as EventListener);
  },
});
