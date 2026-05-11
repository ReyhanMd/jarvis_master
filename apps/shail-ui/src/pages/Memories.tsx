import React, { useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, MemoryRecord, SOURCE_COLOR, SOURCE_LABEL } from '../api';
import { MemoryCard } from '../components/MemoryCard';
import { useUIStore } from '../stores/ui';
import { flag } from '../lib/featureFlags';
import { StateBadge, type MemoryState } from '../components/primitives';

const SOURCES = ['chatgpt', 'claude', 'gemini', 'perplexity', 'web'] as const;
const DATE_OPTS = [
  { key: 'all',   label: 'All time' },
  { key: 'today', label: 'Today' },
  { key: 'week',  label: 'This week' },
  { key: 'month', label: 'This month' },
] as const;

function dateAfter(key: string): string | undefined {
  if (key === 'all') return undefined;
  const d = new Date();
  if (key === 'today') { d.setHours(0,0,0,0); return d.toISOString(); }
  if (key === 'week')  { d.setDate(d.getDate()-7); return d.toISOString(); }
  if (key === 'month') { d.setDate(d.getDate()-30); return d.toISOString(); }
}

export function Memories() {
  const v2 = flag('ui_v2');
  const { id: deepLinkId } = useParams();
  const navigate = useNavigate();
  const openInspector = useUIStore(s => s.openInspector);
  const qc = useQueryClient();

  const [query, setQuery]             = useState('');
  const [source, setSource]           = useState('all');
  const [date, setDate]               = useState('all');
  const [stateFacet, setStateFacet]   = useState<'all' | MemoryState>('all');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [selected, setSelected]       = useState<Set<string>>(new Set());
  const [deleteModal, setDeleteModal] = useState<{ ids: string[]; label: string } | null>(null);

  // Debounce free-text search.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  // Server fetch (cached).
  const searchQuery = useQuery({
    queryKey: ['memories', 'search', debouncedQuery, date],
    queryFn: () => api.search({ query: debouncedQuery, k: 100, after: dateAfter(date) }),
  });

  const allRecords: MemoryRecord[] = searchQuery.data?.items ?? [];
  const records = useMemo(() => {
    let r = allRecords;
    if (source !== 'all') r = r.filter(x => x.sourceApp === source);
    if (v2 && stateFacet !== 'all') r = r.filter(x => (x.state as MemoryState | undefined) === stateFacet);
    return r;
  }, [allRecords, source, stateFacet, v2]);
  const loading = searchQuery.isLoading;

  // Blueprint badge enrichment (separate cached query keyed by visible ids).
  const blueprintIdsKey = records.map(r => r.id).join(',');
  const blueprintQuery = useQuery({
    queryKey: ['memories', 'blueprint-ids', blueprintIdsKey],
    queryFn: () => api.getBlueprintIds(records.map(r => r.id)),
    enabled: records.length > 0,
  });
  const blueprintIds = useMemo(
    () => new Set(blueprintQuery.data?.ids ?? []),
    [blueprintQuery.data],
  );

  // Deep-link /memories/:id → open inspector slide-over (PR-08 mounts component).
  useEffect(() => {
    if (deepLinkId) openInspector(deepLinkId);
  }, [deepLinkId, openInspector]);

  // Optimistic delete via mutation.
  const deleteMutation = useMutation({
    mutationFn: (ids: string[]) => Promise.allSettled(ids.map(id => api.deleteMemory(id))),
    onSuccess: (_res, ids) => {
      qc.setQueryData<{ items: MemoryRecord[]; total: number }>(
        ['memories', 'search', debouncedQuery, date],
        (old) => old ? { ...old, items: old.items.filter(r => !ids.includes(r.id)) } : old,
      );
      setSelected(prev => { const next = new Set(prev); ids.forEach(id => next.delete(id)); return next; });
      setDeleteModal(null);
    },
  });
  const bulkDeleting = deleteMutation.isPending;

  function handleSelect(id: string, checked: boolean) {
    setSelected(prev => {
      const next = new Set(prev);
      checked ? next.add(id) : next.delete(id);
      return next;
    });
  }

  function handleSelectAll() {
    if (selected.size === records.length) setSelected(new Set());
    else setSelected(new Set(records.map(r => r.id)));
  }

  function handleConfirmDelete(ids: string[]) {
    deleteMutation.mutate(ids);
  }

  function handleBulkDelete() {
    if (!selected.size) return;
    const count = selected.size;
    setDeleteModal({ ids: [...selected], label: `Delete ${count} ${count === 1 ? 'memory' : 'memories'}? This cannot be undone.` });
  }

  function handleDeleted(id: string) {
    qc.setQueryData<{ items: MemoryRecord[]; total: number }>(
      ['memories', 'search', debouncedQuery, date],
      (old) => old ? { ...old, items: old.items.filter(r => r.id !== id) } : old,
    );
    setSelected(prev => { const next = new Set(prev); next.delete(id); return next; });
  }

  function handleOpenInspector(id: string) {
    if (!v2) return; // Inspector mounts behind v2 flag.
    openInspector(id);
    navigate(`/memories/${id}`);
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: '40px 48px 0' }}>
      {/* Page header */}
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 600, color: 'var(--shail-text-primary)', letterSpacing: '-0.5px' }}>
          Memories
        </h1>
        <p style={{ margin: '5px 0 0', fontSize: 13, color: 'var(--shail-text-muted)' }}>
          {loading ? 'Loading…' : `${records.length} ${records.length === 1 ? 'memory' : 'memories'}`}
        </p>
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search memories…"
          style={{
            background: 'var(--shail-bg-raised)',
            border: '1px solid var(--shail-border-subtle)',
            borderRadius: 8,
            padding: '10px 14px',
            fontSize: 13,
            color: 'var(--shail-text-primary)',
            outline: 'none',
            width: '100%',
            boxSizing: 'border-box',
            transition: 'border-color 0.15s',
          }}
          onFocus={e => (e.currentTarget.style.borderColor = 'var(--shail-border-strong)')}
          onBlur={e => (e.currentTarget.style.borderColor = 'var(--shail-border-subtle)')}
        />
        {/* Source + date pills in a single horizontally-scrollable row */}
        <div style={{ display: 'flex', gap: 6, overflowX: 'auto', scrollbarWidth: 'none' } as React.CSSProperties}>
          {['all', ...SOURCES].map(s => {
            const isActive = source === s;
            const color = s === 'all' ? 'var(--shail-text-muted)' : (SOURCE_COLOR[s] ?? 'var(--shail-text-muted)');
            const activeBg = s === 'all' ? 'var(--shail-bg-raised)' : (SOURCE_COLOR[s] ?? '#888') + '18';
            const activeBorder = s === 'all' ? 'var(--shail-border-strong)' : (SOURCE_COLOR[s] ?? '#888') + '50';
            return (
              <button
                key={s}
                onClick={() => setSource(s)}
                style={{
                  flexShrink: 0,
                  padding: '5px 11px',
                  borderRadius: 20,
                  fontSize: 11,
                  fontWeight: 500,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  border: `1px solid ${isActive ? activeBorder : 'var(--shail-border-subtle)'}`,
                  background: isActive ? activeBg : 'transparent',
                  color: isActive ? color : 'var(--shail-text-muted)',
                  transition: 'all 0.12s',
                }}
              >
                {s === 'all' ? 'All sources' : SOURCE_LABEL[s]}
              </button>
            );
          })}
          <div style={{ width: 1, background: 'var(--shail-border-subtle)', flexShrink: 0, margin: '0 2px' }} />
          {DATE_OPTS.map(opt => {
            const isActive = date === opt.key;
            return (
              <button
                key={opt.key}
                onClick={() => setDate(opt.key)}
                style={{
                  flexShrink: 0,
                  padding: '5px 11px',
                  borderRadius: 20,
                  fontSize: 11,
                  fontWeight: 500,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  border: `1px solid ${isActive ? 'var(--shail-evidence)50' : 'var(--shail-border-subtle)'}`,
                  background: isActive ? 'var(--shail-evidence-soft)' : 'transparent',
                  color: isActive ? 'var(--shail-evidence)' : 'var(--shail-text-muted)',
                  transition: 'all 0.12s',
                }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
        {v2 && (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', overflowX: 'auto', scrollbarWidth: 'none' } as React.CSSProperties}>
            <span style={{ fontSize: 10, color: 'var(--shail-text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', flexShrink: 0, marginRight: 2 }}>State</span>
            {(['all', 'captured', 'partial', 'replayable', 'failed'] as const).map(st => {
              const isActive = stateFacet === st;
              return (
                <button
                  key={st}
                  onClick={() => setStateFacet(st)}
                  style={{
                    flexShrink: 0,
                    padding: '4px 10px',
                    borderRadius: 14,
                    fontSize: 10,
                    fontWeight: 500,
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    border: `1px solid ${isActive ? 'var(--shail-border-strong)' : 'var(--shail-border-subtle)'}`,
                    background: isActive ? 'var(--shail-bg-raised)' : 'transparent',
                    color: isActive ? 'var(--shail-text-primary)' : 'var(--shail-text-muted)',
                    textTransform: 'capitalize',
                    transition: 'all 0.12s',
                  }}
                >
                  {st}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Bulk actions */}
      {records.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <button
            onClick={handleSelectAll}
            style={{ fontSize: 11, color: 'var(--shail-text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
          >
            {selected.size === records.length ? 'Deselect all' : 'Select all'}
          </button>
          {selected.size > 0 && (
            <button
              onClick={handleBulkDelete}
              disabled={bulkDeleting}
              style={{ fontSize: 11, color: 'var(--shail-danger)', background: 'none', border: 'none', cursor: 'pointer', padding: 0, opacity: bulkDeleting ? 0.5 : 1 }}
            >
              {bulkDeleting ? 'Deleting…' : `Delete ${selected.size} selected`}
            </button>
          )}
        </div>
      )}

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 48, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {loading && records.length === 0 && (
          Array.from({ length: 5 }).map((_, i) => (
            <div key={i} style={{ height: 80, borderRadius: 10, background: 'var(--shail-bg-raised)', border: '1px solid var(--shail-border-subtle)', animation: 'pulse 1.5s ease-in-out infinite' }} />
          ))
        )}
        {!loading && records.length === 0 && (
          <div style={{ marginTop: 80, textAlign: 'center', color: 'var(--shail-text-muted)', fontSize: 14, opacity: 0.5 }}>
            No memories found
          </div>
        )}
        {records.map(r => (
          <div
            key={r.id}
            onClick={(e) => {
              if (!v2) return;
              const tag = (e.target as HTMLElement).tagName;
              if (tag === 'INPUT' || tag === 'BUTTON' || tag === 'A') return;
              handleOpenInspector(r.id);
            }}
            style={{ cursor: v2 ? 'pointer' : 'default', position: 'relative' }}
          >
            {v2 && r.state && (
              <div style={{ position: 'absolute', top: 10, right: 10, zIndex: 1 }}>
                <StateBadge state={r.state as MemoryState} size="xs" />
              </div>
            )}
            <MemoryCard
              record={r}
              selected={selected.has(r.id)}
              onSelect={handleSelect}
              onDeleted={handleDeleted}
              onDeleteRequest={(id) => setDeleteModal({ ids: [id], label: 'Delete this memory? This cannot be undone.' })}
              showCheckbox
              hasBlueprint={blueprintIds.has(r.id)}
            />
          </div>
        ))}
      </div>

      {/* Delete confirm modal */}
      {deleteModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: 'var(--shail-bg-surface)', border: '1px solid var(--shail-border-subtle)', borderRadius: 12, padding: '28px 32px', maxWidth: 400, width: '90%' }}>
            <h3 style={{ margin: '0 0 10px', fontSize: 16, fontWeight: 600, color: 'var(--shail-text-primary)' }}>
              Delete memory?
            </h3>
            <p style={{ margin: '0 0 24px', fontSize: 13, color: 'var(--shail-text-secondary)', lineHeight: 1.6 }}>
              {deleteModal.label}
            </p>
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={() => setDeleteModal(null)}
                style={{ flex: 1, height: 36, borderRadius: 8, fontSize: 13, cursor: 'pointer', background: 'transparent', border: '1px solid var(--shail-border-subtle)', color: 'var(--shail-text-secondary)' }}
              >
                Cancel
              </button>
              <button
                onClick={() => handleConfirmDelete(deleteModal.ids)}
                disabled={bulkDeleting}
                style={{ flex: 1, height: 36, borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', background: 'var(--shail-danger)', border: 'none', color: '#fff', opacity: bulkDeleting ? 0.6 : 1 }}
              >
                {bulkDeleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
