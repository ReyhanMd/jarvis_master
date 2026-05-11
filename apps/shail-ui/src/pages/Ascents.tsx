import React, { useEffect, useState } from 'react';
import { api, AscentDetail, AscentListResponse, AscentSummary, DeliverableItem } from '../api';
import { NewAscentModal } from '../components/NewAscentModal';
import { EmptyState } from '../components/primitives';

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const CARD = { background: '#0d0d0d', border: '1px solid #161616', borderRadius: 9 } as const;

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div style={{ height: 3, background: '#1a1a1a', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: '#fff', transition: 'width 0.3s' }} />
    </div>
  );
}

function DeliverableRow({
  d, expanded, onToggleExpand, onToggleTodo, busy,
}: {
  d: DeliverableItem;
  expanded: boolean;
  onToggleExpand: () => void;
  onToggleTodo: (todoId: string, completed: boolean) => void;
  busy: string | null;
}) {
  const done = d.todos.filter(t => t.completed).length;
  const total = d.todos.length;
  const pct = total ? (done / total) * 100 : 0;

  return (
    <div style={{ ...CARD, marginBottom: 10, overflow: 'hidden' }}>
      <div
        onClick={onToggleExpand}
        style={{
          padding: '14px 18px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          cursor: 'pointer',
        }}
      >
        <div style={{
          width: 18, height: 18, borderRadius: 4,
          background: d.completed ? '#22c55e' : '#1a1a1a',
          border: d.completed ? 'none' : '1px solid #2a2a2a',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, color: '#000', flexShrink: 0,
        }}>
          {d.completed ? '✓' : ''}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, color: '#fff', fontWeight: 500 }}>{d.text}</div>
          {d.description && (
            <div style={{ marginTop: 3, fontSize: 11, color: '#666' }}>{d.description}</div>
          )}
          <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 10, fontFamily: MONO, color: '#666', letterSpacing: '0.05em' }}>
              {done}/{total} TODOS
            </span>
            <div style={{ flex: 1 }}><ProgressBar pct={pct} /></div>
          </div>
        </div>
        <span style={{ color: '#444', fontSize: 14, transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s' }}>›</span>
      </div>

      {expanded && (
        <div style={{ padding: '4px 18px 16px', borderTop: '1px solid #161616' }}>
          {d.todos.map(t => {
            const isBusy = busy === t.id;
            return (
              <div
                key={t.id}
                onClick={() => !isBusy && onToggleTodo(t.id, !t.completed)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '9px 0',
                  borderBottom: '1px solid #131313',
                  cursor: isBusy ? 'wait' : 'pointer',
                  opacity: isBusy ? 0.5 : 1,
                }}
              >
                <span style={{
                  width: 14, height: 14, borderRadius: 3,
                  background: t.completed ? '#fff' : 'transparent',
                  border: t.completed ? '1px solid #fff' : '1px solid #2a2a2a',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 9, color: '#000', flexShrink: 0,
                }}>
                  {t.completed ? '✓' : ''}
                </span>
                <span style={{
                  flex: 1, fontSize: 12,
                  color: t.completed ? '#555' : '#ccc',
                  textDecoration: t.completed ? 'line-through' : 'none',
                }}>
                  {t.text}
                </span>
              </div>
            );
          })}
          {d.memory_ids.length > 0 && (
            <div style={{ marginTop: 10, fontSize: 10, color: '#444', fontFamily: MONO }}>
              CITED: {d.memory_ids.length} {d.memory_ids.length === 1 ? 'memory' : 'memories'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AscentDetailView({ ascentId, onBack, onDelete }: {
  ascentId: string;
  onBack: () => void;
  onDelete: () => void;
}) {
  const [data, setData] = useState<AscentDetail | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    api.getAscent(ascentId).then(d => {
      setData(d);
      // Expand the first deliverable by default for orientation.
      if (d.deliverables[0]) setExpanded({ [d.deliverables[0].id]: true });
    });
  }, [ascentId]);

  const toggleTodo = async (todoId: string, completed: boolean) => {
    if (!data) return;
    setBusy(todoId);
    try {
      const updated = await api.toggleTodo(ascentId, todoId, completed);
      setData(updated);
    } catch { /* ignore — leave UI as it was */ }
    setBusy(null);
  };

  const handleDelete = async () => {
    try {
      await api.deleteAscent(ascentId);
      onDelete();
    } catch { /* */ }
  };

  if (!data) {
    return (
      <div style={{ padding: 40, color: '#3a3a3a' }}>Loading…</div>
    );
  }

  const pct = Math.round(data.progress * 100);

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '32px 40px' }}>
      <button
        onClick={onBack}
        style={{
          background: 'none', border: 'none', color: '#666', fontSize: 12,
          padding: 0, cursor: 'pointer', marginBottom: 18, fontFamily: MONO,
        }}
      >
        ← All ascents
      </button>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 20 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: '#666', letterSpacing: '0.1em', fontFamily: MONO }}>ASCENT</div>
          <h1 style={{ margin: '6px 0 6px', fontSize: 24, fontWeight: 500, color: '#fff' }}>{data.name}</h1>
          {data.description && (
            <p style={{ margin: 0, fontSize: 13, color: '#888', lineHeight: 1.55 }}>{data.description}</p>
          )}
          <div style={{ marginTop: 14, display: 'flex', gap: 16, fontSize: 11, color: '#666', fontFamily: MONO }}>
            <span>{data.deliverable_count} DELIVERABLES</span>
            <span>{data.todos_completed}/{data.todo_count} TODOS</span>
            <span>{pct}%</span>
            <span>STATUS: {data.status.toUpperCase()}</span>
          </div>
        </div>
        <button
          onClick={() => setConfirmDelete(true)}
          style={{
            padding: '6px 12px', fontSize: 11, background: 'transparent',
            border: '1px solid #1f1f1f', color: '#666', borderRadius: 6, cursor: 'pointer',
          }}
        >
          Delete
        </button>
      </div>

      <div style={{ margin: '22px 0 28px' }}><ProgressBar pct={pct} /></div>

      <div>
        {data.deliverables.map(d => (
          <DeliverableRow
            key={d.id}
            d={d}
            expanded={!!expanded[d.id]}
            onToggleExpand={() => setExpanded(p => ({ ...p, [d.id]: !p[d.id] }))}
            onToggleTodo={(tid, c) => toggleTodo(tid, c)}
            busy={busy}
          />
        ))}
      </div>

      {confirmDelete && (
        <div onClick={() => setConfirmDelete(false)} style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }}>
          <div onClick={e => e.stopPropagation()} style={{
            background: '#0d0d0d', border: '1px solid #1f1f1f', borderRadius: 12,
            padding: '32px 36px', maxWidth: 400, width: '90%',
          }}>
            <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 500, color: '#fff' }}>Delete ascent?</h3>
            <p style={{ margin: '0 0 24px', fontSize: 13, color: '#888', lineHeight: 1.55 }}>
              "{data.name}" and all its deliverables and todos will be removed. This cannot be undone.
            </p>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setConfirmDelete(false)} style={{
                flex: 1, padding: '9px 0', fontSize: 13, background: 'transparent',
                border: '1px solid #1e1e1e', color: '#666', borderRadius: 6, cursor: 'pointer',
              }}>Cancel</button>
              <button onClick={handleDelete} style={{
                flex: 1, padding: '9px 0', fontSize: 13, fontWeight: 600,
                background: '#ef4444', border: 'none', color: '#fff', borderRadius: 6, cursor: 'pointer',
              }}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function Ascents() {
  const [list, setList] = useState<AscentListResponse | null>(null);
  const [opened, setOpened] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);

  const refresh = () => api.listAscents().then(setList).catch(() => setList(null));
  useEffect(() => { refresh(); }, []);

  if (opened) {
    return (
      <AscentDetailView
        ascentId={opened}
        onBack={() => { setOpened(null); refresh(); }}
        onDelete={() => { setOpened(null); refresh(); }}
      />
    );
  }

  if (!list) {
    return <div style={{ padding: 40, color: '#3a3a3a' }}>Loading…</div>;
  }

  const ascents: AscentSummary[] = list.items;
  const slotsLeft = list.limit - list.active_count;

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '32px 40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 11, color: '#666', letterSpacing: '0.1em', fontFamily: MONO }}>ASCENTS</div>
          <h1 style={{ margin: '6px 0 0', fontSize: 26, fontWeight: 500, color: '#fff' }}>Goals & plans</h1>
          <p style={{ margin: '6px 0 0', fontSize: 12, color: '#666' }}>
            {list.tier === 'pro'
              ? `${list.active_count} active · pro tier (unlimited)`
              : `${list.active_count}/${list.limit} active · ${slotsLeft > 0 ? `${slotsLeft} free slot${slotsLeft === 1 ? '' : 's'} remaining` : 'limit reached'}`}
          </p>
        </div>
        <button
          onClick={() => setShowNew(true)}
          style={{
            padding: '8px 18px', fontSize: 12, background: '#fff', color: '#000',
            border: 'none', borderRadius: 7, fontWeight: 500, cursor: 'pointer',
          }}
        >
          + New ascent
        </button>
      </div>

      {ascents.length === 0 && (
        <EmptyState
          title="No ascents yet"
          hint='Click "New ascent" to define your first goal — SHAIL will break it into deliverables and todos using your memories as context.'
          action={{ label: '+ New ascent', onClick: () => setShowNew(true) }}
        />
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 14 }}>
        {ascents.map(a => {
          const pct = Math.round(a.progress * 100);
          return (
            <div key={a.id} onClick={() => setOpened(a.id)} style={{
              ...CARD, padding: 18, cursor: 'pointer', transition: 'border-color 0.1s',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 9, fontFamily: MONO, color: a.status === 'active' ? '#22c55e' : '#666', letterSpacing: '0.1em' }}>
                  ● {a.status.toUpperCase()}
                </span>
                <span style={{ fontSize: 10, fontFamily: MONO, color: '#444' }}>{pct}%</span>
              </div>
              <div style={{ fontSize: 15, fontWeight: 500, color: '#fff', marginBottom: 6, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {a.name}
              </div>
              <div style={{ fontSize: 11, color: '#666', lineHeight: 1.45, height: 32, overflow: 'hidden' }}>
                {a.description || '(no description)'}
              </div>
              <div style={{ marginTop: 12 }}><ProgressBar pct={pct} /></div>
              <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#444', fontFamily: MONO }}>
                <span>{a.deliverable_count} D · {a.todo_count} T</span>
                <span>{a.todos_completed} done</span>
              </div>
            </div>
          );
        })}
      </div>

      {showNew && (
        <NewAscentModal
          onClose={() => setShowNew(false)}
          onCreated={(a) => { setShowNew(false); refresh(); setOpened(a.id); }}
        />
      )}
    </div>
  );
}
