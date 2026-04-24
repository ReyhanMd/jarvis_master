import { Readability } from '@mozilla/readability';
import { makeCaptureId, sendCapture } from '../src/lib/capture';
import { showCapturePrompt } from '../src/lib/notify';

// Domains handled by dedicated adapters — skip them here
const AI_SITE_PATTERNS = [
  'chat.openai.com',
  'chatgpt.com',
  'claude.ai',
  'gemini.google.com',
  'bard.google.com',
  'perplexity.ai',
];

const DWELL_MS = 30_000;       // 30 seconds
const SCROLL_THRESHOLD = 0.40; // 40% of page height

export default defineContentScript({
  matches: ['<all_urls>'],
  runAt: 'document_idle',

  main() {
    // Skip AI sites — they have dedicated adapters
    const hostname = location.hostname;
    if (AI_SITE_PATTERNS.some(p => hostname === p || hostname.endsWith(`.${p}`))) {
      return;
    }

    // Skip non-http pages (chrome://, file://, etc.)
    if (!location.protocol.startsWith('http')) return;

    // Skip pages that Readability won't parse well (e.g. pure apps, dashboards)
    // We check this after the dwell threshold is met

    let dwellMet = false;
    let scrollMet = false;
    let captured = false;

    // ── Dwell timer ──────────────────────────────────────────────────────────
    const dwellTimer = setTimeout(() => {
      dwellMet = true;
      maybeCapture();
    }, DWELL_MS);

    // ── Scroll tracker ───────────────────────────────────────────────────────
    function onScroll() {
      if (scrollMet) return;
      const scrolled = window.scrollY + window.innerHeight;
      const total = document.documentElement.scrollHeight;
      if (total > 0 && scrolled / total >= SCROLL_THRESHOLD) {
        scrollMet = true;
        window.removeEventListener('scroll', onScroll);
        maybeCapture();
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true });

    // ── Capture ──────────────────────────────────────────────────────────────
    async function maybeCapture() {
      if (!dwellMet || !scrollMet || captured) return;
      captured = true;

      // Clean up listeners
      clearTimeout(dwellTimer);
      window.removeEventListener('scroll', onScroll);

      // Parse page content with Readability
      let title = document.title;
      let textContent = '';

      try {
        const docClone = document.cloneNode(true) as Document;
        const article = new Readability(docClone).parse();
        if (!article || !article.textContent?.trim()) return; // not an article — skip
        title = article.title || title;
        textContent = article.textContent.trim().slice(0, 2000);
      } catch {
        return;
      }

      if (!textContent) return;

      // Quality filter: skip pages that aren't real articles
      // 1. Too short to be meaningful
      if (textContent.length < 300) return;
      // 2. High markdown-link density → app UI captured by mistake
      //    (e.g. X.com "JavaScript disabled" page, navigation pages)
      const linkPatterns = (textContent.match(/\]\(https?:\/\//g) ?? []).length;
      const wordCount = textContent.split(/\s+/).length;
      if (linkPatterns > 5 && linkPatterns / wordCount > 0.05) return;
      // 3. Skip common low-value error pages
      const lowerText = textContent.toLowerCase();
      if (
        lowerText.includes('javascript is disabled') ||
        lowerText.includes('enable javascript') ||
        lowerText.includes('cookies are disabled')
      ) return;

      const url = location.href;
      const customId = await makeCaptureId(url, textContent);

      // ── Dedup: skip silently if this page is already in the local index ───
      // Check by customId (exact) and by sourceUrl (same page, different day).
      // This prevents re-capturing a page the user already has in memory.
      {
        const dupCheck  = await browser.storage.local.get('shail_doc_index');
        const dupIndex  = (dupCheck['shail_doc_index'] as Array<{ customId?: string; sourceUrl?: string; eventType?: string }>) ?? [];
        const duplicate =
          dupIndex.some(e => e.customId === customId) ||
          dupIndex.some(e => e.sourceUrl === url && e.eventType === 'page_visit');
        if (duplicate) return;
      }

      // Show save/skip banner — never auto-send for web pages
      showCapturePrompt({
        title:     title || url,
        sourceApp: 'web',
        onSave: () => sendCapture({
          customId,
          eventType: 'page_visit',
          sourceApp: 'web',
          sourceUrl: url,
          timestamp: new Date().toISOString(),
          title,
          pageContent: textContent,
        }),
        onSkip: () => {},
      });
    }

    // Edge case: very long pages where user scrolls immediately
    // If page is short enough that full content is visible on load, treat scroll as met
    const docHeight = document.documentElement.scrollHeight;
    const viewHeight = window.innerHeight;
    if (docHeight <= viewHeight * 1.1) {
      scrollMet = true;
    }
  },
});
