import { startActiveCapture } from '../src/lib/active-capture-orchestrator';
import { PLATFORM_ADAPTERS } from '../src/lib/platform-adapters';

export default defineContentScript({
  matches: [
    'https://www.perplexity.ai/*',
    'https://perplexity.ai/*',
  ],
  runAt: 'document_idle',

  main() {
    startActiveCapture(PLATFORM_ADAPTERS.perplexity, {
      isStreaming: () => !!(
        document.querySelector('[aria-label="Stop"]') ||
        document.querySelector('.loading-animation') ||
        document.querySelector('[class*="StopButton"]')
      ),
      useRaceLock: false,
    });
  },
});
