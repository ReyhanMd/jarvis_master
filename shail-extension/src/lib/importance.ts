/**
 * importance.ts — Rule-based importance scorer for captured AI responses.
 *
 * Runs entirely in the browser (content script context).
 * Zero API calls, zero latency, zero cost.
 *
 * Bucket thresholds:
 *   score >= 40 → AUTO-SAVE  (silent capture, green badge)
 *   score 10-39 → ASK-USER   (show notification widget)
 *   score < 10  → SKIP       (drop silently)
 */

export type CaptureBucket = 'auto-save' | 'ask-user' | 'skip';

export interface ScoreResult {
  score:   number;
  bucket:  CaptureBucket;
  reasons: string[];   // human-readable signal labels (for debugging)
}

// ─── Trivial-opener patterns ──────────────────────────────────────────────────
// These are responses where the AI is just being polite, not providing value.
// If text starts with one of these AND is under 200 chars → instant skip.
const TRIVIAL_OPENERS = [
  /^(sure|of course|certainly|absolutely)[!.,\s]/i,
  /^(great question|good question)[!.,\s]/i,
  /^(i('d| would) be happy to|happy to help)[!.,\s]/i,
  /^(i('ll| will) help)[!.,\s]/i,
  /^(you're welcome|you are welcome)[!.,\s]/i,
  /^(glad i could|no problem|my pleasure|anytime)[!.,\s]/i,
  /^(hello|hi|hey)[!,\s]/i,
  /^(thanks for (asking|reaching out|the question))[!.,\s]/i,
  /^(of course[,!]?\s*(i('d| would) be happy|here('s| is)))/i,
];

// ─── High-value keyword signals ───────────────────────────────────────────────
// These words appearing in the response strongly suggest actionable content.
const VALUE_KEYWORDS = [
  'solution', 'approach', 'example', 'steps', 'step-by-step',
  'implementation', 'how to', 'guide', 'tutorial', 'walkthrough',
  'algorithm', 'function', 'method', 'process', 'workflow',
  'architecture', 'pattern', 'strategy', 'framework', 'configuration',
  'install', 'setup', 'deploy', 'debug', 'fix', 'resolve',
];

// ─── Main scorer ──────────────────────────────────────────────────────────────

export function scoreContent(text: string): ScoreResult {
  const trimmed = text.trim();
  const reasons: string[] = [];

  // ── Instant skip: too short to be useful ──────────────────────────────────
  if (trimmed.length < 80) {
    return { score: 0, bucket: 'skip', reasons: ['too short (<80 chars)'] };
  }

  // ── Instant skip: trivial opener + short reply ────────────────────────────
  // Only skip if BOTH: starts with a trivial phrase AND is short
  if (trimmed.length < 200 && TRIVIAL_OPENERS.some(p => p.test(trimmed))) {
    return { score: 0, bucket: 'skip', reasons: ['trivial opener + short'] };
  }

  let score = 0;

  // ── Signal: length ────────────────────────────────────────────────────────
  if (trimmed.length > 200)  { score += 5;  reasons.push('medium length');      }
  if (trimmed.length > 500)  { score += 10; reasons.push('long response');      }
  if (trimmed.length > 1500) { score += 15; reasons.push('very long response'); }

  // ── Signal: code block (strongest indicator of actionable content) ────────
  if (/```/.test(trimmed)) {
    score += 30;
    reasons.push('contains code block');
  }

  // ── Signal: structured lists ──────────────────────────────────────────────
  if (/^\d+\.\s+\S/m.test(trimmed)) {
    score += 15;
    reasons.push('numbered list');
  }
  if (/^[-*]\s+\S/m.test(trimmed)) {
    score += 10;
    reasons.push('bullet points');
  }

  // ── Signal: markdown headers ──────────────────────────────────────────────
  if (/^#{1,3}\s+\S/m.test(trimmed)) {
    score += 10;
    reasons.push('markdown headers');
  }

  // ── Signal: table ─────────────────────────────────────────────────────────
  if (/\|.+\|.+\|/.test(trimmed)) {
    score += 10;
    reasons.push('table');
  }

  // ── Signal: multiple content paragraphs ──────────────────────────────────
  const paragraphs = trimmed.split(/\n{2,}/).filter(p => p.trim().length > 50);
  if (paragraphs.length >= 3) {
    score += 5;
    reasons.push(`${paragraphs.length} paragraphs`);
  }

  // ── Signal: value keywords ────────────────────────────────────────────────
  const matched = VALUE_KEYWORDS.filter(kw =>
    new RegExp(`\\b${kw.replace(/[-\s]/g, '[\\s-]')}\\b`, 'i').test(trimmed)
  );
  if (matched.length > 0) {
    const kwScore = Math.min(matched.length * 5, 20);
    score += kwScore;
    reasons.push(`keywords: ${matched.slice(0, 3).join(', ')}`);
  }

  // ── Bucket assignment ─────────────────────────────────────────────────────
  const bucket: CaptureBucket =
    score >= 40 ? 'auto-save' :
    score >= 10 ? 'ask-user'  :
                  'skip';

  return { score, bucket, reasons };
}

/**
 * Convenience wrapper that returns just the bucket label.
 * Use this in content scripts where you only need the decision.
 */
export function decideBucket(text: string): CaptureBucket {
  return scoreContent(text).bucket;
}
