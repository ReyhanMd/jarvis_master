import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ReplayJobDetail, AscentDetail, HorizonItem } from '../api';
import { flag } from '../lib/featureFlags';
import { EmptyState } from '../components/primitives';

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const CARD = { background: '#0d0d0d', border: '1px solid #161616', borderRadius: 9 } as const;

// ── Replay Timeline (ui_v2) ──────────────────────────────────────────────────

type ReplayJobSummaryItem = {
  replay_job_id: string;
  status: string;
  mode: string;
  created_at: string;
  updated_at: string;
  scope_type: string;
  scope_ref: string;
  bundle_version: string;
};

function statusColor(status: string) {
  if (status === 'completed' || status === 'promoted') return '#22c55e';
  if (status === 'failed') return '#ef4444';
  if (status === 'running') return '#fbbf24';
  return '#555';
}

function statusDot(status: string) {
  return (
    <span style={{
      display: 'inline-block', width: 7, height: 7, borderRadius: '50%',
      background: statusColor(status), flexShrink: 0,
      boxShadow: status === 'running' ? `0 0 6px ${statusColor(status)}88` : undefined,
    }} />
  );
}

function ReplayTimeline() {
  const [jobs, setJobs] = useState<ReplayJobSummaryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, ReplayJobDetail>>({});
  const navigate = useNavigate();

  useEffect(() => {
    // Backend returns individual job detail; we don't have a list endpoint yet.
    // Use recent replay job ids from localStorage if available, otherwise show empty.
    const stored = localStorage.getItem('shail_replay_jobs');
    const ids: string[] = stored ? JSON.parse(stored) : [];
    if (ids.length === 0) { setLoading(false); return; }
    Promise.allSettled(ids.map(id => api.getReplayJob(id)))
      .then(results => {
        const loaded: ReplayJobSummaryItem[] = [];
        results.forEach((r, i) => {
          if (r.status === 'fulfilled') {
            const j = r.value;
            loaded.push({
              replay_job_id: j.replay_job_id,
              status: j.status,
              mode: j.mode,
              created_at: j.created_at,
              updated_at: j.updated_at,
              scope_type: j.scope_type,
              scope_ref: j.scope_ref,
              bundle_version: j.bundle_version,
            });
          }
        });
        loaded.sort((a, b) => b.created_at.localeCompare(a.created_at));
        setJobs(loaded);
      })
      .finally(() => setLoading(false));
  }, []);

  async function toggleExpand(id: string) {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    if (!detail[id]) {
      try {
        const d = await api.getReplayJob(id);
        setDetail(prev => ({ ...prev, [id]: d }));
      } catch { /* */ }
    }
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '32px 40px' }}>
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: 11, color: '#666', letterSpacing: '0.1em', fontFamily: MONO }}>HORIZON</div>
        <h1 style={{ margin: '6px 0 0', fontSize: 26, fontWeight: 500, color: '#fff' }}>Replay Timeline</h1>
        <p style={{ margin: '6px 0 0', fontSize: 12, color: '#666', maxWidth: 600, lineHeight: 1.5 }}>
          History of re-extraction jobs. Each replay runs the current extraction pipeline against a stored raw artifact —
          letting you see how improvements affect older captures.
        </p>
      </div>

      {loading && <div style={{ color: '#3a3a3a', fontSize: 12 }}>Loading…</div>}

      {!loading && jobs.length === 0 && (
        <EmptyState
          title="No replay jobs yet"
          hint="Open a memory in the inspector and click 'Replay now' to run the current extraction pipeline against its raw artifact."
          action={{ label: 'Browse memories', onClick: () => navigate('/memories') }}
        />
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxWidth: 720, position: 'relative' }}>
        {/* Timeline spine */}
        {jobs.length > 0 && (
          <div style={{ position: 'absolute', left: 10, top: 12, bottom: 12, width: 1, background: '#161616' }} />
        )}

        {jobs.map(j => (
          <div key={j.replay_job_id} style={{ paddingLeft: 32, position: 'relative' }}>
            {/* Timeline dot */}
            <div style={{ position: 'absolute', left: 6, top: 16 }}>{statusDot(j.status)}</div>

            <div style={{ ...CARD, padding: '14px 18px', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span style={{
                      fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', fontFamily: MONO,
                      color: statusColor(j.status),
                    }}>
                      {j.status.toUpperCase()}
                    </span>
                    <span style={{ fontSize: 10, color: '#555', fontFamily: MONO }}>{j.mode}</span>
                    <span style={{ fontSize: 10, color: '#3a3a3a', fontFamily: MONO }}>v{j.bundle_version}</span>
                  </div>
                  <div style={{ fontSize: 12, color: '#aaa', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {j.scope_type} · {j.scope_ref}
                  </div>
                  <div style={{ fontSize: 10, color: '#555', marginTop: 3, fontFamily: MONO }}>
                    {new Date(j.created_at).toLocaleString()}
                  </div>
                </div>
                <button
                  onClick={() => toggleExpand(j.replay_job_id)}
                  style={{ background: 'transparent', border: '1px solid #1f1f1f', borderRadius: 5, padding: '4px 10px', fontSize: 10, color: '#666', cursor: 'pointer', flexShrink: 0 }}
                >
                  {expanded === j.replay_job_id ? 'Hide' : 'Details'}
                </button>
              </div>

              {expanded === j.replay_job_id && detail[j.replay_job_id] && (
                <div style={{ marginTop: 12, borderTop: '1px solid #131313', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {detail[j.replay_job_id].items.map(item => (
                    <div key={item.replay_job_item_id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
                      {statusDot(item.status)}
                      <span style={{ color: '#666', fontFamily: MONO, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.artifact_id.slice(0, 8)}…
                      </span>
                      <span style={{ color: statusColor(item.status), fontFamily: MONO }}>{item.status}</span>
                      {item.error && <span style={{ color: '#ef9a9a', fontSize: 10 }}>{item.error}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Classic Horizon (legacy, ui_v1) ──────────────────────────────────────────

interface ConfirmStartProps {
  item: HorizonItem;
  onCancel: () => void;
  onConfirm: (a: AscentDetail) => void;
}

function ConfirmStart({ item, onCancel, onConfirm }: ConfirmStartProps) {
  const [name, setName] = useState(item.suggested_name);
  const [description, setDescription] = useState(item.suggested_description);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const a = await api.createAscent({ name: name.trim(), description: description.trim() });
      onConfirm(a);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      let display = msg;
      try {
        const parsed = JSON.parse(msg);
        if (parsed?.detail?.message) display = parsed.detail.message;
      } catch { /* */ }
      setError(display);
      setBusy(false);
    }
  };

  return (
    <div onClick={onCancel} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 520, maxWidth: '92%', background: '#0d0d0d',
        border: '1px solid #1f1f1f', borderRadius: 12, padding: '32px 36px',
      }}>
        <div style={{ fontSize: 11, color: '#666', fontFamily: MONO, letterSpacing: '0.08em', marginBottom: 4 }}>
          START ASCENT FROM HORIZON
        </div>
        <h2 style={{ margin: '0 0 18px', fontSize: 18, fontWeight: 500, color: '#fff' }}>{item.label}</h2>

        <label style={{ display: 'block', fontSize: 11, color: '#666', marginBottom: 6 }}>NAME</label>
        <input
          value={name} onChange={e => setName(e.target.value)}
          style={{ width: '100%', padding: '10px 12px', fontSize: 13, background: '#0a0a0a', border: '1px solid #1f1f1f', borderRadius: 6, color: '#fff', outline: 'none', marginBottom: 16 }}
        />
        <label style={{ display: 'block', fontSize: 11, color: '#666', marginBottom: 6 }}>DETAILS</label>
        <textarea
          value={description} onChange={e => setDescription(e.target.value)}
          rows={4}
          style={{ width: '100%', padding: '10px 12px', fontSize: 13, background: '#0a0a0a', border: '1px solid #1f1f1f', borderRadius: 6, color: '#fff', outline: 'none', resize: 'vertical', fontFamily: 'inherit', marginBottom: 18 }}
        />

        {error && (
          <div style={{ padding: '10px 12px', marginBottom: 14, border: '1px solid #3a1010', background: '#1a0808', borderRadius: 6, fontSize: 12, color: '#ef9a9a' }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} disabled={busy} style={{ padding: '8px 18px', fontSize: 12, background: 'transparent', border: '1px solid #1e1e1e', borderRadius: 6, color: '#666', cursor: 'pointer' }}>Cancel</button>
          <button onClick={submit} disabled={busy || !name.trim()} style={{
            padding: '8px 22px', fontSize: 12,
            background: busy || !name.trim() ? '#222' : '#fff',
            color: busy || !name.trim() ? '#555' : '#000',
            border: 'none', borderRadius: 6, fontWeight: 500,
            cursor: busy || !name.trim() ? 'not-allowed' : 'pointer',
          }}>{busy ? 'Generating…' : 'Generate plan'}</button>
        </div>
      </div>
    </div>
  );
}

function ClassicHorizon() {
  const [items, setItems] = useState<HorizonItem[]>([]);
  const [confirming, setConfirming] = useState<HorizonItem | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const refresh = async () => {
    setLoading(true);
    try {
      const r = await api.horizon();
      setItems(r.items);
    } catch { setItems([]); }
    setLoading(false);
  };

  useEffect(() => { refresh(); }, []);

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '32px 40px' }}>
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 11, color: '#666', letterSpacing: '0.1em', fontFamily: MONO }}>HORIZON</div>
        <h1 style={{ margin: '6px 0 0', fontSize: 26, fontWeight: 500, color: '#fff' }}>Suggested goals</h1>
        <p style={{ margin: '6px 0 0', fontSize: 12, color: '#666', maxWidth: 640, lineHeight: 1.5 }}>
          Topics that recur across your memories but don't yet have an active ascent.
        </p>
      </div>

      {loading && <div style={{ color: '#3a3a3a', fontSize: 12 }}>Detecting…</div>}

      {!loading && items.length === 0 && (
        <div style={{ ...CARD, padding: 40, textAlign: 'center' }}>
          <div style={{ fontSize: 14, color: '#666', marginBottom: 8 }}>No suggestions yet.</div>
          <div style={{ fontSize: 12, color: '#3a3a3a' }}>
            SHAIL surfaces a horizon item once a topic appears in 3+ memories without an active ascent.
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 14 }}>
        {items.map(it => (
          <div key={it.label} style={{ ...CARD, padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <span style={{ fontSize: 9, color: '#fbbf24', letterSpacing: '0.1em', fontFamily: MONO }}>◇ HORIZON</span>
              <span style={{ fontSize: 10, color: '#666', fontFamily: MONO }}>{it.memory_count} memories</span>
            </div>
            <div style={{ fontSize: 16, fontWeight: 500, color: '#fff', marginBottom: 6 }}>{it.suggested_name}</div>
            <div style={{ fontSize: 11, color: '#888', lineHeight: 1.55, marginBottom: 14, minHeight: 50 }}>{it.suggested_description}</div>
            {it.sample_titles.length > 0 && (
              <div style={{ marginBottom: 14, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {it.sample_titles.slice(0, 2).map(t => (
                  <div key={t} style={{ fontSize: 10, color: '#444', fontFamily: MONO, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>· {t}</div>
                ))}
              </div>
            )}
            <button
              onClick={() => setConfirming(it)}
              style={{ width: '100%', padding: '8px 0', fontSize: 12, background: '#fff', color: '#000', border: 'none', borderRadius: 6, fontWeight: 500, cursor: 'pointer' }}
            >
              Start ascent
            </button>
          </div>
        ))}
      </div>

      {confirming && (
        <ConfirmStart
          item={confirming}
          onCancel={() => setConfirming(null)}
          onConfirm={() => { setConfirming(null); navigate('/ascents'); }}
        />
      )}
    </div>
  );
}

// ── Entry point ──────────────────────────────────────────────────────────────

export function Horizon() {
  return flag('ui_v2') ? <ReplayTimeline /> : <ClassicHorizon />;
}
