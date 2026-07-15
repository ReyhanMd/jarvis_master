const BASE = 'http://localhost:8000';
const BASE_FALLBACK = 'http://127.0.0.1:8000';
const REQUEST_TIMEOUT_MS = 6000;

function authHeaders(): Record<string, string> {
  const key = localStorage.getItem('shail_api_key');
  return key ? { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
}

function parseBackendError(path: string, error: unknown): Error {
  const msg = error instanceof Error ? error.message : String(error);
  if (msg === 'NOT_SIGNED_IN') return new Error('NOT_SIGNED_IN');
  if (msg === 'BACKEND_TIMEOUT') return new Error(`Backend timeout while calling ${path}`);
  if (msg === 'BACKEND_OFFLINE') return new Error(`Backend offline while calling ${path}`);
  if (msg.includes('404') || msg.includes('Not Found')) return new Error(`Backend route not loaded for ${path}. Restart SHAIL backend.`);
  if (msg.includes('Failed to fetch') || msg.includes('Load failed')) return new Error(`Backend offline while calling ${path}`);
  return new Error(msg);
}

async function fetchJson<T>(base: string, path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${base}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { ...authHeaders(), ...(init.headers as Record<string, string> ?? {}) },
    });
    if (res.status === 401) throw new Error('NOT_SIGNED_IN');
    if (!res.ok) {
      const t = await res.text().catch(() => '');
      throw new Error(t || `${res.status}`);
    }
    if (res.status === 204) return undefined as T;
    return res.json();
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw new Error('BACKEND_TIMEOUT');
    const msg = error instanceof Error ? error.message : String(error);
    if (/failed to fetch|networkerror|load failed/i.test(msg)) throw new Error('BACKEND_OFFLINE');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await fetchJson<T>(BASE, path, init);
  } catch (first) {
    const msg = first instanceof Error ? first.message : String(first);
    if (!['BACKEND_OFFLINE', 'BACKEND_TIMEOUT'].includes(msg)) {
      throw parseBackendError(path, first);
    }
    try {
      return await fetchJson<T>(BASE_FALLBACK, path, init);
    } catch (second) {
      throw parseBackendError(path, second);
    }
  }
}

function isNotFoundError(error: unknown) {
  const msg = error instanceof Error ? error.message : String(error);
  return msg.includes('404') || msg.includes('Not Found');
}

async function localRagReq<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await req<T>(`/local-rag${path}`, init);
  } catch (error) {
    if (!isNotFoundError(error)) throw error;
    return req<T>(`/api/v2/local-rag${path}`, init);
  }
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
  systemReadiness: () => req<SystemReadiness>('/system/readiness'),
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
  localGraphBuild: (limit = 1000) =>
    localRagReq<{ status: string; source_count: number; node_count: number; edge_count: number }>(
      `/graph/build?limit=${limit}`,
      { method: 'POST' },
    ),
  localGraph: (limit = 1000) =>
    localRagReq<LocalGraphResponse>(`/graph?limit=${limit}`),
  localGraphSearch: (q: string, limit = 25) =>
    localRagReq<LocalGraphResponse>(`/graph/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  localGraphNeighbors: (nodeId: string, limit = 50) =>
    localRagReq<LocalGraphResponse>(`/graph/neighbors/${encodeURIComponent(nodeId)}?limit=${limit}`),
  localEvidence: (query: string, k = 8, includeGraph = true) =>
    localRagReq<LocalEvidenceResponse>('/evidence', {
      method: 'POST',
      body: JSON.stringify({ query, k, include_graph: includeGraph }),
    }),
  localAnswer: (query: string, k = 8, includeGraph = true) =>
    localRagReq<LocalAnswerResponse>('/answer', {
      method: 'POST',
      body: JSON.stringify({ query, k, include_graph: includeGraph }),
    }),
  localIntelligencePacket: (body: LocalIntelligencePacketRequest) =>
    localRagReq<LocalIntelligencePacketResponse>('/intelligence/packet', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  localIntelligenceStatus: () =>
    localRagReq<LocalIntelligenceStatusResponse>('/intelligence/status'),
  localIntelligenceFactsSearch: (q = '', limit = 50) =>
    localRagReq<LocalIntelligenceFactsSearchResponse>(`/intelligence/facts/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  localIntelligencePacketGet: (packetId: string) =>
    localRagReq<LocalIntelligencePacketResponse>(`/intelligence/packet/${encodeURIComponent(packetId)}`),
  localSemanticsBuild: (limit = 500, force = false, mode = 'deterministic', model?: string) => {
    const params = new URLSearchParams({ limit: String(limit), force: String(force), mode });
    if (model) params.set('model', model);
    return localRagReq<LocalSemanticsBuildResponse>(`/semantics/build?${params.toString()}`, { method: 'POST' });
  },
  localSemanticsJobCreate: (body: LocalSemanticsJobRequest) =>
    localRagReq<LocalSemanticsJobResponse>('/semantics/jobs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  localSemanticsJob: (jobId: string) =>
    localRagReq<LocalSemanticsJobResponse>(`/semantics/jobs/${encodeURIComponent(jobId)}`),
  cancelLocalSemanticsJob: (jobId: string) =>
    localRagReq<LocalSemanticsJobResponse>(`/semantics/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }),
  localSemanticsStatus: () =>
    localRagReq<LocalSemanticsStatusResponse>('/semantics/status'),
  localSemanticsSearch: (q = '', limit = 50) =>
    localRagReq<LocalSemanticsSearchResponse>(`/semantics/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  localSemanticsFile: (fileId: string) =>
    localRagReq<LocalSemanticsSearchResponse>(`/semantics/file/${encodeURIComponent(fileId)}`),
  localReasoningBuild: (body: LocalReasoningBuildRequest) =>
    localRagReq<LocalReasoningBuildResponse>('/semantics/reasoning/build', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  localReasoningStatus: () =>
    localRagReq<LocalReasoningStatusResponse>('/semantics/reasoning/status'),
  localReasoningSearch: (q = '', limit = 50) =>
    localRagReq<LocalReasoningSearchResponse>(`/semantics/reasoning/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  localReasoningConflicts: (limit = 50) =>
    localRagReq<LocalReasoningConflictsResponse>(`/semantics/reasoning/conflicts?limit=${limit}`),
  localReasoningGroup: (groupId: string) =>
    localRagReq<LocalReasoningGroup>(`/semantics/reasoning/group/${encodeURIComponent(groupId)}`),

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
  graph_reason?: string | null;
  evidence_reason?: string | null;
  confidence?: string | null;
  is_latest_candidate?: boolean;
  duplicate_of?: string | null;
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
  | {
      type: 'local_file';
      id: string;
      title: string;
      path: string;
      snippet?: string;
      file_type?: string;
      score?: number;
      graph_reason?: string | null;
      evidence_reason?: string | null;
      confidence?: string | null;
      is_latest_candidate?: boolean;
      duplicate_of?: string | null;
    };

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

export interface LocalGraphNode {
  id: string;
  type: string;
  title?: string | null;
  label?: string | null;
  uri?: string | null;
  path?: string | null;
  source_path?: string | null;
  privacy_state?: 'allowed' | 'blocked' | 'redacted' | string;
  metadata?: Record<string, unknown>;
  source_app?: string | null;
  state?: string | null;
}

export interface LocalGraphRelation {
  source_id: string;
  target_id: string;
  relation: string;
  weight: number;
  evidence?: string | null;
  confidence?: string;
  source_path?: string | null;
}

export interface LocalGraphResponse {
  nodes: LocalGraphNode[];
  relations: LocalGraphRelation[];
}

export interface LocalEvidenceItem {
  id: string;
  title: string;
  path: string;
  snippet: string;
  file_type: string;
  score: number;
  reason: string;
  graph_relation?: string | null;
  graph_evidence?: string | null;
  evidence_source: string;
  confidence: string;
  is_latest_candidate: boolean;
  is_duplicate_candidate: boolean;
  duplicate_of?: string | null;
  content_hash?: string | null;
  mtime?: number | null;
  size_bytes?: number | null;
  extractor_used?: string | null;
}

export interface LocalEvidenceResponse {
  evidence_bundle_id: string;
  query: string;
  direct_matches: LocalEvidenceItem[];
  graph_expansions: LocalEvidenceItem[];
  selected_files: LocalEvidenceItem[];
  suppressed_files: LocalEvidenceItem[];
  warnings: string[];
  confidence: string;
  prompt_context: string;
  citations: Array<Record<string, unknown>>;
  semantic_facts: LocalSemanticFact[];
  semantic_tasks: LocalSemanticTask[];
  semantic_entities: LocalSemanticEntity[];
  semantic_warnings: string[];
  semantic_resolutions?: LocalReasoningGroup[];
  semantic_conflicts?: LocalReasoningGroup[];
  reasoning_warnings?: string[];
}

export interface LocalAnswerResponse {
  answer: string;
  confidence: string;
  evidence_bundle_id: string;
  query: string;
  citations: Array<Record<string, unknown>>;
  evidence_summary: Array<Record<string, unknown>>;
  warnings: string[];
  follow_up_questions: string[];
  unresolved_conflicts: LocalReasoningGroup[];
  semantic_resolutions: LocalReasoningGroup[];
  semantic_conflicts: LocalReasoningGroup[];
  quality_score: number;
  quality_signals: Record<string, unknown>;
  prompt_context: string;
}

export interface LocalIntelligencePacketRequest {
  query: string;
  scope?: string | null;
  k: number;
  include_graph: boolean;
  include_semantics?: boolean;
  include_reasoning?: boolean;
  include_answer: boolean;
}

export interface LocalCanonicalFact {
  fact_id: string;
  entity?: string | null;
  attribute?: string | null;
  value?: string | number | null;
  period?: string | null;
  confidence: string;
  status: string;
  preferred_claim?: Record<string, unknown> | null;
  competing_claims: Array<Record<string, unknown>>;
  source_files: Array<Record<string, unknown>>;
  why_this_is_preferred?: string | null;
  warnings: string[];
}

export interface LocalIntelligencePacketResponse {
  packet_id: string;
  query: string;
  answer: string;
  confidence: string;
  canonical_facts: LocalCanonicalFact[];
  supporting_evidence: Array<Record<string, unknown>>;
  conflicts: Array<Record<string, unknown>>;
  gaps: Array<Record<string, unknown>>;
  follow_up_questions: string[];
  recommended_next_actions: string[];
  timeline: Array<Record<string, unknown>>;
  source_map: Array<Record<string, unknown>>;
  warnings: string[];
  evidence_bundle_id: string;
  created_at: number;
  metadata: Record<string, unknown>;
}

export interface LocalIntelligenceStatusResponse {
  packets: number;
  latest_packet_at?: number | null;
  confidence: Record<string, number>;
  llm_synthesis_enabled: boolean;
  model: string;
}

export interface LocalIntelligenceFactsSearchResponse {
  query: string;
  items: LocalCanonicalFact[];
  total: number;
  status: LocalIntelligenceStatusResponse;
}

export interface LocalSemanticEntity {
  id: string;
  file_id: string;
  path: string;
  entity_type: string;
  label: string;
  source_span?: string | null;
  confidence: string;
  metadata?: Record<string, unknown>;
}

export interface LocalSemanticFact {
  id: string;
  file_id: string;
  path: string;
  entity?: string | null;
  attribute?: string | null;
  value?: string | null;
  value_num?: number | null;
  unit?: string | null;
  period?: string | null;
  source_span?: string | null;
  confidence: string;
  metadata?: Record<string, unknown>;
}

export interface LocalSemanticTask {
  id: string;
  file_id: string;
  path: string;
  text: string;
  status?: string | null;
  due_date?: string | null;
  source_span?: string | null;
  confidence: string;
  metadata?: Record<string, unknown>;
}

export interface LocalSemanticsBuildResponse {
  status: string;
  files_seen: number;
  processed: number;
  skipped: number;
  failed: number;
  entities: number;
  facts: number;
  tasks: number;
  metrics: number;
  mode?: string;
  job_id?: string | null;
  queued?: boolean;
}

export interface LocalSemanticsStatusResponse {
  files: Record<string, number>;
  entities: Record<string, number>;
  facts: number;
  tasks: number;
  last_extracted_at?: number | null;
  latest_llm_enriched_at?: number | null;
  extractor_version: string;
  queue?: LocalSemanticsQueueStatus;
}

export interface LocalSemanticsQueueStatus {
  pending: number;
  running: number;
  failed: number;
  done: number;
  cancelled: number;
  latest_llm_enriched_at?: number | null;
  active_model?: string;
  llm_enabled?: boolean;
  active_job?: LocalSemanticsJobResponse | null;
}

export interface LocalSemanticsJobRequest {
  mode: 'deterministic' | 'llm' | 'hybrid';
  limit: number;
  force: boolean;
  model?: string;
}

export interface LocalSemanticsJobResponse {
  job_id: string;
  status: string;
  mode?: string | null;
  model?: string | null;
  limit?: number | null;
  force: boolean;
  files_seen: number;
  files_processed: number;
  files_skipped: number;
  files_failed: number;
  chunks_processed: number;
  entities: number;
  facts: number;
  tasks: number;
  warnings: string[];
  last_error?: string | null;
}

export interface LocalSemanticsSearchResponse {
  file?: Record<string, unknown> | null;
  entities: LocalSemanticEntity[];
  facts: LocalSemanticFact[];
  tasks: LocalSemanticTask[];
}

export interface LocalReasoningBuildRequest {
  limit: number;
  force: boolean;
}

export interface LocalReasoningBuildResponse {
  status: string;
  groups: number;
  claims: number;
  conflicts: number;
  resolved: number;
  unresolved: number;
}

export interface LocalReasoningStatusResponse {
  groups: number;
  claims: number;
  conflicts: number;
  resolved: number;
  unresolved: number;
  last_built_at?: number | null;
}

export interface LocalReasoningClaim {
  claim_id: string;
  group_id: string;
  fact_id: string;
  file_id: string;
  path: string;
  entity?: string | null;
  attribute?: string | null;
  value?: string | null;
  value_num?: number | null;
  unit?: string | null;
  period?: string | null;
  value_norm: string;
  confidence: string;
  extractor: string;
  source_span?: string | null;
  content_hash?: string | null;
  file_mtime?: number | null;
  is_latest_candidate: boolean;
  is_duplicate_candidate: boolean;
  support_count: number;
  score: number;
  reason?: string | null;
  metadata?: Record<string, unknown>;
}

export interface LocalReasoningGroup {
  group_id: string;
  label: string;
  entity_norm: string;
  attribute_norm: string;
  period_norm: string;
  unit_norm: string;
  value_type: string;
  claim_count: number;
  distinct_value_count: number;
  status: string;
  preferred_claim_id?: string | null;
  preferred_claim?: LocalReasoningClaim | null;
  competing_claims: LocalReasoningClaim[];
  confidence: string;
  reason?: string | null;
  warnings: string[];
  updated_at: number;
}

export interface LocalReasoningSearchResponse extends LocalReasoningStatusResponse {
  items: LocalReasoningGroup[];
}

export interface LocalReasoningConflictsResponse extends LocalReasoningStatusResponse {
  items: LocalReasoningGroup[];
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

export interface GraphApiMemory {
  id: string;
  memory: string;
  content?: string | null;
  isStatic: boolean;
  spaceId: string;
  isLatest: boolean;
  isForgotten: boolean;
  forgetAfter?: string | null;
  forgetReason?: string | null;
  version: number;
  parentMemoryId?: string | null;
  rootMemoryId?: string | null;
  createdAt: string;
  updatedAt: string;
  relation?: Record<string, string> | null;
  updatesMemoryId?: string | null;
  nextVersionId?: string | null;
  memoryRelations?: Record<string, string> | null;
  spaceContainerTag?: string | null;
}

export interface GraphApiDocument {
  id: string;
  title?: string | null;
  summary?: string | null;
  documentType: string;
  createdAt: string;
  updatedAt: string;
  memories: GraphApiMemory[];
}

export interface MemoryGraph {
  documents: GraphApiDocument[];
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

export interface SystemReadiness {
  status: 'ready' | 'degraded' | string;
  backend_online: boolean;
  services: Record<string, Record<string, unknown>>;
  checks: Record<string, { ok: boolean; error?: string; missing?: string[]; [key: string]: unknown }>;
  python: {
    executable: string;
    version: string;
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
