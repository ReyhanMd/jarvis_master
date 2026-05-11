// ─── Capture ────────────────────────────────────────────────────────────────

export type EventType =
  | 'ai_conversation'
  | 'page_visit'
  | 'manual'
  | 'audio_clip'
  | 'video_clip'
  | 'pdf_doc'
  | 'mindmap'
  | 'diagram'
  | 'html_page'
  | 'document';

export type SourceApp =
  | 'chatgpt'
  | 'claude'
  | 'gemini'
  | 'perplexity'
  | 'web';

// ─── Structured payloads (v2 envelopes) ─────────────────────────────────────

export interface GithubHunkLine {
  kind: '+' | '-' | ' ';
  text: string;
}

export interface GithubHunk {
  header: string;
  lines: GithubHunkLine[];
}

export interface GithubFile {
  path: string;
  status?: string;
  hunks: GithubHunk[];
  patch_text?: string;
  summary?: string;
}

export interface GithubDiffPayload {
  repo: string;
  owner: string;
  pr_number: number;
  base_sha?: string;
  head_sha?: string;
  files: GithubFile[];
  rendered_patch: string;
}

export interface HtmlTablePayload {
  title?: string;
  columns: string[];
  rows: (string | number)[][];
  column_types?: string[];
  units?: string;
  source_locator?: string;
  header_depth?: number;
}

export interface DashboardCardPayload {
  section_title?: string;
  card_title?: string;
  primary_value?: string;
  value_num?: number | null;
  unit?: string;
  delta_value?: string;
  delta_unit?: string;
  time_window?: string;
  subtitle?: string;
  source_locator?: string;
}

export interface ChartSeries {
  name?: string;
  values?: (number | string)[];
}

export interface SvgChartPayload {
  title?: string;
  subtitle?: string;
  chart_type?: string;
  time_window?: string;
  x_axis?: string;
  y_axis?: string;
  series?: ChartSeries[];
  legend?: string[];
  source_locator?: string;
  capture_confidence?: 'complete' | 'partial';
}

export interface CaptureCandidate {
  /** SHA-256 fingerprint — stable per conversation when conversationId is present */
  customId: string;
  /** Provider conversation UUID extracted from the URL (Sprint 1+) */
  conversationId?: string;
  eventType: EventType;
  sourceApp: SourceApp;
  sourceUrl: string;
  timestamp: string; // ISO 8601
  title?: string;
  userText?: string;      // the user's prompt (ai_conversation only)
  assistantText?: string; // the AI's response (ai_conversation only)
  pageContent?: string;   // trimmed page text (page_visit only)
  /** Canonical thread ID from the provider's URL (e.g. ChatGPT /c/<uuid>).
   *  When present, the backend upserts to the same memory record for every
   *  turn in the conversation instead of creating a new record per snapshot. */
  conversationId?: string;
  artifactKind?: string;
  artifactMimeType?: string;
  artifactPayload?: Record<string, unknown>;
  artifactBase64?: string;
  artifactCompleteness?: 'complete' | 'partial' | 'stub' | 'legacy_partial';
  captureHints?: Record<string, unknown>;
  selectorVersion?: string;
}

// ─── Memory ─────────────────────────────────────────────────────────────────

export type MemoryStateLabel =
  | 'captured' | 'partial' | 'queued' | 'replayable'
  | 'active' | 'historical' | 'failed' | 'synced'
  | 'local-only' | 'trusted' | 'incomplete';

export interface MemoryRecord {
  id: string;
  customId: string;
  eventType: EventType;
  sourceApp: SourceApp;
  sourceUrl: string;
  title: string;
  summary: string;
  timestamp: string;
  tags?: string[];
  pinned?: boolean;
  /** Relevance score from Supermemory's hybrid search (0–1). Higher = more relevant. */
  score?: number;
  // v2 manifesto — additive, may be undefined for legacy records.
  confidence?: number;
  state?: MemoryStateLabel;
  fidelity?: number | null;
  version?: number;
  parentId?: string | null;
}

// ─── Search / Context ────────────────────────────────────────────────────────

export interface SearchFilters {
  sourceApp?: SourceApp;
  dateFrom?: string;
  dateTo?: string;
}

export interface SearchRequest {
  query: string;
  filters?: SearchFilters;
  scope?: 'all' | 'current_site';
  after?: string;  // ISO 8601 — only return memories with timestamp >= after
}

export interface ContextBundle {
  query: string;
  answer: string;
  items: MemoryRecord[];
  injectionText: string; // formatted block prefixed with "--- Prior context ---"
}

// ─── Guidance / Ghost Cursor ─────────────────────────────────────────────────

export interface DomCandidate {
  selector: string;
  label: string;
  rect: { x: number; y: number; width: number; height: number };
}

export interface GuidanceStep {
  order: number;
  instruction: string;
  why: string;
  target: {
    selector: string;
    fallbackBox: [number, number, number, number]; // x1, y1, x2, y2
    label: string;
  };
  confidence: number;
}

export interface GuidancePlan {
  steps: GuidanceStep[];
  audioRecommended: boolean;
}

export interface GuidanceRequest {
  query: string;
  domCandidates: DomCandidate[];
  screenshotRef: string; // base64
  currentUrl: string;
  appType: SourceApp | 'unknown';
  memoryContext?: string;
}

// ─── Site Policies ───────────────────────────────────────────────────────────

export type PolicyType = 'ALLOW' | 'SUMMARY_ONLY' | 'DENY';

export interface SitePolicy {
  domain: string;
  policy: PolicyType;
}

// ─── User / Auth ─────────────────────────────────────────────────────────────

export interface UserProfile {
  user_id: string;
  email:   string;
  name:    string;
}

// ─── API responses ────────────────────────────────────────────────────────────

export interface CaptureResult {
  memoryId: string;
  status: 'created' | 'queued' | 'duplicate' | 'denied';
  summary?: string;
}

export interface StatsResult {
  memoriesThisWeek: number;
  topSource: SourceApp | null;
  lastCaptured: MemoryRecord | null;
  recentCaptures: MemoryRecord[];
}

// ─── Background messages ─────────────────────────────────────────────────────

export type BackgroundMessage =
  | { type: 'CAPTURE'; payload: CaptureCandidate }
  | { type: 'SEARCH'; payload: SearchRequest }
  | { type: 'OPEN_SIDEPANEL' }
  | { type: 'GET_POLICIES' }
  | { type: 'FETCH_ASCENT'; payload: { id: string } }
  | { type: 'TOGGLE_TODO'; payload: { ascentId: string; todoId: string; completed: boolean } }
  | { type: 'SYNC_PAUSE_BADGE'; payload: { enabled: boolean } };

export type BackgroundResponse =
  | { ok: true; data: unknown }
  | { ok: false; error: string };
