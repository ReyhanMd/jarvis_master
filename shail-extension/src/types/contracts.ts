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
  | 'document'
  | 'github_pr_diff'
  | 'bulk_history';

export type SourceApp =
  | 'chatgpt'
  | 'claude'
  | 'gemini'
  | 'perplexity'
  | 'grok'
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
  /** True when SHAIL generated a temporary chat ID before the provider URL had a stable ID. */
  conversationIdTemporary?: boolean;
  /** Temporary chat ID to merge into this capture once the provider stable ID appears. */
  previousConversationId?: string;
  eventType: EventType;
  sourceApp: SourceApp;
  sourceUrl: string;
  timestamp: string; // ISO 8601
  title?: string;
  userText?: string;      // the user's prompt (ai_conversation only)
  assistantText?: string; // the AI's response (ai_conversation only)
  pageContent?: string;   // trimmed page text (page_visit only)
  artifactKind?: string;
  artifactMimeType?: string;
  artifactPayload?: Record<string, unknown>;
  artifactBase64?: string;
  artifactCompleteness?: 'complete' | 'partial' | 'stub' | 'legacy_partial';
  captureHints?: Record<string, unknown>;
  selectorVersion?: string;
  /** Phase 2: number of conversation turns in this capture */
  turnCount?: number;
  /** Phase 2: how this capture was produced */
  captureMode?: 'active' | 'retroactive' | 'bulk';
  /** Phase 2: whether retroactive capture came from API interception or DOM scroll fallback. */
  captureSource?: 'api' | 'dom_scroll';
  /** Explicit user actions bypass automatic-capture pause, but not blocked-domain policy. */
  captureInitiator?: 'auto' | 'manual';
  /** Typed extraction preserving code, tables, math, images, and tool output. */
  segments?: CaptureSegment[];
}

export interface CaptureSegment {
  kind: 'text' | 'markdown' | 'code' | 'table' | 'mermaid' | 'math' | 'html' | 'json' | 'image_ref' | 'tool_call' | 'tool_result';
  content: string;
  language?: string;
  role?: 'user' | 'assistant' | 'tool';
  metadata?: Record<string, unknown>;
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
  memoryId?: string;
  status: 'saved' | 'created' | 'queued' | 'duplicate' | 'denied' | 'offline_queued' | 'error';
  summary?: string;
  reason?: string;
}

export interface CaptureSurfaceState {
  memory_id?: string;
  conversation_id?: string;
  source_app: SourceApp;
  source_url: string;
  title: string;
  capture_mode: 'active' | 'retroactive' | 'bulk';
  capture_source?: 'api' | 'dom_scroll';
  capture_policy: 'capturing' | 'paused' | 'excluded' | 'ended';
  retention_policy: 'keep_raw' | 'blueprint_only' | 'decide_later' | 'transcript_deleted';
  pipeline: {
    current_stage?: string;
    current_state?: string;
    stages: Record<string, unknown>;
  };
  blueprint: {
    present: boolean;
    job_state?: 'pending' | 'running' | 'done' | 'failed';
    last_error?: string | null;
  };
  raw_transcript?: {
    content_chars?: number;
    segment_count?: number;
    embedded?: boolean;
    blueprinted?: boolean;
    transcript_deleted_at?: string | null;
  };
  updated_at: string;
}

export interface StatsResult {
  totalLocalMemories: number;
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
  | { type: 'SYNC_PAUSE_BADGE'; payload: { enabled: boolean } }
  | { type: 'START_BULK_CYCLE'; payload: { sourceApp: SourceApp; urls: string[] } }
  | { type: 'DELETE_TRANSCRIPT_KEEP_BLUEPRINT'; payload: { memoryId: string; policy: 'keep_raw' | 'blueprint_only' | 'decide_later' } }
  | { type: 'CACHE_EVICTION'; payload: { keys?: string[]; action?: string; id?: string } };

export type BackgroundResponse =
  | { ok: true; data: unknown }
  | { ok: false; error: string };
