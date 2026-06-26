import { startActiveCapture } from '../src/lib/active-capture-orchestrator';
import { PLATFORM_ADAPTERS } from '../src/lib/platform-adapters';

export default defineContentScript({
  matches: [
    'https://grok.com/*',
    'https://x.ai/*',
  ],
  runAt: 'document_idle',

  main() {
    startActiveCapture(PLATFORM_ADAPTERS.grok, {
      isStreaming: () => !!(
        document.querySelector('[aria-label="Stop"]') ||
        document.querySelector('[data-testid="stop-button"]') ||
        document.querySelector('.streaming-cursor') ||
        document.querySelector('[class*="StopButton"]')
      ),
      useRaceLock: false,
    });
  },
});
