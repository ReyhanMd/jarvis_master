import { sha256 } from './crypto';
import { isDomainDenied } from './utils';
import { appendToSessionBuffer, buildFullTranscript } from './session-buffer';
import type {
  CaptureCandidate,
  CaptureResult,
  DashboardCardPayload,
  GithubDiffPayload,
  HtmlTablePayload,
  SitePolicy,
  SourceApp,
  SvgChartPayload,
  CaptureSegment,
} from '../types/contracts';

// ─── Policy cache (30s TTL) ───────────────────────────────────────────────────

let _policyCache: SitePolicy[] | null = null;
let _policyCacheAt = 0;
const POLICY_TTL_MS = 30_000;

export async function isCaptureAllowed(url: string): Promise<boolean> {
  const now = Date.now();
  if (_policyCache === null || now - _policyCacheAt > POLICY_TTL_MS) {
    try {
      const stored = await browser.storage.local.get('shail_policies');
      _policyCache = (stored['shail_policies'] as SitePolicy[]) ?? [];
    } catch {
      _policyCache = [];
    }
    _policyCacheAt = now;
  }
  return !isDomainDenied(url, _policyCache);
}

/**
 * Builds a stable SHA-256 customId for deduplication.
 * Combines url + calendar date + a content fingerprint so the same page
 * visited twice on the same day produces the same ID.
 */
export async function makeCaptureId(
  url: string,
  contentFingerprint = '',
): Promise<string> {
  const date = new Date().toDateString(); // e.g. "Mon Apr 13 2026"
  return sha256(url + date + contentFingerprint.slice(0, 80));
}

/**
 * Sends a CaptureCandidate to the background service worker.
 * Silently drops the message if the extension context is invalidated
 * (e.g. user navigated away mid-capture).
 */
export async function sendCapture(candidate: CaptureCandidate): Promise<CaptureResult | null> {
  try {
    const response = await browser.runtime.sendMessage({ type: 'CAPTURE', payload: candidate });
    if (response?.ok) return response.data as CaptureResult;
    return null;
  } catch {
    // Extension context invalidated or background not ready — ignore silently
    return null;
  }
}

/**
 * Builds a CaptureCandidate for an AI conversation turn.
 *
 * When conversationId is supplied (Sprint 1+):
 *   - customId is stable across all captures of the same conversation
 *   - The session buffer accumulates the full transcript across page refreshes
 *   - Background dedup ring is bypassed (backend handles upsert idempotently)
 *
 * When conversationId is absent (non-conversation pages, unknown URL patterns):
 *   - Falls back to legacy content-fingerprint customId
 *   - No buffer involvement
 */
export async function buildAiCandidate(opts: {
  sourceApp: SourceApp;
  userText: string;
  assistantText: string;
  conversationId?: string;
  conversationIdTemporary?: boolean;
  previousConversationId?: string;
  segments?: CaptureSegment[];
  title?: string;
}): Promise<CaptureCandidate> {
  const url = window.location.href;

  let customId: string;
  let finalAssistantText: string;

  if (opts.conversationId) {
    customId = await sha256('shail_session_' + opts.conversationId);
    const buffer = await appendToSessionBuffer(opts.conversationId, opts.assistantText);
    finalAssistantText = buildFullTranscript(buffer);
  } else {
    customId = await makeCaptureId(url, opts.assistantText);
    finalAssistantText = opts.assistantText;
  }

  return {
    customId,
    conversationId: opts.conversationId,
    conversationIdTemporary: opts.conversationIdTemporary,
    previousConversationId: opts.previousConversationId,
    eventType: 'ai_conversation',
    sourceApp: opts.sourceApp,
    sourceUrl: url,
    timestamp: new Date().toISOString(),
    title: opts.title ?? document.title,
    userText: opts.userText,
    assistantText: finalAssistantText,
    segments: opts.segments,
    captureMode: 'active',
  };
}

/**
 * Builds a CaptureCandidate for a fully-fetched PDF (base64 bytes included).
 */
export async function buildPdfBytesCandidate(opts: {
  base64: string;
  contentStub: string;
}): Promise<CaptureCandidate> {
  const url = window.location.href;
  const customId = await sha256(url + opts.base64.slice(0, 64));
  return {
    customId,
    eventType: 'pdf_doc',
    sourceApp: 'web' as SourceApp,
    sourceUrl: url,
    timestamp: new Date().toISOString(),
    title: document.title || opts.contentStub,
    pageContent: opts.contentStub,
    artifactMimeType: 'application/pdf',
    artifactBase64: opts.base64,
    artifactCompleteness: 'complete',
  };
}

/**
 * Builds a CaptureCandidate for a PDF when byte-fetching failed — stores URL stub only.
 */
export async function buildPdfStubCandidate(opts: {
  contentStub: string;
}): Promise<CaptureCandidate> {
  const url = window.location.href;
  const customId = await sha256(url + new Date().toDateString());
  return {
    customId,
    eventType: 'pdf_doc',
    sourceApp: 'web' as SourceApp,
    sourceUrl: url,
    timestamp: new Date().toISOString(),
    title: document.title || opts.contentStub,
    pageContent: opts.contentStub,
    artifactMimeType: 'application/pdf',
    artifactCompleteness: 'stub',
  };
}

/**
 * Builds a CaptureCandidate from structured DOM extraction (tables, cards, SVG charts).
 * Returns null if no structured content was found.
 */
export async function buildStructuredDomCandidate(opts: {
  pageContent: string;
  tables: HtmlTablePayload[];
  cards: DashboardCardPayload[];
  charts: SvgChartPayload[];
}): Promise<CaptureCandidate | null> {
  const hasStructured = opts.tables.length > 0 || opts.cards.length > 0 || opts.charts.length > 0;
  if (!hasStructured) return null;
  const url = window.location.href;
  const customId = await sha256(url + new Date().toDateString() + opts.pageContent.slice(0, 80));
  return {
    customId,
    eventType: 'html_page',
    sourceApp: 'web' as SourceApp,
    sourceUrl: url,
    timestamp: new Date().toISOString(),
    title: document.title || url,
    pageContent: opts.pageContent,
    artifactKind: 'structured_dom',
    artifactPayload: {
      tables: opts.tables,
      cards: opts.cards,
      charts: opts.charts,
    },
    artifactCompleteness: 'complete',
  };
}

/**
 * Builds a CaptureCandidate from a parsed GitHub PR diff payload.
 * Renders the full patch as assistantText so the backend can FTS-index it.
 */
export async function buildGithubDiffCandidate(
  diff: GithubDiffPayload,
): Promise<CaptureCandidate> {
  const url = window.location.href;
  const fingerprint = `${diff.owner}/${diff.repo}#${diff.pr_number}@${diff.head_sha ?? ''}`;
  const customId = await sha256(fingerprint);
  return {
    customId,
    eventType: 'github_pr_diff',
    sourceApp: 'web' as SourceApp,
    sourceUrl: url,
    timestamp: new Date().toISOString(),
    title: document.title || fingerprint,
    userText: '',
    assistantText: diff.rendered_patch,
  };
}

/**
 * Debounced MutationObserver that fires `onStable` once DOM stops changing.
 * Returns a cleanup function.
 */
export function observeWithStability(
  root: Element | Document,
  onStable: () => void,
  stabilityMs = 500,
): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null;

  const observer = new MutationObserver(() => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(onStable, stabilityMs);
  });

  observer.observe(root, {
    childList: true,
    subtree: true,
    characterData: true,
  });

  return () => {
    if (timer) clearTimeout(timer);
    observer.disconnect();
  };
}


// ── Phase 2: Bulk Capture ─────────────────────────────────────────────────

/**
 * Builds a CaptureCandidate from an array of conversation turn pairs.
 *
 * Used by the scroll-pump and API interceptor to assemble a full
 * retroactive capture. The customId is a stable SHA-256 of
 * `shail_session_${conversationId}` so active and retroactive capture update
 * the same memory for the same conversation instead of creating duplicates.
 *
 * Retroactive capture remains an ai_conversation update. Phase 3 bulk imports
 * still use bulk_history.
 */
export async function buildBulkCapture(opts: {
  sourceApp: SourceApp;
  conversationId: string;
  conversationIdTemporary?: boolean;
  previousConversationId?: string;
  turns: Array<{ user: string; assistant: string }>;
  captureMode: 'retroactive' | 'bulk';
  captureSource?: 'api' | 'dom_scroll';
  title?: string;
}): Promise<CaptureCandidate> {
  const url = window.location.href;
  const customId = await sha256('shail_session_' + opts.conversationId);

  // Build the full transcript in the same format as extractTranscript()
  const fullTranscript = opts.turns
    .map(t => `User: ${t.user}\n\nAssistant: ${t.assistant}`)
    .join('\n\n---\n\n');

  // Use the last turn's user text as the title fallback
  const userText = opts.turns.length > 0
    ? opts.turns[opts.turns.length - 1].user
    : '';

  return {
    customId,
    conversationId: opts.conversationId,
    conversationIdTemporary: opts.conversationIdTemporary,
    previousConversationId: opts.previousConversationId,
    eventType: opts.captureMode === 'retroactive' ? 'ai_conversation' : 'bulk_history',
    sourceApp: opts.sourceApp,
    sourceUrl: url,
    timestamp: new Date().toISOString(),
    title: opts.title || document.title || `${opts.sourceApp} conversation`,
    userText,
    assistantText: fullTranscript,
    turnCount: opts.turns.length,
    captureMode: opts.captureMode,
    captureSource: opts.captureSource,
    captureInitiator: 'manual',
  };
}
