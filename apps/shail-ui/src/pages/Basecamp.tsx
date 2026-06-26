import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, AscentSummary, CaptureEvent, MemoryRecord, RouteCluster, SOURCE_LABEL, SOURCE_COLOR } from '../api';
import { AltitudeChart } from '../components/AltitudeChart';
import { NewAscentModal } from '../components/NewAscentModal';

// ── Sub-components ──────────────────────────────────────────────────────────

const CARD = {
  background: '#0d0d0d',
  border: '1px solid #161616',
  borderRadius: 9,
} as const;

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

function StatCard({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div style={{ ...CARD, padding: '16px 18px' }}>
      <div style={{ fontSize: 10, letterSpacing: '0.1em', color: '#555', fontFamily: MONO }}>
        {label}
      </div>
      <div style={{ marginTop: 8, fontSize: 28, fontWeight: 500, color: '#fff', lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ marginTop: 6, fontSize: 11, color: '#555', fontFamily: MONO }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function timeAgo(ts: string): string {
  if (!ts) return '—';
  const t = new Date(ts).getTime();
  if (Number.isNaN(t)) return '—';
  const d = (Date.now() - t) / 1000;
  if (d < 60) return `${Math.floor(d)}s`;
  if (d < 3600) return `${Math.floor(d / 60)}m`;
  if (d < 86400) return `${Math.floor(d / 3600)}h`;
  return `${Math.floor(d / 86400)}d`;
}

function ActiveAscentPanel({ ascent, onOpen }: { ascent: AscentSummary | null; onOpen: () => void }) {
  if (!ascent) {
    return (
      <div style={{ ...CARD, padding: 18 }}>
        <div style={{ fontSize: 10, letterSpacing: '0.1em', color: '#555', fontFamily: MONO }}>ACTIVE ASCENT</div>
        <div style={{ marginTop: 14, fontSize: 13, color: '#666', lineHeight: 1.55 }}>
          No active ascents yet.
        </div>
        <button
          onClick={onOpen}
          style={{
            marginTop: 14, padding: '8px 14px', fontSize: 12, background: '#fff',
            color: '#000', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 500,
          }}
        >
          + New ascent
        </button>
      </div>
    );
  }

  const pct = Math.round(ascent.progress * 100);
  // 5 nodes: 0=BASE, 2=RIDGE, 4=SUMMIT; positions at 0,1,2,3,4
  const NODES = 5;
  const stages = ['BASE', 'RIDGE', 'SUMMIT'];
  // Current position as continuous float (0–4) based on progress
  const progressPos = ascent.progress * (NODES - 1); // 0.0 – 4.0
  const activeNodeIdx = Math.floor(progressPos);

  // Derive NEXT STEP from available ascent metadata
  const completedTodos = ascent.todos_completed;
  const totalTodos = ascent.todo_count;
  const remaining = totalTodos - completedTodos;
  const nextStepText = remaining > 0
    ? `Complete next ${Math.min(3, remaining)} task${remaining > 1 ? 's' : ''} in "${ascent.name.split(' ').slice(0, 4).join(' ')}" — ${remaining} remaining.`
    : `All todos complete — review deliverables and mark ascent done.`;

  return (
    <div style={{ ...CARD, padding: 18 }}>
      <div style={{ fontSize: 10, letterSpacing: '0.1em', color: '#555', fontFamily: MONO }}>ACTIVE ASCENT</div>
      <div style={{ marginTop: 12, fontSize: 16, fontWeight: 500, color: '#fff', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {ascent.name}
      </div>
      <div style={{ marginTop: 4, fontSize: 11, color: '#666', lineHeight: 1.45 }}>
        {ascent.deliverable_count} deliverables · {ascent.todos_completed}/{ascent.todo_count} todos · {timeAgo(ascent.created_at)} old
      </div>

      {/* ── Stage track with connecting line ── */}
      <div style={{ marginTop: 18, position: 'relative', height: 20 }}>

        {/* Full background track */}
        <div style={{
          position: 'absolute', left: 8, right: 8, top: 8,
          height: 1, background: '#1a1a1a',
        }} />

        {/* Completed segment — white line from left up to current position */}
        {pct > 0 && (
          <div style={{
            position: 'absolute',
            left: 8,
            top: 8,
            height: 1,
            width: `calc(${(progressPos / (NODES - 1)) * 100}% - 16px)`,
            background: 'linear-gradient(90deg, #fff 0%, #888 100%)',
            transition: 'width 0.5s ease',
          }} />
        )}

        {/* Nodes */}
        {Array.from({ length: NODES }, (_, i) => {
          const isCompleted = i < activeNodeIdx;
          const isCurrent = i === activeNodeIdx && pct > 0;
          const isUpcoming = i > activeNodeIdx || pct === 0;

          return (
            <div key={i} style={{
              position: 'absolute',
              left: `calc(${(i / (NODES - 1)) * 100}% - 5px)`,
              top: 3,
              width: 10, height: 10,
              borderRadius: 5,
              background: isCompleted ? '#fff' : isCurrent ? '#22c55e' : '#1a1a1a',
              border: isCompleted
                ? '2px solid #fff'
                : isCurrent
                  ? '2px solid #22c55e'
                  : '2px solid #2a2a2a',
              // Pulse ring on active node
              boxShadow: isCurrent ? '0 0 0 3px rgba(34,197,94,0.2)' : 'none',
              zIndex: 2,
              transition: 'all 0.3s ease',
            }} />
          );
        })}
      </div>

      {/* Stage labels */}
      <div style={{ marginTop: 6, display: 'flex', justifyContent: 'space-between', fontSize: 9, color: '#444', letterSpacing: '0.1em', fontFamily: MONO }}>
        {stages.map(s => <span key={s}>{s}</span>)}
      </div>

      {/* Progress percent */}
      <div style={{ marginTop: 10, fontSize: 11, color: '#888', fontFamily: MONO }}>
        {pct}% complete
      </div>

      {/* ── NEXT STEP card ── */}
      <div style={{
        marginTop: 14,
        padding: '10px 12px',
        background: '#111',
        border: '1px solid #1f1f1f',
        borderRadius: 7,
      }}>
        <div style={{
          fontSize: 9, letterSpacing: '0.12em', color: '#f59e0b',
          fontFamily: MONO, fontWeight: 700, marginBottom: 6,
        }}>
          NEXT STEP
        </div>
        <div style={{ fontSize: 12, color: '#ccc', lineHeight: 1.55 }}>
          {nextStepText}
        </div>
      </div>
    </div>
  );
}


function CaptureLogPanel({ events, refreshing, onRefresh }: { events: CaptureEvent[]; refreshing: boolean; onRefresh: () => void }) {
  const colorFor = (t: string) => ({
    CAPTURE: '#fff', INDEX: '#888', LINK: '#a78bfa', RECALL: '#22c55e', PRUNE: '#ef4444',
  } as Record<string, string>)[t] || '#666';

  return (
    <div style={{ ...CARD, padding: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontSize: 13, color: '#fff', fontWeight: 500 }}>Capture log</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 9, color: '#22c55e',
            letterSpacing: '0.1em', fontFamily: MONO,
          }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#22c55e' }} />
            LIVE
          </span>
          <button
            onClick={onRefresh}
            disabled={refreshing}
            style={{
              background: 'none', border: '1px solid #1f1f1f', borderRadius: 5,
              padding: '3px 8px', fontSize: 10, color: '#666', cursor: refreshing ? 'wait' : 'pointer',
              fontFamily: MONO, opacity: refreshing ? 0.5 : 1,
            }}
            title="Refresh"
          >↻</button>
        </div>
      </div>

      <div style={{ maxHeight: 240, overflowY: 'auto', fontFamily: MONO, fontSize: 10, lineHeight: 1.85 }}>
        {events.length === 0 && (
          <div style={{ color: '#333', fontStyle: 'italic' }}>(no events yet — capture a memory or create an ascent)</div>
        )}
        {events.map((e, i) => {
          const t = new Date(e.ts);
          const hh = t.toTimeString().slice(0, 8);
          return (
            <div key={i} style={{ display: 'flex', gap: 10, color: '#666' }}>
              <span style={{ color: '#3a3a3a' }}>{hh}</span>
              <span style={{ color: colorFor(e.event_type), width: 56, flexShrink: 0 }}>{e.event_type}</span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {e.description}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SourcesBreakdown({ items }: { items: MemoryRecord[] }) {
  const counts: Record<string, number> = {};
  for (const m of items) counts[m.sourceApp] = (counts[m.sourceApp] || 0) + 1;
  const total = items.length;
  const order = ['web', 'chatgpt', 'claude', 'gemini', 'perplexity'];
  const rows = order.filter(k => counts[k]).map(k => ({ k, c: counts[k] }));

  return (
    <div style={{ ...CARD, padding: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontSize: 13, color: '#fff', fontWeight: 500 }}>
          Sources <span style={{ color: '#444', fontWeight: 400 }}>· last 30 days</span>
        </div>
        <span style={{ fontSize: 11, color: '#666', fontFamily: MONO }}>{total} total</span>
      </div>
      {rows.length === 0 && (
        <div style={{ fontSize: 11, color: '#3a3a3a' }}>No memories yet.</div>
      )}
      {rows.map(({ k, c }) => {
        const pct = (c / total) * 100;
        const color = SOURCE_COLOR[k] || '#888';
        return (
          <div key={k} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#aaa', marginBottom: 4 }}>
              <span>{SOURCE_LABEL[k] || k}</span>
              <span style={{ fontFamily: MONO, color: '#666' }}>{c}</span>
            </div>
            <div style={{ height: 4, background: '#161616', borderRadius: 2 }}>
              <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2, transition: 'width 0.3s' }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface SystemHealth {
  ok: boolean;
  ollamaReachable: boolean;
  chromaReady: boolean;
  embedderReady: boolean;
  responseMs: number;
  model: string;
  embedding: string;
  captureMode: 'on' | 'off' | 'unknown';
}

function SystemStatusPanel({ health }: { health: SystemHealth | null }) {
  const Row = ({ k, v, dot }: { k: string; v: React.ReactNode; dot?: 'green' | 'red' }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', fontSize: 11, fontFamily: MONO }}>
      <span style={{ color: '#666' }}>{k}</span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#aaa' }}>
        {dot === 'green' && <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#22c55e' }} />}
        {dot === 'red'   && <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#ef4444' }} />}
        {v}
      </span>
    </div>
  );

  if (!health) {
    return (
      <div style={{ ...CARD, padding: 18 }}>
        <div style={{ fontSize: 13, color: '#fff', fontWeight: 500, marginBottom: 8 }}>System</div>
        <div style={{ fontSize: 11, color: '#3a3a3a' }}>Checking…</div>
      </div>
    );
  }

  return (
    <div style={{ ...CARD, padding: 18 }}>
      <div style={{ fontSize: 13, color: '#fff', fontWeight: 500, marginBottom: 8 }}>System</div>
      <Row k="Backend"      v="localhost:8000"   dot={health.ok ? 'green' : 'red'} />
      <Row k="Vector store" v="chroma"           dot={health.chromaReady ? 'green' : 'red'} />
      <Row k="Embedding"    v={health.embedding} dot={health.embedderReady ? 'green' : 'red'} />
      <Row k="Local model"  v={health.model}     dot={health.ollamaReachable ? 'green' : 'red'} />
      <Row k="Latency"      v={`${health.responseMs}ms`} />
      <Row k="Capture"      v={health.captureMode} />
      <Row k="Storage"      v="local-first" />
    </div>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────

export function Basecamp() {
  const navigate = useNavigate();
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [ascents, setAscents] = useState<AscentSummary[]>([]);
  const [activeAscent, setActiveAscent] = useState<AscentSummary | null>(null);
  const [events, setEvents] = useState<CaptureEvent[]>([]);
  const [routes, setRoutes] = useState<RouteCluster[]>([]);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [refreshingLog, setRefreshingLog] = useState(false);
  const [quickAsk, setQuickAsk] = useState('');

  const fetchAll = async () => {
    try {
      const [memResp, ascResp, evtResp, routesResp] = await Promise.all([
        api.search({ query: '', k: 100 }).catch(() => ({ items: [] as MemoryRecord[], total: 0 })),
        api.listAscents().catch(() => ({ items: [] as AscentSummary[], active_count: 0, limit: 5, tier: 'free' as const })),
        api.captureLog(50).catch(() => ({ events: [] as CaptureEvent[], count: 0 })),
        api.routes().catch(() => ({ routes: [] as RouteCluster[], total_clusters: 0 })),
      ]);
      setMemories(memResp.items || []);
      setAscents(ascResp.items || []);
      setActiveAscent((ascResp.items || []).find(a => a.status === 'active') || null);
      setEvents(evtResp.events || []);
      setRoutes(routesResp.routes || []);
    } catch { /* swallow — components handle empty states */ }
  };

  const fetchHealth = async () => {
    const t0 = performance.now();
    try {
      const r = await fetch('http://localhost:8000/health');
      const ms = Math.round(performance.now() - t0);
      const d = await r.json();
      let captureMode: SystemHealth['captureMode'] = 'unknown';
      try {
        const cs = await api.getSettings();
        captureMode = cs.capture_enabled ? 'on' : 'off';
      } catch { /* anonymous fallback */ }
      setHealth({
        ok: d.status === 'ok',
        ollamaReachable: !!d.ollama_reachable,
        chromaReady: !!d.chroma_ready,
        embedderReady: !!d.embedder_ready,
        responseMs: ms,
        model: 'gemma3',
        embedding: 'nomic-embed',
        captureMode,
      });
    } catch {
      setHealth({ ok: false, ollamaReachable: false, chromaReady: false, embedderReady: false,
        responseMs: 0, model: 'unknown', embedding: 'unknown', captureMode: 'unknown' });
    }
  };

  useEffect(() => { fetchAll(); fetchHealth(); }, []);

  const totalMemories = memories.length;
  const memoriesThisWeek = useMemo(() => {
    const wk = new Date(); wk.setDate(wk.getDate() - 7);
    return memories.filter(m => new Date(m.timestamp) >= wk).length;
  }, [memories]);

  const lastCaptured = memories[0];

  const sourceCounts: Record<string, number> = {};
  for (const m of memories) sourceCounts[m.sourceApp] = (sourceCounts[m.sourceApp] || 0) + 1;
  const topSourceEntry = Object.entries(sourceCounts).sort((a, b) => b[1] - a[1])[0];
  const topSource = topSourceEntry ? topSourceEntry[0] : null;
  const topPct = topSourceEntry && totalMemories ? Math.round((topSourceEntry[1] / totalMemories) * 100) : 0;

  const activeAscents = ascents.filter(a => a.status === 'active');

  const refreshLog = async () => {
    setRefreshingLog(true);
    try {
      const r = await api.captureLog(50);
      setEvents(r.events);
    } catch { /* */ }
    setRefreshingLog(false);
  };

  const onAsk = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && quickAsk.trim()) {
      navigate(`/chat?q=${encodeURIComponent(quickAsk.trim())}`);
    }
  };

  // Today date label
  const today = new Date();
  const dateStr = today.toLocaleDateString(undefined, { month: 'long', day: 'numeric' });

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '32px 40px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <div style={{ fontSize: 11, color: '#666', letterSpacing: '0.1em', fontFamily: MONO }}>BASECAMP</div>
          <h1 style={{ margin: '6px 0 0', fontSize: 26, fontWeight: 500, color: '#fff', letterSpacing: '-0.4px' }}>
            Today, {dateStr}
          </h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <input
            value={quickAsk}
            onChange={e => setQuickAsk(e.target.value)}
            onKeyDown={onAsk}
            placeholder="◌ Ask SHAIL anything…"
            style={{
              width: 280,
              padding: '8px 14px',
              fontSize: 12,
              background: '#0a0a0a',
              border: '1px solid #1a1a1a',
              borderRadius: 7,
              color: '#aaa',
              outline: 'none',
            }}
          />
          <button
            onClick={() => setShowNew(true)}
            style={{
              padding: '8px 16px', fontSize: 12, background: '#fff', color: '#000',
              border: 'none', borderRadius: 7, fontWeight: 500, cursor: 'pointer',
            }}
          >
            New ascent
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 14, marginBottom: 18 }}>
        <StatCard
          label="MEMORIES"
          value={totalMemories}
          sub={`this week +${memoriesThisWeek}`}
        />
        <StatCard
          label="ACTIVE ASCENTS"
          value={activeAscents.length}
          sub={activeAscents.slice(0, 3).map(a => a.name.split(/\s+/)[0]).join(', ').toUpperCase() || '—'}
        />
        <StatCard
          label="TOP SOURCE"
          value={topSource ? (SOURCE_LABEL[topSource] || topSource) : '—'}
          sub={topSource ? `${topPct}% of captures` : 'no data yet'}
        />
        <StatCard
          label="LAST CAPTURED"
          value={lastCaptured ? timeAgo(lastCaptured.timestamp) : '—'}
          sub={lastCaptured ? lastCaptured.title.slice(0, 32) : '—'}
        />
      </div>

      {/* Two-column grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.55fr) minmax(0, 1fr)', gap: 14 }}>
        {/* LEFT */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <AltitudeChart daysBack={7} />

          {/* Recent captures */}
          <div style={{ ...CARD, padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div style={{ fontSize: 13, color: '#fff', fontWeight: 500 }}>Recent captures</div>
              <span style={{ fontSize: 10, color: '#666', fontFamily: MONO, letterSpacing: '0.08em' }}>
                {memoriesThisWeek} NEW
              </span>
            </div>
            {memories.slice(0, 8).map(m => (
              <div key={m.id} style={{
                display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0',
                borderBottom: '1px solid #111', fontSize: 12,
              }}>
                <span style={{
                  width: 60, fontSize: 9, color: SOURCE_COLOR[m.sourceApp] || '#666',
                  letterSpacing: '0.08em', fontFamily: MONO, flexShrink: 0,
                }}>
                  {(SOURCE_LABEL[m.sourceApp] || m.sourceApp).toUpperCase()}
                </span>
                <span style={{
                  flex: 1, color: '#ccc', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {m.title || m.sourceUrl}
                </span>
                <span style={{ fontSize: 10, color: '#3a3a3a', fontFamily: MONO, flexShrink: 0 }}>
                  {timeAgo(m.timestamp)}
                </span>
              </div>
            ))}
            {memories.length === 0 && (
              <div style={{ fontSize: 12, color: '#3a3a3a', padding: '14px 0' }}>No captures yet.</div>
            )}
          </div>

          {/* Sources breakdown */}
          <SourcesBreakdown items={memories} />
        </div>

        {/* RIGHT */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <ActiveAscentPanel ascent={activeAscent} onOpen={() => setShowNew(true)} />
          <CaptureLogPanel events={events} refreshing={refreshingLog} onRefresh={refreshLog} />
          <SystemStatusPanel health={health} />

          {/* Top routes preview */}
          {routes.length > 0 && (
            <div style={{ ...CARD, padding: 18 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div style={{ fontSize: 13, color: '#fff', fontWeight: 500 }}>Routes</div>
                <button
                  onClick={() => navigate('/routes')}
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer', color: '#666',
                    fontSize: 11, fontFamily: MONO,
                  }}
                >
                  See all →
                </button>
              </div>
              {routes.slice(0, 5).map(r => (
                <div key={r.label} style={{
                  display: 'flex', justifyContent: 'space-between', padding: '6px 0', fontSize: 12, color: '#ccc',
                }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.label}
                  </span>
                  <span style={{ color: '#666', fontFamily: MONO, fontSize: 10 }}>
                    {r.count}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {showNew && (
        <NewAscentModal
          onClose={() => setShowNew(false)}
          onCreated={(a) => { fetchAll(); navigate(`/ascents`); }}
        />
      )}
    </div>
  );
}
