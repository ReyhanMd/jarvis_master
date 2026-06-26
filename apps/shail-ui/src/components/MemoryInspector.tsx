import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { useUIStore } from '../stores/ui';
import { ActionBar, ConfidenceBadge, EmptyState, StateBadge, type Action, type MemoryState } from './primitives';

const PANEL_WIDTH = 560;

type TabKey = 'source' | 'chunks' | 'facts' | 'lineage' | 'replay' | 'metadata';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'source',    label: 'Source' },
  { key: 'chunks',    label: 'Chunks' },
  { key: 'facts',     label: 'Facts' },
  { key: 'lineage',   label: 'Lineage' },
  { key: 'replay',    label: 'Replay' },
  { key: 'metadata',  label: 'Metadata' },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 18 }}>
      <h3 style={{ margin: '0 0 8px', fontSize: 11, fontWeight: 600,
        color: 'var(--shail-text-muted, #6c707a)',
        textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {title}
      </h3>
      <div style={{ fontSize: 12, color: 'var(--shail-text-primary, #e0e0e0)', lineHeight: 1.5 }}>
        {children}
      </div>
    </section>
  );
}

export function MemoryInspector() {
  const id = useUIStore(s => s.inspectorMemoryId);
  const close = useUIStore(s => s.closeInspector);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<TabKey>('source');

  // Hooks must be called unconditionally; guards inside `enabled`.
  const memQ = useQuery({
    queryKey: ['memory', 'detail', id],
    queryFn: () => api.getMemory(id!),
    enabled: !!id,
    staleTime: 30_000,
  });
  const blueprintQ = useQuery({
    queryKey: ['memory', 'blueprint', id],
    queryFn: () => api.getBlueprint(id!),
    enabled: !!id && tab === 'facts',
    staleTime: 60_000,
  });
  const artifactsQ = useQuery({
    queryKey: ['memory', 'artifacts', id],
    queryFn: () => api.getArtifacts(id!),
    enabled: !!id && tab === 'chunks',
    staleTime: 60_000,
  });
  const materializationsQ = useQuery({
    queryKey: ['memory', 'materializations', id],
    queryFn: () => api.getMaterializations(id!),
    enabled: !!id && tab === 'replay',
    staleTime: 60_000,
  });
  const relatedQ = useQuery({
    queryKey: ['memory', 'related', id],
    queryFn: () => api.getRelatedMemories(id!),
    enabled: !!id && tab === 'lineage',
    staleTime: 60_000,
  });
  const healthQ = useQuery({
    queryKey: ['memory', 'health', id],
    queryFn: () => api.getCaptureHealth(id!),
    enabled: !!id,
    staleTime: 60_000,
  });

  const deleteMutation = useMutation({
    mutationFn: (mid: string) => api.deleteMemory(mid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memories'] });
      handleClose();
    },
  });

  function handleClose() {
    close();
    if (window.location.pathname.match(/\/memories\/[^/]+$/)) {
      navigate('/memories');
    }
  }

  if (!id) return null;

  const mem = memQ.data;
  const actions: Action[] = mem ? [
    { label: 'Replay', onClick: () => setTab('replay'), variant: 'primary' },
    { label: 'Open source', onClick: () => mem.sourceUrl && window.open(mem.sourceUrl, '_blank'), disabled: !mem.sourceUrl },
    { label: mem.pinned ? 'Unpin' : 'Pin', onClick: () => { /* PR-17 */ } },
    { label: 'Export', onClick: () => { /* PR-18 */ } },
    { label: 'Delete', onClick: () => deleteMutation.mutate(id), variant: 'destructive', disabled: deleteMutation.isPending },
  ] : [];

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={handleClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
          zIndex: 90,
        }}
      />
      {/* Panel */}
      <aside
        style={{
          position: 'fixed', top: 0, right: 0, bottom: 0,
          width: PANEL_WIDTH, maxWidth: '100vw',
          background: 'var(--shail-bg-base, #0c0d10)',
          borderLeft: '1px solid var(--shail-border-strong, #2a2a2a)',
          zIndex: 95,
          display: 'flex', flexDirection: 'column',
          color: 'var(--shail-text-primary, #e0e0e0)',
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        }}
        aria-label="Memory inspector"
      >
        {/* Header */}
        <header style={{ padding: '20px 24px 12px', borderBottom: '1px solid var(--shail-border-subtle, #1a1a1a)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <span style={{ fontSize: 10, color: 'var(--shail-text-muted, #6c707a)', textTransform: 'uppercase', letterSpacing: 0.6 }}>
              Memory · {mem?.sourceApp ?? '…'}
            </span>
            <button onClick={handleClose} aria-label="Close"
              style={{ background: 'none', border: 'none', color: '#888', fontSize: 18, cursor: 'pointer' }}>
              ✕
            </button>
          </div>
          <h2 style={{ margin: '0 0 8px', fontSize: 16, fontWeight: 500, lineHeight: 1.3 }}>
            {mem?.title ?? (memQ.isLoading ? 'Loading…' : 'Memory')}
          </h2>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {mem?.state && <StateBadge state={mem.state as MemoryState} size="xs" />}
            {typeof mem?.confidence === 'number' && <ConfidenceBadge value={mem.confidence} showBar />}
            {mem?.timestamp && (
              <span style={{ fontSize: 10, color: 'var(--shail-text-muted, #6c707a)' }}>
                {new Date(mem.timestamp).toLocaleString()}
              </span>
            )}
            {typeof mem?.version === 'number' && mem.version > 1 && (
              <span style={{ fontSize: 10, color: 'var(--shail-text-muted, #6c707a)' }}>v{mem.version}</span>
            )}
          </div>
          {healthQ.data && (
            <div style={{
              marginTop: 10, padding: '6px 10px',
              background: 'var(--shail-bg-surface, #0a0a0a)',
              border: '1px solid var(--shail-border-subtle, #1a1a1a)',
              borderRadius: 5,
              display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap',
              fontSize: 10, color: 'var(--shail-text-secondary, #b0b0b0)',
            }}>
              <span>completeness: <b style={{ color: '#e0e0e0' }}>{healthQ.data.completeness}</b></span>
              <span>artifacts: <b style={{ color: '#e0e0e0' }}>{healthQ.data.artifact_count}</b></span>
              <span>materializations: <b style={{ color: '#e0e0e0' }}>{healthQ.data.materialization_count}</b></span>
              {healthQ.data.has_active_materialization && <span style={{ color: 'var(--shail-evidence, #6c8cd5)' }}>active ✓</span>}
            </div>
          )}
        </header>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, padding: '8px 16px',
          borderBottom: '1px solid var(--shail-border-subtle, #1a1a1a)',
          overflowX: 'auto' }}>
          {TABS.map(t => {
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                style={{
                  padding: '6px 12px', fontSize: 11, fontWeight: 500,
                  background: active ? 'var(--shail-bg-overlay, #1a1a1a)' : 'transparent',
                  color: active ? 'var(--shail-text-primary, #fff)' : 'var(--shail-text-muted, #6c707a)',
                  border: 'none', borderRadius: 5, cursor: 'pointer',
                }}
              >
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
          {tab === 'source' && (
            <Section title="Source">
              {memQ.isLoading && <div style={{ color: '#666' }}>Loading…</div>}
              {memQ.error && <div style={{ color: '#e07070' }}>Failed to load.</div>}
              {mem && (
                <>
                  {mem.sourceUrl && (
                    <a href={mem.sourceUrl} target="_blank" rel="noreferrer"
                      style={{ color: 'var(--shail-accent, #7aa6e0)', fontSize: 11, wordBreak: 'break-all' }}>
                      {mem.sourceUrl}
                    </a>
                  )}
                  <pre style={{ marginTop: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    fontFamily: 'inherit', fontSize: 12, lineHeight: 1.55,
                    background: 'var(--shail-bg-surface, #0a0a0a)',
                    border: '1px solid var(--shail-border-subtle, #1a1a1a)',
                    borderRadius: 6, padding: 12, color: 'var(--shail-text-secondary, #b0b0b0)' }}>
                    {mem.content || mem.summary}
                  </pre>
                </>
              )}
            </Section>
          )}

          {tab === 'chunks' && (
            <Section title={`Artifacts (${artifactsQ.data?.items.length ?? 0})`}>
              {artifactsQ.isLoading && <div style={{ color: '#666' }}>Loading…</div>}
              {!artifactsQ.isLoading && (artifactsQ.data?.items.length ?? 0) === 0 && (
                <EmptyState title="No artifacts" hint="No raw capture artifacts stored for this memory." />
              )}
              {artifactsQ.data?.items.map(a => (
                <div key={a.artifact_id} style={{
                  padding: '10px 12px', marginBottom: 8,
                  background: 'var(--shail-bg-surface, #0a0a0a)',
                  border: '1px solid var(--shail-border-subtle, #1a1a1a)',
                  borderRadius: 6, fontSize: 11,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontWeight: 500 }}>{a.artifact_kind}</span>
                    <span style={{ color: '#666' }}>seq {a.artifact_seq}</span>
                  </div>
                  <div style={{ color: '#888' }}>
                    {a.completeness} · {a.byte_size}b · {new Date(a.captured_at).toLocaleString()}
                  </div>
                </div>
              ))}
            </Section>
          )}

          {tab === 'facts' && (
            <Section title="Extracted facts">
              {blueprintQ.isLoading && <div style={{ color: '#666' }}>Loading…</div>}
              {blueprintQ.error && <EmptyState title="No blueprint" hint="No extracted facts available for this memory." />}
              {blueprintQ.data && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {blueprintQ.data.summary && (
                    <div>
                      <strong style={{ fontSize: 11, color: '#888' }}>Summary</strong>
                      <p style={{ margin: '4px 0 0', fontSize: 12, lineHeight: 1.55 }}>{blueprintQ.data.summary}</p>
                    </div>
                  )}
                  {blueprintQ.data.key_entities?.length > 0 && (
                    <div>
                      <strong style={{ fontSize: 11, color: '#888' }}>Key entities</strong>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                        {blueprintQ.data.key_entities.map((e, i) => (
                          <span key={i} style={{ fontSize: 11, padding: '3px 8px',
                            background: 'var(--shail-bg-overlay, #1a1a1a)', borderRadius: 4 }}>
                            {e}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {blueprintQ.data.decisions?.length > 0 && (
                    <div>
                      <strong style={{ fontSize: 11, color: '#888' }}>Decisions</strong>
                      <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12, lineHeight: 1.6 }}>
                        {blueprintQ.data.decisions.map((d, i) => (
                          <li key={i}>{typeof d === 'string' ? d : d.statement}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {blueprintQ.data.next_actions?.length > 0 && (
                    <div>
                      <strong style={{ fontSize: 11, color: '#888' }}>Next actions</strong>
                      <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12, lineHeight: 1.6 }}>
                        {blueprintQ.data.next_actions.map((a, i) => <li key={i}>{a}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </Section>
          )}

          {tab === 'lineage' && (
            <Section title="Related memories">
              {relatedQ.isLoading && <div style={{ color: '#666' }}>Loading…</div>}
              {!relatedQ.isLoading && (relatedQ.data?.length ?? 0) === 0 && (
                <EmptyState title="No related memories" hint="Nothing linked to this memory yet." />
              )}
              {relatedQ.data?.map(r => (
                <button key={r.id}
                  onClick={() => useUIStore.getState().openInspector(r.id)}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left',
                    padding: '8px 10px', marginBottom: 6,
                    background: 'var(--shail-bg-surface, #0a0a0a)',
                    border: '1px solid var(--shail-border-subtle, #1a1a1a)',
                    borderRadius: 5, color: 'inherit', cursor: 'pointer', fontSize: 12,
                  }}>
                  <div style={{ fontWeight: 500 }}>{r.title || r.sourceUrl}</div>
                  <div style={{ fontSize: 10, color: '#888', marginTop: 2 }}>{r.sourceApp} · {new Date(r.timestamp).toLocaleDateString()}</div>
                </button>
              ))}
            </Section>
          )}

          {tab === 'replay' && (
            <Section title="Materializations">
              {materializationsQ.isLoading && <div style={{ color: '#666' }}>Loading…</div>}
              {!materializationsQ.isLoading && (materializationsQ.data?.items.length ?? 0) === 0 && (
                <EmptyState title="No replay versions"
                  hint="No alternate extractions exist yet. Replay this memory to generate a new version." />
              )}
              {materializationsQ.data?.items.map(m => (
                <div key={m.materialization_id} style={{
                  padding: '10px 12px', marginBottom: 8,
                  background: m.is_active ? 'var(--shail-evidence-soft, #1d1d36)' : 'var(--shail-bg-surface, #0a0a0a)',
                  border: '1px solid var(--shail-border-subtle, #1a1a1a)',
                  borderRadius: 6, fontSize: 11,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontWeight: 500 }}>{m.extractor_bundle_version}</span>
                    {m.is_active && <span style={{ color: 'var(--shail-evidence, #6c8cd5)' }}>active</span>}
                  </div>
                  <div style={{ color: '#888' }}>
                    {m.content_type} · {m.status} · {new Date(m.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
              {mem && (
                <button
                  onClick={() => api.createReplayJob({ memoryId: id, mode: 'shadow' })
                    .then(job => {
                      const stored = localStorage.getItem('shail_replay_jobs');
                      const ids: string[] = stored ? JSON.parse(stored) : [];
                      if (!ids.includes(job.replay_job_id)) {
                        localStorage.setItem('shail_replay_jobs', JSON.stringify([job.replay_job_id, ...ids].slice(0, 50)));
                      }
                      return qc.invalidateQueries({ queryKey: ['memory', 'materializations', id] });
                    })}
                  style={{
                    marginTop: 8, padding: '8px 14px', fontSize: 12,
                    background: 'var(--shail-accent-soft, #1a2a40)',
                    color: 'var(--shail-accent, #7aa6e0)',
                    border: '1px solid var(--shail-accent, #7aa6e0)',
                    borderRadius: 5, cursor: 'pointer',
                  }}>
                  Replay now (shadow)
                </button>
              )}
            </Section>
          )}

          {tab === 'metadata' && mem && (
            <Section title="Metadata">
              <pre style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, lineHeight: 1.6,
                background: 'var(--shail-bg-surface, #0a0a0a)',
                border: '1px solid var(--shail-border-subtle, #1a1a1a)',
                borderRadius: 6, padding: 12, color: 'var(--shail-text-secondary, #b0b0b0)',
                whiteSpace: 'pre-wrap' }}>
{JSON.stringify({
  id: mem.id,
  customId: mem.customId,
  eventType: mem.eventType,
  sourceApp: mem.sourceApp,
  sourceUrl: mem.sourceUrl,
  timestamp: mem.timestamp,
  tags: mem.tags,
  pinned: mem.pinned,
  confidence: mem.confidence,
  state: mem.state,
  version: mem.version,
  parentId: mem.parentId,
  fidelity: mem.fidelity,
}, null, 2)}
              </pre>
            </Section>
          )}
        </div>

        {/* Action footer */}
        <footer style={{ padding: '12px 24px',
          borderTop: '1px solid var(--shail-border-subtle, #1a1a1a)',
          background: 'var(--shail-bg-surface, #0a0a0a)' }}>
          <ActionBar actions={actions} dense />
        </footer>
      </aside>
    </>
  );
}
