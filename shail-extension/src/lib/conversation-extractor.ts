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
    turns: recent,
  };
}
