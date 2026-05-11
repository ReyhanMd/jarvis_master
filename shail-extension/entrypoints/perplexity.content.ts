import { buildAiCandidate, isCaptureAllowed, makeCaptureId, observeWithStability, sendCapture } from '../src/lib/capture';
import { extractTranscript } from '../src/lib/conversation-extractor';
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

    function isStreaming(): boolean {
      return !!(
        document.querySelector('[aria-label="Stop"]') ||
        document.querySelector('.loading-animation') ||
        document.querySelector('[class*="StopButton"]')
      );
    }

    async function tryCapture() {
      if (!await isCaptureAllowed(location.href)) return;
      if (isStreaming()) return;

      const transcript = extractTranscript({
        userSelectors: QUERY_SELECTORS,
        assistantSelectors: ANSWER_SELECTORS,
        maxTurns: 10,
      });
      if (!transcript) return;

      if (!transcript.latestAssistantText || transcript.latestAssistantText === lastSeenText) return;
      lastSeenText = transcript.latestAssistantText;

      const { bucket } = scoreContent(transcript.latestAssistantText);
      if (bucket === 'skip') return;

      const assistantPayload = transcript.turnCount > 0
        ? transcript.assistantText
        : transcript.latestAssistantText;
      const userText = transcript.userText || document.title;

      async function doCapture() {
        if (transcript.latestAssistantText === lastCapturedText) return;
        lastCapturedText = transcript.latestAssistantText;
        const candidate = await buildAiCandidate({
          sourceApp: 'perplexity',
          userText,
          assistantText: assistantPayload,
          turns: transcript.turns,
          selectorVersion: 'perplexity:answer-content:v1',
        });
        await sendCapture(candidate);
      }

      const cid = await makeCaptureId(location.href, assistantPayload);
      const stored = await browser.storage.local.get('shail_doc_index');
      const index = (stored['shail_doc_index'] as Array<{ customId?: string }>) ?? [];
      if (index.some(e => e.customId === cid)) return;

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
