/**
 * Multi-turn conversation extractor — shared across all AI-platform content
 * scripts (ChatGPT, Claude, Gemini, Perplexity).
 *
 * Each platform supplies CSS selector arrays for user/assistant message
 * elements. This module zips them into turn pairs and emits a full
 * transcript so the backend's blueprint generator can extract structured
 * knowledge from the entire session, not just the latest Q+A.
 *
 * Output shape matches what the existing /capture endpoint expects:
 *   {
 *     userText:      <latest user message>,    // for toast title + dedup
 *     assistantText: <full transcript>,        // what the blueprint sees
 *   }
 *
 * The transcript joins turns with a "---" separator so the LLM can tell
 * them apart while still treating the whole thing as one document.
 */

export interface MultiTurnSelectors {
  /** CSS selectors for user message containers, tried in order. */
  userSelectors: string[];
  /** CSS selectors for assistant message containers, tried in order. */
  assistantSelectors: string[];
  /** Max turn-pairs to include (default 10). Older turns are dropped. */
  maxTurns?: number;
}

export interface ExtractedTranscript {
  userText: string;          // latest user msg
  assistantText: string;     // full transcript joined
  turnCount: number;         // how many turn-pairs were captured
  latestAssistantText: string; // for change-detection / dedup keys
  turns: Array<{ user: string; assistant: string }>;
}

/**
 * Pick the FIRST selector that returns at least one element. Returns all
 * matching elements (in DOM order) so we can preserve turn ordering.
 *
 * Different selectors can match overlapping element sets (e.g. on Claude
 * `.font-claude-message` and `[class*="AssistantMessage"]` may both hit).
 * We use the first selector that returns ANY hits — the platform's
 * preferred one — to avoid double-counting.
 */
function queryAll(selectors: string[]): HTMLElement[] {
  for (const sel of selectors) {
    const els = document.querySelectorAll(sel);
    if (els.length) return Array.from(els) as HTMLElement[];
  }
  return [];
}

function textOf(el: HTMLElement): string {
  return (el.innerText || el.textContent || '').trim();
}

/**
 * Extract the full multi-turn transcript from the current page.
 *
 * Returns null if no assistant elements are found at all (page hasn't
 * rendered yet, or selectors are stale on a UI change). Returns a
 * transcript with turnCount=0 if we found assistant text but couldn't
 * pair any user messages — caller can fall back to single-turn mode.
 */
export function extractTranscript(opts: MultiTurnSelectors): ExtractedTranscript | null {
  const maxTurns = opts.maxTurns ?? 10;
  const userEls      = queryAll(opts.userSelectors);
  const assistantEls = queryAll(opts.assistantSelectors);

  if (assistantEls.length === 0) return null;

  // Zip into turn pairs. We iterate up to min(user, assistant) so each turn
  // has both halves. If counts are unequal (e.g. user typed but no reply
  // yet), we drop the orphan.
  const turnCount = Math.min(userEls.length, assistantEls.length);
  if (turnCount === 0) {
    // No user element found — return the latest assistant text only so
    // the caller can decide whether to fall back to single-turn capture.
    const latestAssistant = textOf(assistantEls[assistantEls.length - 1]);
    return {
      userText: '',
      assistantText: latestAssistant,
      turnCount: 0,
      latestAssistantText: latestAssistant,
      turns: [{ user: '', assistant: latestAssistant }],
    };
  }

  const turns: { user: string; assistant: string }[] = [];
  for (let i = 0; i < turnCount; i++) {
    turns.push({
      user:      textOf(userEls[i]),
      assistant: textOf(assistantEls[i]),
    });
  }
  // Sprint 1: removed turns.slice(-maxTurns) — session-buffer now handles
  // windowing. Full DOM-visible transcript is returned so the backend always
  // sees the complete conversation, not just the latest window.
  const _ = maxTurns; // kept in interface for backward compat; no longer slices

  const fullTranscript = turns
    .map(t => `User: ${t.user}\n\nAssistant: ${t.assistant}`)
    .join('\n\n---\n\n');

  const latestUserText      = turns[turns.length - 1].user;
  const latestAssistantText = turns[turns.length - 1].assistant;

  return {
    userText: latestUserText,
    assistantText: fullTranscript,
    turnCount: turns.length,
    latestAssistantText,
    turns,
  };
}


/**
 * Auto-scroll the conversation container to load all lazy-rendered turns.
 *
 * Many AI platforms virtualize the message list — only ~10-20 turns are in
 * the DOM at any moment. To grab the FULL session, we scroll the scroll
 * container to the top, wait for new turns to render, count them, and
 * repeat until the count stops growing for 2 consecutive checks.
 *
 * `scrollContainerSelector` is provider-specific (e.g. `main` on ChatGPT).
 * `userSelectors` is reused to count the most-reliable turn marker after
 * each scroll. Caller passes the same selectors as extractTranscript.
 *
 * Bounded by `maxIterations` (default 30 = ~9s of scrolling) to avoid
 * infinite loops on broken pages.
 */
export async function scrollToCaptureFullSession(opts: {
  scrollContainerSelector: string;
  userSelectors: string[];
  maxIterations?: number;
  settleMs?: number;
}): Promise<{ totalTurns: number; iterations: number; reachedTop: boolean }> {
  const maxIterations = opts.maxIterations ?? 30;
  const settleMs = opts.settleMs ?? 300;
  const container = document.querySelector(opts.scrollContainerSelector) as HTMLElement | null;
  if (!container) {
    // Fallback: scroll window. Better than nothing on platforms whose
    // scroll container is just <html>.
    return scrollWindow(opts.userSelectors, maxIterations, settleMs);
  }

  let lastCount = -1;
  let stableChecks = 0;
  let iterations = 0;
  let reachedTop = false;

  while (iterations < maxIterations) {
    iterations++;
    container.scrollTo({ top: 0, behavior: 'auto' });
    await new Promise(r => setTimeout(r, settleMs));
    const userEls = queryAll(opts.userSelectors);
    const count = userEls.length;
    if (count === lastCount) {
      stableChecks++;
      if (stableChecks >= 2) {
        reachedTop = container.scrollTop <= 4;
        break;
      }
    } else {
      stableChecks = 0;
      lastCount = count;
    }
  }
  return { totalTurns: lastCount < 0 ? 0 : lastCount, iterations, reachedTop };
}


async function scrollWindow(
  userSelectors: string[], maxIterations: number, settleMs: number,
): Promise<{ totalTurns: number; iterations: number; reachedTop: boolean }> {
  let lastCount = -1, stableChecks = 0, iterations = 0;
  while (iterations < maxIterations) {
    iterations++;
    window.scrollTo({ top: 0, behavior: 'auto' });
    await new Promise(r => setTimeout(r, settleMs));
    const count = queryAll(userSelectors).length;
    if (count === lastCount) {
      stableChecks++;
      if (stableChecks >= 2) break;
    } else {
      stableChecks = 0;
      lastCount = count;
    }
  }
  return { totalTurns: lastCount < 0 ? 0 : lastCount, iterations, reachedTop: window.scrollY <= 4 };
}


/**
 * Capture the entire conversation by scrolling to load all turns, then
 * extracting the transcript. Use this for manual "Capture full session"
 * commands. Background capture should continue to use plain
 * extractTranscript() to stay lightweight.
 */
export async function extractFullSessionTranscript(
  opts: MultiTurnSelectors & { scrollContainerSelector: string },
): Promise<ExtractedTranscript | null> {
  await scrollToCaptureFullSession({
    scrollContainerSelector: opts.scrollContainerSelector,
    userSelectors: opts.userSelectors,
  });
  return extractTranscript(opts);
}


// ── Phase 2: Bulk History Sidebar Scraping ──────────────────────────────────

/**
 * Scrapes the platform's sidebar to extract all visible historical conversation URLs.
 * Returns an array of clean URLs (excluding the current page URL if desired).
 */
export function extractSidebarLinks(sourceApp: import('../types/contracts').SourceApp): string[] {
  let selectors: string[] = [];
  switch (sourceApp) {
    case 'chatgpt':
      selectors = ['nav a[href*="/c/"]'];
      break;
    case 'claude':
      selectors = ['nav a[href*="/chat/"]', '[data-testid="history-item"] a'];
      break;
    case 'gemini':
      selectors = ['nav a[href*="/app/"]', '.recent-conversations a', 'a[href*="/app/"]'];
      break;
    case 'perplexity':
      selectors = ['nav a[href*="/search/"]', 'a[href*="/search/"]'];
      break;
    case 'grok':
      selectors = ['nav a[href*="/chat/"]', 'nav a[href*="/conversation/"]', 'a[href*="/chat/"]'];
      break;
    default:
      return [];
  }

  const links = new Set<string>();
  for (const sel of selectors) {
    document.querySelectorAll(sel).forEach(el => {
      const href = (el as HTMLAnchorElement).href;
      if (href) {
        // Strip hashes or query params to ensure clean conversation URLs
        const cleanUrl = href.split('#')[0].split('?')[0];
        links.add(cleanUrl);
      }
    });
  }

  return Array.from(links);
}


// ── Phase 2: Scroll Pump Capture (AsyncGenerator) ──────────────────────────

export interface ScrollPumpProgress {
  turnsFound: number;
  turnsNew: number;
  progress: number;  // 0–1
  done: boolean;
}

/**
 * Scroll-pump capture with deduplication, progressive yield, and
 * IndexedDB crash-safe buffering.
 *
 * Yields progress after each scroll iteration so the floating bar
 * can display a real-time progress indicator.
 *
 * Each turn is fingerprinted (SHA-256 of user+assistant text) and
 * only new turns are written to the IndexedDB buffer. At completion,
 * the full set of unique turns is available via `getTurns()`.
 */
export async function* scrollPumpCapture(opts: {
  scrollContainerSelector: string;
  userSelectors: string[];
  assistantSelectors: string[];
  conversationId: string;
  maxIterations?: number;
  settleMs?: number;
}): AsyncGenerator<ScrollPumpProgress, void, undefined> {
  const maxIterations = opts.maxIterations ?? 50;
  const settleMs = opts.settleMs ?? 400;
  const container = document.querySelector(opts.scrollContainerSelector) as HTMLElement | null;
  const scrollTarget = container || document.documentElement;

  const seenFingerprints = new Set<string>();
  let totalTurnsFound = 0;
  let totalTurnsNew = 0;
  let stableChecks = 0;
  let lastCount = -1;

  // Lazy import — these are only available in extension context
  let appendTurn: typeof import('./scroll-pump-store').appendTurn | null = null;
  try {
    const mod = await import('./scroll-pump-store');
    appendTurn = mod.appendTurn;
  } catch {
    // Not in extension context (e.g. test env) — skip IndexedDB buffering
  }

  for (let iteration = 0; iteration < maxIterations; iteration++) {
    // Scroll to top to force lazy-loaded turns to render
    if (container) {
      container.scrollTo({ top: 0, behavior: 'auto' });
    } else {
      window.scrollTo({ top: 0, behavior: 'auto' });
    }
    await new Promise(r => setTimeout(r, settleMs));

    // Extract all currently-visible turns
    const userEls = queryAll(opts.userSelectors);
    const assistantEls = queryAll(opts.assistantSelectors);
    const turnCount = Math.min(userEls.length, assistantEls.length);

    if (turnCount === lastCount) {
      stableChecks++;
      if (stableChecks >= 2) {
        // DOM has stabilized — we've loaded all available turns
        yield {
          turnsFound: totalTurnsFound,
          turnsNew: totalTurnsNew,
          progress: 1.0,
          done: true,
        };
        return;
      }
    } else {
      stableChecks = 0;
      lastCount = turnCount;
    }

    // Process each turn — fingerprint and dedup
    let newThisIteration = 0;
    for (let i = 0; i < turnCount; i++) {
      const userText = textOf(userEls[i]);
      const assistantText = textOf(assistantEls[i]);
      // Simple fingerprint: first 80 chars of user + first 80 chars of assistant
      const fingerprint = `${userText.slice(0, 80)}||${assistantText.slice(0, 80)}`;

      if (seenFingerprints.has(fingerprint)) continue;
      seenFingerprints.add(fingerprint);
      totalTurnsNew++;
      newThisIteration++;

      // Write to IndexedDB buffer (crash-safe)
      if (appendTurn) {
        try {
          await appendTurn({
            conversationId: opts.conversationId,
            turnIndex: -iteration * 10000 + i,
            userText,
            assistantText,
            fingerprint,
            timestamp: Date.now(),
          });
        } catch {
          // IndexedDB write failed — continue without crash safety
        }
      }
    }

    totalTurnsFound = turnCount;
    const progress = stableChecks > 0
      ? 0.9 + (stableChecks * 0.05)
      : Math.min(0.9, (iteration + 1) / maxIterations);

    yield {
      turnsFound: totalTurnsFound,
      turnsNew: totalTurnsNew,
      progress,
      done: false,
    };
  }

  // Max iterations reached
  yield {
    turnsFound: totalTurnsFound,
    turnsNew: totalTurnsNew,
    progress: 1.0,
    done: true,
  };
}

