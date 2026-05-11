import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api, McpProvider, MemoryRecord } from '../api';
import { EmptyState } from '../components/primitives';
import { flag } from '../lib/featureFlags';

const MONO = 'ui-monospace,"SF Mono",Menlo,monospace';

const ICONS: Record<string, string> = {
  drive:  '▲',
  notion: '◻',
  github: '◈',
  gmail:  '✉',
};

const DESCRIPTIONS: Record<string, string> = {
  drive:  'Index Google Docs, plain-text and markdown files. Active fetch on every chat query.',
  notion: 'Index pages from your Notion workspace. Active fetch on every chat query.',
  github: 'Index your owner repos (READMEs + metadata). Issue & PR search on every chat query.',
  gmail:  'Index messages in selected labels. Vector-search at chat time (no live email API calls).',
};

interface RetrievalResult {
  loading: boolean;
  items: MemoryRecord[];
  total: number;
  error: string | null;
}

export function Connections() {
  const [providers, setProviders] = useState<McpProvider[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const [labelPicker, setLabelPicker] = useState<boolean>(false);
  const [retrieval, setRetrieval] = useState<Record<string, RetrievalResult>>({});

  const reload = useCallback(async () => {
    try {
      const r = await api.listMcpProviders();
      setProviders(r.items);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    reload();
    pollTimer.current = setInterval(() => { reload(); }, 3000);
    return () => { if (pollTimer.current) clearInterval(pollTimer.current); };
  }, [reload]);

  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      const data = e.data as { type?: string; ok?: boolean; provider?: string; error?: string };
      if (data?.type !== 'shail-mcp-result') return;
      if (data.ok) reload();
      else setError(data.error ?? 'OAuth failed');
    };
    window.addEventListener('message', onMsg);
    return () => window.removeEventListener('message', onMsg);
  }, [reload]);

  async function handleConnect(name: string) {
    setError(null);
    setBusy(name);
    try {
      const r = await api.startMcpAuth(name);
      const w = window.open(r.authorize_url, 'shail-mcp', 'width=520,height=640');
      if (!w) throw new Error('Popup blocked — allow popups for this site');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleDisconnect(name: string) {
    if (!confirm(`Disconnect ${name}? Indexed data will remain searchable until you delete it manually.`)) return;
    setBusy(name);
    try {
      await api.disconnectMcp(name);
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleReindex(name: string) {
    setBusy(name);
    try {
      await api.reindexMcp(name);
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleTestRetrieval(name: string) {
    setRetrieval(prev => ({ ...prev, [name]: { loading: true, items: [], total: 0, error: null } }));
    try {
      const r = await api.search({ query: name, k: 3 });
      setRetrieval(prev => ({ ...prev, [name]: { loading: false, items: r.items, total: r.total, error: null } }));
    } catch (e) {
      setRetrieval(prev => ({ ...prev, [name]: { loading: false, items: [], total: 0, error: (e as Error).message } }));
    }
  }

  return (
    <div style={{ flex: 1, padding: '40px 48px', overflowY: 'auto' }}>
      <h1 style={{ margin: 0, fontSize: 22, fontWeight: 500, color: '#fff', letterSpacing: '-0.4px' }}>Connections</h1>
      <p style={{ margin: '6px 0 32px', fontSize: 13, color: '#3a3a3a' }}>
        OAuth-connected sources. Connected providers are indexed in the background and queried in real-time during chat.
      </p>

      {error && (
        <div style={{ marginBottom: 18, padding: '10px 14px', background: '#1a0808', border: '1px solid #3a1010', borderRadius: 7, color: '#ef9a9a', fontSize: 12 }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 720 }}>
        {(providers ?? []).map(p => (
          <ProviderCard
            key={p.name}
            p={p}
            busy={busy === p.name}
            retrieval={retrieval[p.name] ?? null}
            onConnect={() => handleConnect(p.name)}
            onDisconnect={() => handleDisconnect(p.name)}
            onReindex={() => handleReindex(p.name)}
            onShowLabels={() => setLabelPicker(true)}
            onTestRetrieval={() => handleTestRetrieval(p.name)}
          />
        ))}
        {providers && providers.length === 0 && (
          <EmptyState
            title="No providers available"
            hint="Configure OAuth credentials in your .env file to enable external source connections."
          />
        )}
      </div>

      {labelPicker && (
        <GmailLabelPicker onClose={() => { setLabelPicker(false); reload(); }} />
      )}
    </div>
  );
}

function HealthBar({ count, max = 500 }: { count: number; max?: number }) {
  const pct = Math.min(100, (count / max) * 100);
  const color = pct > 80 ? '#22c55e' : pct > 30 ? '#fbbf24' : '#666';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
      <div style={{ flex: 1, height: 3, background: '#161616', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, transition: 'width 0.3s' }} />
      </div>
      <span style={{ fontSize: 10, color, fontFamily: MONO, flexShrink: 0 }}>{count} indexed</span>
    </div>
  );
}

function ProviderCard({
  p, busy, retrieval, onConnect, onDisconnect, onReindex, onShowLabels, onTestRetrieval,
}: {
  p: McpProvider;
  busy: boolean;
  retrieval: RetrievalResult | null;
  onConnect: () => void;
  onDisconnect: () => void;
  onReindex: () => void;
  onShowLabels: () => void;
  onTestRetrieval: () => void;
}) {
  const indexing = p.index_status === 'indexing';

  return (
    <div style={{ background: '#0a0a0a', border: '1px solid #161616', borderRadius: 10, padding: '20px 24px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, flex: 1, minWidth: 0 }}>
          <span style={{ fontSize: 20, color: p.connected ? '#fff' : '#2a2a2a', marginTop: 1 }}>
            {ICONS[p.name] || '◯'}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ fontSize: 14, fontWeight: 500, color: '#ccc' }}>{p.label}</div>
              {p.connected && (
                <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.08em', color: '#22c55e', background: '#0a1a0d', border: '1px solid #1c5e2d', borderRadius: 4, padding: '2px 6px', fontFamily: MONO }}>
                  CONNECTED
                </span>
              )}
              {!p.configured && (
                <span title="Set OAuth credentials in .env" style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.08em', color: '#fbbf24', background: '#1a1208', border: '1px solid #3a2810', borderRadius: 4, padding: '2px 6px', fontFamily: MONO }}>
                  NOT CONFIGURED
                </span>
              )}
            </div>
            <div style={{ fontSize: 12, color: '#444', marginTop: 4, lineHeight: 1.5 }}>
              {DESCRIPTIONS[p.name] || ''}
            </div>
            {p.connected && (
              <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 14, fontSize: 11, color: '#666', fontFamily: MONO }}>
                {p.metadata.email && <span>{p.metadata.email}</span>}
                {p.metadata.login && <span>@{p.metadata.login}</span>}
                {p.metadata.workspace_name && <span>{p.metadata.workspace_name}</span>}
                {p.last_synced && <span>· synced {new Date(p.last_synced).toLocaleString()}</span>}
              </div>
            )}
            {p.connected && <HealthBar count={p.indexed_count} />}
            {p.connected && indexing && (
              <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, fontSize: 11, color: '#8ab4f8' }}>
                <span style={{
                  display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                  background: '#8ab4f8', boxShadow: '0 0 6px #8ab4f888',
                  animation: 'pulse 1.4s ease-in-out infinite',
                }} />
                Indexing… {p.indexed_count} so far
              </div>
            )}
            {p.index_error && (
              <div style={{ marginTop: 10, fontSize: 11, color: '#ef9a9a' }}>{p.index_error}</div>
            )}

            {/* Test retrieval results */}
            {retrieval && (
              <div style={{ marginTop: 12, padding: '10px 12px', background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 7 }}>
                {retrieval.loading ? (
                  <span style={{ fontSize: 11, color: '#3a3a3a' }}>Searching…</span>
                ) : retrieval.error ? (
                  <span style={{ fontSize: 11, color: '#ef9a9a' }}>{retrieval.error}</span>
                ) : retrieval.items.length === 0 ? (
                  <span style={{ fontSize: 11, color: '#3a3a3a' }}>No memories found for this source yet.</span>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div style={{ fontSize: 10, color: '#555', fontFamily: MONO, marginBottom: 2 }}>
                      RETRIEVAL SAMPLE · {retrieval.total} total memories in store
                    </div>
                    {retrieval.items.map(m => (
                      <div key={m.id} style={{ fontSize: 11, color: '#aaa', lineHeight: 1.4 }}>
                        · {m.title}
                        {typeof m.score === 'number' && (
                          <span style={{ color: '#555', marginLeft: 6, fontFamily: MONO }}>{(m.score * 100).toFixed(0)}%</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end', flexShrink: 0 }}>
          {!p.connected ? (
            <button
              disabled={!p.configured || busy}
              onClick={onConnect}
              style={{
                padding: '7px 18px', borderRadius: 6, fontSize: 12, fontWeight: 500,
                cursor: p.configured && !busy ? 'pointer' : 'not-allowed',
                background: p.configured ? '#fff' : '#0d0d0d',
                border: p.configured ? 'none' : '1px solid #1a1a1a',
                color: p.configured ? '#000' : '#2a2a2a',
              }}
            >
              {busy ? '…' : 'Connect'}
            </button>
          ) : (
            <>
              {flag('ui_v2') && (
                <button
                  onClick={onTestRetrieval}
                  disabled={!!retrieval?.loading}
                  style={{
                    padding: '6px 14px', borderRadius: 6, fontSize: 11, fontWeight: 500,
                    cursor: retrieval?.loading ? 'not-allowed' : 'pointer',
                    background: 'transparent', border: '1px solid #1f3a4a', color: '#7aa6e0',
                  }}
                >
                  {retrieval?.loading ? '…' : 'Test retrieval'}
                </button>
              )}
              <button
                onClick={onReindex}
                disabled={busy || indexing}
                style={{
                  padding: '6px 14px', borderRadius: 6, fontSize: 11, fontWeight: 500,
                  cursor: !busy && !indexing ? 'pointer' : 'not-allowed',
                  background: 'transparent', border: '1px solid #1f1f1f', color: '#aaa',
                }}
              >
                {indexing ? 'Indexing…' : 'Re-sync'}
              </button>
              {p.name === 'gmail' && (
                <button
                  onClick={onShowLabels}
                  style={{ padding: '6px 14px', borderRadius: 6, fontSize: 11, fontWeight: 500, cursor: 'pointer', background: 'transparent', border: '1px solid #1f1f1f', color: '#aaa' }}
                >
                  Labels
                </button>
              )}
              <button
                onClick={onDisconnect}
                disabled={busy}
                style={{ padding: '6px 14px', borderRadius: 6, fontSize: 11, cursor: busy ? 'not-allowed' : 'pointer', background: 'transparent', border: '1px solid #3a1010', color: '#ef4444' }}
              >
                Disconnect
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Gmail label picker ──────────────────────────────────────────────────────

const DEFAULT_LABELS = ['INBOX', 'IMPORTANT', 'STARRED'];

function GmailLabelPicker({ onClose }: { onClose: () => void }) {
  const [labels, setLabels] = useState<{ id: string; name: string; type: string }[]>([]);
  const [selected, setSelected] = useState<string[]>(DEFAULT_LABELS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [{ labels: ls }, { settings }] = await Promise.all([
          api.gmailLabels(),
          api.getMcpSettings('gmail'),
        ]);
        setLabels(ls);
        const cur = (settings.labels as string[] | undefined) ?? DEFAULT_LABELS;
        setSelected(cur);
      } catch (e) {
        setErr((e as Error).message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function save() {
    setSaving(true);
    try {
      await api.putMcpSettings('gmail', { labels: selected });
      await api.reindexMcp('gmail');
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function toggle(id: string) {
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)', zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 440, maxWidth: '92%', maxHeight: '80vh',
        background: '#0d0d0d', border: '1px solid #1f1f1f',
        borderRadius: 12, padding: '28px 32px',
        display: 'flex', flexDirection: 'column',
      }}>
        <h3 style={{ margin: '0 0 6px', fontSize: 16, fontWeight: 500, color: '#fff' }}>Gmail labels to index</h3>
        <p style={{ margin: '0 0 16px', fontSize: 12, color: '#666' }}>
          Only messages in selected labels are indexed. Recommended: <code style={{ fontFamily: MONO }}>IMPORTANT</code> + <code style={{ fontFamily: MONO }}>STARRED</code> for best signal.
        </p>
        <div style={{ flex: 1, overflowY: 'auto', marginBottom: 16, paddingRight: 4 }}>
          {loading && <div style={{ color: '#3a3a3a', fontSize: 12 }}>Loading…</div>}
          {err && <div style={{ color: '#ef9a9a', fontSize: 12 }}>{err}</div>}
          {!loading && labels.map(l => (
            <label key={l.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', cursor: 'pointer', borderBottom: '1px solid #131313' }}>
              <input type="checkbox" checked={selected.includes(l.id)} onChange={() => toggle(l.id)} style={{ accentColor: '#fff' }} />
              <span style={{ flex: 1, fontSize: 12, color: '#ccc' }}>{l.name}</span>
              <span style={{ fontSize: 9, color: '#444', fontFamily: MONO, letterSpacing: '0.05em' }}>{l.type}</span>
            </label>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '7px 16px', fontSize: 12, background: 'transparent', border: '1px solid #1f1f1f', color: '#666', borderRadius: 6, cursor: 'pointer' }}>
            Cancel
          </button>
          <button onClick={save} disabled={saving || loading} style={{ padding: '7px 16px', fontSize: 12, fontWeight: 500, background: '#fff', color: '#000', border: 'none', borderRadius: 6, cursor: saving ? 'not-allowed' : 'pointer' }}>
            {saving ? 'Saving…' : 'Save & re-index'}
          </button>
        </div>
      </div>
    </div>
  );
}
