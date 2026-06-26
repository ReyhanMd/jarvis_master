const BASE = 'http://localhost:8000';

function authHeaders(): Record<string, string> {
  const key = localStorage.getItem('shail_api_key');
  return key ? { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { ...init, headers: { ...authHeaders(), ...(init.headers as Record<string, string> ?? {}) } });
  if (res.status === 401) throw new Error('NOT_SIGNED_IN');
  if (!res.ok) { const t = await res.text().catch(() => ''); throw new Error(t || `${res.status}`); }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  // Auth
  me: () => req<{ user_id: string; email: string; name: string }>('/auth/me'),
  googleStartUrl: (state: string) => `${BASE}/auth/google/start?state=${encodeURIComponent(state)}`,
  pollGoogleToken: async (state: string): Promise<{ email: string; name: string; api_key: string; user_id: string } | null> => {
    const res = await fetch(`${BASE}/auth/google/token?state=${encodeURIComponent(state)}`);
    if (res.status === 204) return null;
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
  },

  // Memories
  search: (body: Record<string, unknown>) =>
    req<{ items: MemoryRecord[]; total: number }>('/browser/search', { method: 'POST', body: JSON.stringify(body) }),
  deleteMemory: (id: string) =>
    req<{ ok: boolean }>(`/browser/memories/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getMemory: (id: string) =>
    req<MemoryRecord & { content?: string }>(`/browser/memories/${encodeURIComponent(id)}`),
  getRelatedMemories: (id: string, limit = 10) =>
    req<MemoryRecord[]>(`/api/v2/memories/${encodeURIComponent(id)}/related?limit=${limit}`),
  memoryGraph: () =>
    req<MemoryGraph>('/api/v2/graph'),
  getBlueprint: (id: string) =>
    req<Blueprint>(`/browser/blueprint/${encodeURIComponent(id)}`),
  getBlueprintIds: (ids: string[]) =>
    req<{ ids: string[] }>('/browser/blueprint-ids', { method: 'POST', body: JSON.stringify({ ids }) }),
  getArtifacts: (id: string) =>
    req<{ items: CaptureArtifact[] }>(`/browser/memories/${encodeURIComponent(id)}/artifacts`),
  getMaterializations: (id: string) =>
    req<{ items: MemoryMaterialization[] }>(`/browser/memories/${encodeURIComponent(id)}/materializations`),
  getCaptureHealth: (id: string) =>
    req<CaptureHealth>(`/browser/memories/${encodeURIComponent(id)}/capture-health`),
  createReplayJob: (body: ReplayJobRequest) =>
    req<ReplayJobSummary>('/browser/replay/jobs', { method: 'POST', body: JSON.stringify(body) }),
  getReplayJob: (id: string) =>
    req<ReplayJobDetail>(`/browser/replay/jobs/${id}`),

  // Stats
  stats: () => req<{ totalMemories: number; memoriesThisWeek: number; topSource: string | null; lastCapturedAt: string | null }>('/browser/stats'),
  altitude: (days = 7) =>
    req<AltitudeResponse>(`/browser/altitude?days=${days}`),

  // Settings
  getSettings: () => req<CaptureSettings>('/browser/capture-settings'),
  putSettings: (body: Partial<CaptureSettings>) =>
    req<CaptureSettings>('/browser/capture-settings', { method: 'PUT', body: JSON.stringify(body) }),

  // Export
  exportUrl: () => `${BASE}/browser/export`,
  import: (items: MemoryRecord[]) =>
    req<{ imported: number; skipped: number }>('/browser/import', { method: 'POST', body: JSON.stringify(items) }),

  // System / Services
  systemStatus: () => req<SystemStatus>('/system/status'),
  systemStop: () => req<{ stopped: string[]; note: string }>('/system/stop', { method: 'POST' }),
  systemStartUrl: () => `${BASE}/system/start`,
  systemRestartUrl: (service: string) => `${BASE}/system/restart/${service}`,
  ollamaModels: () => req<{ status: string; binary_path: string | null; models: { name: string; size: number; modified_at: string }[]; has_gemma: boolean; install_url: string }>('/system/ollama-models'),

  // Ascents
  listAscents: () => req<AscentListResponse>('/browser/ascents'),
  getAscent: (id: string) => req<AscentDetail>(`/browser/ascents/${id}`),
  createAscent: (body: { name: string; description?: string }) =>
    req<AscentDetail>('/browser/ascents', { method: 'POST', body: JSON.stringify(body) }),
  toggleTodo: (ascentId: string, todoId: string, completed: boolean) =>
    req<AscentDetail>(`/browser/ascents/${ascentId}/todos/${todoId}`, {
      method: 'PUT', body: JSON.stringify({ completed }),
    }),
  deleteAscent: (id: string) =>
    req<{ ok: boolean }>(`/browser/ascents/${id}`, { method: 'DELETE' }),

  // Chat — streaming uses fetch directly with auth headers; this exposes the URL.
  chatUrl: () => `${BASE}/browser/chat`,
  chatNonStream: (message: string, session_id?: string) =>
    req<ChatResponse>('/browser/chat', {
      method: 'POST', body: JSON.stringify({ message, session_id, stream: false }),
    }),

  // Chat sessions
  listChatSessions: () => req<{ items: ChatSessionSummary[] }>('/browser/chat/sessions'),
  createChatSession: () => req<ChatSessionSummary>('/browser/chat/sessions', { method: 'POST' }),
  getChatSession: (id: string) => req<ChatSessionDetail>(`/browser/chat/sessions/${id}`),
  patchChatSession: (
    id: string,
    body: {
      title?: string;
      pinned?: boolean;
      capture_enabled?: boolean;
      retention_policy?: 'keep_raw' | 'blueprint_only' | 'transcript_deleted';
    },
  ) =>
    req<ChatSessionSummary>(`/browser/chat/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteChatSession: (id: string) =>
    req<{ ok: boolean }>(`/browser/chat/sessions/${id}`, { method: 'DELETE' }),

  // Phase C — session backfill, timeline, blueprint, redact
  // Sprint 2: defaults to async (returns job_id immediately). Pass
  // synchronous=true for legacy blocking call used by small-session paths.
  backfillSession: (id: string, opts: { includeBlueprint?: boolean; synchronous?: boolean } = {}) =>
    req<
      | {
          // Synchronous (legacy) response shape
          session_id: string;
          turns_seen: number;
          turns_indexed: number;
          turns_skipped: number;
          blueprint_generated: boolean;
          blueprint_memory_id: string | null;
          raw_transcript_chars: number;
          errors: string[];
          duration_ms: number;
          degraded_mode?: boolean;
          degraded_reason?: string | null;
          fts_fallback_used?: boolean;
        }
      | {
          // Async (default) response shape
          session_id: string;
          job_id: string;
          state: string;
          accepted: boolean;
        }
    >(`/browser/chat/sessions/${id}/backfill`, {
      method: 'POST',
      body: JSON.stringify({
        include_blueprint: opts.includeBlueprint ?? true,
        synchronous: opts.synchronous ?? false,
      }),
    }),
  // Sprint 2: poll backfill progress
  getBackfillStatus: (id: string) =>
    req<{
      session_id: string;
      state: 'idle' | 'running' | 'done' | 'failed' | 'degraded';
      cursor: number;
      total_messages: number;
      progress_pct: number;
      remaining: number;
      job_id: string | null;
      error: string | null;
      backfilled_at: string | null;
    }>(`/browser/chat/sessions/${id}/backfill/status`),
  // Sprint 1: capture-pipeline health probe
  getSessionHealth: (id: string) =>
    req<{
      session_id: string;
      ollama_up: boolean;
      embedder_error: string | null;
      fts_available: boolean;
      fts_indexed: number;
      vector_indexed: number;
      degraded_mode: boolean;
    }>(`/browser/chat/sessions/${id}/health`),
  // Sprint 4: import external chat export. `file` is a File from <input type=file>.
  // We bypass the JSON `req` helper because FormData needs the browser-set
  // multipart boundary in Content-Type — req's authHeaders() forces JSON.
  importChats: async (
    file: File,
    source: 'chatgpt' | 'claude' | 'cursor',
    autoBackfill = true,
  ) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('source', source);
    fd.append('auto_backfill', String(autoBackfill));
    const key = localStorage.getItem('shail_api_key');
    const headers: Record<string, string> = key ? { Authorization: `Bearer ${key}` } : {};
    const res = await fetch(`${BASE}/browser/chat/import`, {
      method: 'POST', body: fd, headers,
    });
    if (res.status === 401) throw new Error('NOT_SIGNED_IN');
    if (!res.ok) { const t = await res.text().catch(() => ''); throw new Error(t || `${res.status}`); }
    return res.json() as Promise<{
      source: string;
      conversations_seen: number;
      sessions_created: number;
      messages_inserted: number;
      session_ids: string[];
      errors: string[];
    }>;
  },
  getSessionTimeline: (id: string) =>
    req<{
      session: {
        id: string;
        title: string;
        created_at: string;
        updated_at: string;
        pinned: boolean;
        retention_policy: string;
        capture_enabled: boolean;
        blueprint_memory_id: string | null;
        backfilled_at: string | null;
      };
      turns: Array<{ user_msg: any; asst_msg: any }>;
      blueprint: any | null;
      retention: { policy: string; raw_available: boolean };
    }>(`/browser/chat/sessions/${id}/timeline`),
  getSessionBlueprint: (id: string) =>
    req<any>(`/browser/chat/sessions/${id}/blueprint`),
  redactSession: (id: string) =>
    req<{ ok: boolean; messages_deleted: number; blueprint_kept: string }>(
      `/browser/chat/sessions/${id}/redact`,
      { method: 'POST' },
    ),

  // MCP connectors
  listMcpProviders: () => req<{ items: McpProvider[] }>('/mcp/providers'),
  startMcpAuth: (provider: string) => req<{ authorize_url: string }>(`/mcp/${provider}/auth/start`),
  disconnectMcp: (provider: string) =>
    req<{ ok: boolean }>(`/mcp/connections/${provider}`, { method: 'DELETE' }),
  mcpIndexStatus: (provider: string) =>
    req<{ indexed_count: number; status: string; error: string | null; last_synced: string | null }>(`/mcp/${provider}/index/status`),
  reindexMcp: (provider: string) =>
    req<{ ok: boolean; status: string }>(`/mcp/${provider}/index/run`, { method: 'POST' }),
  getMcpSettings: (provider: string) =>
    req<{ settings: Record<string, unknown> }>(`/mcp/${provider}/settings`),
  putMcpSettings: (provider: string, settings: Record<string, unknown>) =>
    req<{ settings: Record<string, unknown> }>(`/mcp/${provider}/settings`, {
      method: 'PUT', body: JSON.stringify({ settings }),
    }),
  gmailLabels: () => req<{ labels: { id: string; name: string; type: string }[] }>('/mcp/gmail/labels'),

  // LLM settings
  llmSettings: () => req<LLMSettings>('/browser/llm-settings'),
  putLLMSettings: (body: Partial<LLMSettingsUpdate>) =>
    req<LLMSettings>('/browser/llm-settings', { method: 'PUT', body: JSON.stringify(body) }),
  testLLM: (body: { provider: string; api_key?: string; model?: string }) =>
    req<{ ok: boolean; info: string }>('/browser/llm-settings/test', {
      method: 'POST', body: JSON.stringify(body),
    }),

  // Local file path-index (Graphify map)
  pathIndexStats: () =>
    req<{ total: number; total_files: number; total_dirs: number; by_type: Record<string, number>; by_kind: Record<string, number>; embedded: number; last_indexed_at: number | null }>(
      '/path-index/stats',
    ),
  pathIndexTree: (root?: string, depth = 2, maxNodes = 500) => {
    const params = new URLSearchParams();
    if (root) params.set('root', root);
    params.set('depth', String(depth));
    params.set('max_nodes', String(maxNodes));
    return req<{ root: string | null; nodes: PathTreeNode[]; edges: { source: string; target: string }[]; truncated: boolean }>(
      `/path-index/tree?${params.toString()}`,
    );
  },
  pathIndexSync: () =>
    req<{ status: string }>('/path-index/sync', { method: 'POST' }),
  pathIndexEmbed: (path: string) =>
    req<{ path: string; chunks_ingested: number; embedded: boolean; user_id: string }>(
      `/path-index/embed?path=${encodeURIComponent(path)}`,
      { method: 'POST' },
    ),
  pathIndexOpen: (path: string) =>
    req<{ ok: boolean; path: string }>(
      `/path-index/open?path=${encodeURIComponent(path)}`,
      { method: 'POST' },
    ),
  pathIndexSearch: (q: string, limit = 20) =>
    req<{ items: { id: string; path: string; file_type: string; size_bytes: number | null; mtime: number | null; title: string | null; indexed_at: number }[]; total: number }>(
      `/path-index/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),

  // Local files: explicit ingest + filesystem watcher
  ingestLocalFiles: (paths: string[], maxFiles = 500) =>
    req<{ ingested: number; skipped: number; files_seen: number; errors: string[] }>(
      '/browser/chat/files/ingest',
      { method: 'POST', body: JSON.stringify({ paths, max_files: maxFiles }) },
    ),
  startFolderWatch: (path: string) =>
    req<{ ok: boolean; path?: string; status?: string; error?: string }>(
      '/browser/chat/files/watch',
      { method: 'POST', body: JSON.stringify({ path }) },
    ),
  stopFolderWatch: (path: string) =>
    req<{ ok: boolean; path?: string; status?: string }>(
      `/browser/chat/files/watch?path=${encodeURIComponent(path)}`,
      { method: 'DELETE' },
    ),
  listFolderWatches: () =>
    req<{ watches: { user_id: string; path: string; created_at: string; last_event_at: string | null; event_count: number }[] }>(
      '/browser/chat/files/watch',
    ),

  // Capture log
  captureLog: (limit = 100) =>
    req<{ events: CaptureEvent[]; count: number }>(`/browser/capture-log?limit=${limit}`),

  // Routes & Horizon
  routes: () => req<{ routes: RouteCluster[]; total_clusters: number }>('/browser/routes'),
  horizon: () => req<{ items: HorizonItem[]; total_candidates: number }>('/browser/horizon'),

  // Test retrieval for a connected source
  testRetrieval: (sourceApp: string) =>
    api.search({ query: 'test', filters: { sourceApp }, k: 3 }),

  // Anonymous memory sync
  anonymousCount: () => req<{ count: number }>('/browser/anonymous-count'),
  listAnonymousMemories: () =>
    req<{ items: { id: string; title: string; sourceApp: string; timestamp: string }[]; total: number }>('/browser/anonymous-memories'),
  claimAnonymous: (ids?: string[]) =>
    req<{ claimed: number }>('/browser/claim-anonymous', {
      method: 'POST',
      body: JSON.stringify({ ids: ids ?? null }),
    }),
};

// ── Ascents types ──────────────────────────────────────────────────────────
export interface TodoItem {
  id: string;
  text: string;
  order_index: number;
  completed: boolean;
  completed_at: string | null;
}

export interface DeliverableItem {
  id: string;
  text: string;
  description: string;
  order_index: number;
  completed: boolean;
  todos: TodoItem[];
  memory_ids: string[];
}

export interface AscentSummary {
  id: string;
  name: string;
  description: string;
  status: 'active' | 'completed' | 'abandoned';
  created_at: string;
  updated_at: string;
  deliverable_count: number;
  todo_count: number;
  todos_completed: number;
  progress: number;   // 0..1
}

export interface AscentDetail extends AscentSummary {
  deliverables: DeliverableItem[];
}

export interface AscentListResponse {
  items: AscentSummary[];
  active_count: number;
  limit: number;
  tier: 'free' | 'pro';
}

// ── Chat types ─────────────────────────────────────────────────────────────
export interface ChatMemoryCitation { id: string; title: string; score: number; }
export interface ChatWebSource { title: string; url: string; snippet: string; }
export interface ChatLocalFileCitation {
  id: string;
  title: string;
  path: string;
  snippet: string;
  file_type: string;
  score: number;
}
export interface ChatPastChatCitation {
  message_id: string;
  session_id: string;
  session_title: string;
  snippet: string;
  score: number;
}
export interface ChatResponse {
  answer: string;
  session_id: string;
  message_id: string;
  provider: string;
  model: string;
  fellback: boolean;
  memories: ChatMemoryCitation[];
  past_chats: ChatPastChatCitation[];
  web_sources: ChatWebSource[];
  local_files?: ChatLocalFileCitation[];
  used_web: boolean;
}

/** Citation as stored in chat_messages.citations JSON column. */
export type StoredCitation =
  | { type: 'memory'; id: string; title: string; score: number }
  | { type: 'chat'; id: string; session_id: string; title: string; snippet: string; score: number }
  | { type: 'web'; id: string; title: string; url: string; snippet: string }
  | { type: 'mcp'; id: string; provider: string; title: string; snippet?: string; url?: string }
  | { type: 'local_file'; id: string; title: string; path: string; snippet?: string; file_type?: string; score?: number };

export interface PathTreeNode {
  id: string;          // absolute path
  name: string;
  is_dir: boolean;
  kind: string | null; // 'code'|'doc'|'data'|'media'|'log'|'other'
  size: number | null;
  mtime: number | null;
  child_count: number;
  embedded: boolean;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  pinned: boolean;
  message_count?: number;
  preview?: string;
}

export interface StoredChatMessage {
  id: string;
  session_id: string;
  user_id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: StoredCitation[];
  provider?: string | null;
  model?: string | null;
  created_at: string;
}

export interface ChatSessionDetail extends ChatSessionSummary {
  messages: StoredChatMessage[];
}

// ── MCP types ──────────────────────────────────────────────────────────────
export interface McpProvider {
  name: 'drive' | 'github' | 'notion' | 'gmail';
  label: string;
  scopes: string[];
  configured: boolean;     // server has OAuth client credentials in env
  connected: boolean;      // user has connected this provider
  metadata: Record<string, string>;   // email / login / workspace_name etc.
  indexed_count: number;
  index_status: 'idle' | 'indexing' | 'error';
  index_error: string | null;
  last_synced: string | null;
}

// ── LLM settings ───────────────────────────────────────────────────────────
export interface LLMSettings {
  active_provider: 'ollama' | 'openai' | 'anthropic';
  active_model: string;
  openai_configured: boolean;
  anthropic_configured: boolean;
}
export interface LLMSettingsUpdate {
  active_provider: 'ollama' | 'openai' | 'anthropic';
  active_model: string;
  openai_api_key: string;
  anthropic_api_key: string;
}

// ── Capture events ─────────────────────────────────────────────────────────
export interface CaptureEvent {
  ts: string;
  event_type: 'CAPTURE' | 'INDEX' | 'LINK' | 'RECALL' | 'PRUNE';
  description: string;
  ref_id: string;
}

// ── Routes / Horizon ──────────────────────────────────────────────────────
export interface RouteCluster {
  label: string;
  axis: 'tag' | 'source';
  count: number;
  latest_ts: string;
  sample_titles: string[];
}
export interface HorizonItem {
  label: string;
  axis: 'tag' | 'source';
  memory_count: number;
  latest_ts: string;
  sample_titles: string[];
  suggested_name: string;
  suggested_description: string;
}

export type MemoryStateLabel =
  | 'captured' | 'partial' | 'queued' | 'replayable'
  | 'active' | 'historical' | 'failed' | 'synced'
  | 'local-only' | 'trusted' | 'incomplete';

export interface MemoryRecord {
  id: string;
  customId: string;
  eventType: string;
  sourceApp: string;
  sourceUrl: string;
  title: string;
  summary: string;
  timestamp: string;
  tags: string[];
  pinned: boolean;
  score?: number;
  content?: string;
  // v2 manifesto fields (additive — server defaults to safe values for legacy records)
  confidence?: number;
  state?: MemoryStateLabel;
  parentId?: string | null;
  version?: number;
  fidelity?: number | null;
}

export interface MemoryGraphNode {
  id: string;
  label: string;
  type: string;
  sourceApp: string;
  timestamp: string;
  importance: number;
}

export interface MemoryGraphEdge {
  source: string;
  target: string;
}

export interface MemoryGraph {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
}

export interface Blueprint {
  memory_id: string;
  version: number;
  content_type: string;
  created_at: string;
  artifact_id?: string | null;
  materialization_id?: string | null;
  extractor_bundle_version?: string | null;
  updated_at?: string | null;
  summary: string;
  decisions: Array<string | { statement: string; reasoning?: string | null; confidence?: string }>;
  questions_answered: { q: string; a: string }[];
  open_questions: string[];
  next_actions: string[];
  key_entities: string[];
  reasoning_chains?: { conclusion: string; steps: string[]; evidence: string[] }[];
  failed_attempts?: { approach: string; failure: string; lesson: string }[];
  facts?: Record<string, unknown>[];
  metrics?: Record<string, unknown>[];
  tables?: Record<string, unknown>[];
  extensions?: Record<string, unknown>;
}

export interface CaptureArtifact {
  artifact_id: string;
  artifact_seq: number;
  artifact_kind: string;
  completeness: string;
  captured_at: string;
  created_at: string;
  byte_size: number;
  event_type: string;
  source_app: string;
  source_url: string;
  metadata: Record<string, unknown>;
}

export interface MemoryMaterialization {
  materialization_id: string;
  memory_id: string;
  artifact_id: string;
  extractor_bundle_version: string;
  content_type: string;
  status: string;
  is_active: boolean;
  validation: Record<string, unknown>;
  created_at: string;
  promoted_at?: string | null;
}

export interface CaptureHealth {
  memory_id: string;
  artifact_count: number;
  materialization_count: number;
  completeness: string;
  has_active_materialization: boolean;
  latest_artifact_kind?: string | null;
  latest_bundle_version?: string | null;
}

export interface AltitudePoint {
  date: string;
  bytes: number;
  captures: number;
  deletes?: number;
}

export interface AltitudeResponse {
  points: AltitudePoint[];
  totalBytes: number;
  totalCaptures: number;
  weekOverWeekPct: number;
}

export interface ReplayJobRequest {
  mode?: 'shadow' | 'promote';
  artifactId?: string;
  memoryId?: string;
  artifactKind?: string;
}

export interface ReplayJobSummary {
  replay_job_id: string;
  status: string;
}

export interface ReplayJobItem {
  replay_job_item_id: string;
  replay_job_id: string;
  artifact_id: string;
  memory_id: string;
  status: string;
  materialization_id?: string | null;
  validation: Record<string, unknown>;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReplayJobDetail extends ReplayJobSummary {
  mode: string;
  scope_type: string;
  scope_ref: string;
  bundle_version: string;
  validation: Record<string, unknown>;
  prior_active_materialization_id?: string | null;
  promoted_materialization_id?: string | null;
  created_at: string;
  updated_at: string;
  items: ReplayJobItem[];
}

export interface ServiceInfo {
  status: 'running' | 'stopped' | 'not_installed' | 'starting' | 'error' | 'unknown';
  port: number | null;
  pid: number | null;
  managed_owner?: string | null;
}

export interface SystemStatus {
  services: Record<string, ServiceInfo>;
  tier: 'free' | 'pro';
  blueprint_queue?: {
    pending: number;
    running: number;
    done?: number;
    failed?: number;
  };
}

export interface CaptureSettings {
  capture_enabled: boolean;
  blocked_domains: string[];
  ollama_model: string;
  external_api_key: string;
}

export const SOURCE_COLOR: Record<string, string> = {
  chatgpt: '#10a37f',
  claude:  '#cc785c',
  gemini:  '#4285f4',
  perplexity: '#20b2aa',
  web:     '#6b7280',
};

export const SOURCE_LABEL: Record<string, string> = {
  chatgpt: 'ChatGPT',
  claude:  'Claude',
  gemini:  'Gemini',
  perplexity: 'Perplexity',
  web:     'Web',
};
