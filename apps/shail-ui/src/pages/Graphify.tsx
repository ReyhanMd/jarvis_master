/**
 * Graphify — live navigable map of the local file/folder graph.
 *
 * Backend auto-scans content roots on startup; watchdog observers debounce-
 * reindex on changes. This page polls /path-index/stats every 5s and refreshes
 * the tree when the dataset shifts. Click a folder to expand. Click a file to
 * preview metadata, refresh its pointer, or reveal it in Finder.
 *
 * Local files are pointer-only: chat reads relevant files at answer time and
 * cites the local path. File contents are not saved as memories.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { api, PathTreeNode } from '../api';
import { EmptyState } from '../components/primitives';

const MONO = 'ui-monospace,"SF Mono",Menlo,monospace';

const KIND_COLOR: Record<string, string> = {
  code:  '#7aa6e0',
  doc:   '#fbbf24',
  data:  '#22c55e',
  media: '#c084fc',
  log:   '#9ca3af',
  other: '#444',
};

interface Stats {
  total: number;
  total_files: number;
  total_dirs: number;
  by_kind: Record<string, number>;
  embedded: number;
  last_indexed_at: number | null;
}

export function Graphify() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [childrenByPath, setChildrenByPath] = useState<Record<string, PathTreeNode[]>>({});
  const [rootNodes, setRootNodes] = useState<PathTreeNode[]>([]);
  const [selected, setSelected] = useState<PathTreeNode | null>(null);
  const [refreshingPath, setRefreshingPath] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [lastIndexedTs, setLastIndexedTs] = useState<number | null>(null);

  const loadStats = useCallback(async () => {
    try {
      const s = await api.pathIndexStats();
      setStats(s);
      return s;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, []);

  const loadRoots = useCallback(async () => {
    try {
      const r = await api.pathIndexTree(undefined, 1, 500);
      setRootNodes(r.nodes.filter(n => n.is_dir));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  // Initial load
  useEffect(() => {
    (async () => {
      const s = await loadStats();
      if (s) setLastIndexedTs(s.last_indexed_at);
      await loadRoots();
    })();
  }, [loadStats, loadRoots]);

  // Live updates: poll stats every 5s; if last_indexed_at moved, refresh expanded subtrees.
  useEffect(() => {
    const t = setInterval(async () => {
      const s = await loadStats();
      if (!s) return;
      if (s.last_indexed_at && s.last_indexed_at !== lastIndexedTs) {
        setLastIndexedTs(s.last_indexed_at);
        // Refresh roots + currently-expanded paths.
        await loadRoots();
        for (const path of expanded) {
          await loadChildren(path);
        }
      }
    }, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastIndexedTs, expanded]);

  async function loadChildren(path: string) {
    try {
      const r = await api.pathIndexTree(path, 1, 500);
      // Filter out the path itself; we only want its direct children.
      const children = r.nodes.filter(n => n.id !== path);
      setChildrenByPath(prev => ({ ...prev, [path]: children }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function toggle(node: PathTreeNode) {
    if (!node.is_dir) {
      setSelected(node);
      return;
    }
    const next = new Set(expanded);
    if (next.has(node.id)) {
      next.delete(node.id);
    } else {
      next.add(node.id);
      if (!childrenByPath[node.id]) await loadChildren(node.id);
    }
    setExpanded(next);
  }

  async function handleRefreshPath(path: string) {
    setRefreshingPath(path);
    try {
      const r = await api.pathIndexEmbed(path);
      // Refresh the parent's children so the badge updates
      const parent = path.split('/').slice(0, -1).join('/');
      if (parent) await loadChildren(parent);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshingPath(null);
    }
  }

  async function handleOpenPath(path: string) {
    try {
      await api.pathIndexOpen(path);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleSync() {
    setSyncing(true);
    try {
      await api.pathIndexSync();
      // Sync runs in background; poll until last_indexed_at moves or 30s pass
      const t0 = Date.now();
      while (Date.now() - t0 < 30000) {
        await new Promise(r => setTimeout(r, 2000));
        const s = await loadStats();
        if (s && s.last_indexed_at && s.last_indexed_at !== lastIndexedTs) {
          setLastIndexedTs(s.last_indexed_at);
          await loadRoots();
          break;
        }
      }
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div style={{ flex: 1, padding: '40px 48px', overflowY: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 500, color: '#fff', letterSpacing: '-0.4px' }}>Graphify</h1>
        <button onClick={handleSync} disabled={syncing} style={{
          padding: '6px 14px', borderRadius: 6, fontSize: 11, fontWeight: 500,
          cursor: syncing ? 'wait' : 'pointer',
          background: 'transparent', border: '1px solid #1f3a4a', color: '#7aa6e0',
        }}>{syncing ? 'Scanning…' : 'Re-scan filesystem'}</button>
      </div>
      <p style={{ margin: '0 0 24px', fontSize: 13, color: '#3a3a3a' }}>
        Auto-discovered map of your content folders. Chat uses matching files as pointer-only citations and does not store them as memories.
      </p>

      {error && (
        <div style={{ marginBottom: 18, padding: '10px 14px', background: '#1a0808',
                      border: '1px solid #3a1010', borderRadius: 7, color: '#ef9a9a', fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* Stats bar */}
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginBottom: 24 }}>
        <Stat label="FILES"     value={stats?.total_files ?? '—'} />
        <Stat label="FOLDERS"   value={stats?.total_dirs ?? '—'} />
        {stats?.by_kind && Object.entries(stats.by_kind).slice(0, 4).map(([k, n]) => (
          <Stat key={k} label={k.toUpperCase()} value={n} color={KIND_COLOR[k] || '#666'} />
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 18, alignItems: 'start' }}>
        {/* Tree */}
        <div style={{ background: '#0a0a0a', border: '1px solid #161616', borderRadius: 10, padding: '12px 0', minHeight: 400 }}>
          {rootNodes.length === 0 ? (
            <EmptyState
              title="No content folders found"
              hint="Backend scans ~/Documents, ~/Desktop, ~/Downloads, ~/Code, ~/Projects, etc. on startup."
            />
          ) : (
            rootNodes.map(root => (
              <TreeRow
                key={root.id}
                node={root}
                depth={0}
                expanded={expanded}
                childrenByPath={childrenByPath}
                onToggle={toggle}
                selected={selected?.id ?? null}
              />
            ))
          )}
        </div>

        {/* Detail panel */}
        <div style={{ background: '#0a0a0a', border: '1px solid #161616', borderRadius: 10, padding: 18, position: 'sticky', top: 0 }}>
          {!selected ? (
            <div style={{ fontSize: 12, color: '#3a3a3a' }}>Pick a file from the tree to inspect.</div>
          ) : (
            <FileDetail
              node={selected}
              refreshing={refreshingPath === selected.id}
              onRefresh={() => handleRefreshPath(selected.id)}
              onOpen={() => handleOpenPath(selected.id)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, hint, color }: { label: string; value: number | string; hint?: string; color?: string }) {
  return (
    <div style={{ background: '#0a0a0a', border: '1px solid #161616', borderRadius: 8, padding: '12px 16px', minWidth: 110 }}>
      <div style={{ fontSize: 9, color: color || '#444', fontFamily: MONO, letterSpacing: '0.08em', marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 500, color: '#ccc' }}>
        {value}
        {hint && <span style={{ fontSize: 10, color: '#555', marginLeft: 6, fontFamily: MONO }}>{hint}</span>}
      </div>
    </div>
  );
}

function TreeRow({
  node, depth, expanded, childrenByPath, onToggle, selected,
}: {
  node: PathTreeNode;
  depth: number;
  expanded: Set<string>;
  childrenByPath: Record<string, PathTreeNode[]>;
  onToggle: (n: PathTreeNode) => void;
  selected: string | null;
}) {
  const open = expanded.has(node.id);
  const indent = depth * 16;
  const isSel = selected === node.id;
  return (
    <>
      <div
        onClick={() => onToggle(node)}
        style={{
          padding: `4px 14px 4px ${14 + indent}px`,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontFamily: MONO,
          fontSize: 12,
          color: isSel ? '#fff' : node.is_dir ? '#ccc' : '#888',
          background: isSel ? '#101820' : 'transparent',
        }}
      >
        <span style={{ color: '#555', width: 10 }}>
          {node.is_dir ? (open ? '▾' : '▸') : ' '}
        </span>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.is_dir ? `${node.name}/` : node.name}
        </span>
        {!node.is_dir && node.kind && (
          <span style={{
            fontSize: 9, color: KIND_COLOR[node.kind] || '#666',
            fontFamily: MONO, letterSpacing: '0.05em',
          }}>{node.kind.toUpperCase()}</span>
        )}
        {node.is_dir && node.child_count > 0 && (
          <span style={{ fontSize: 10, color: '#3a3a3a' }}>{node.child_count}</span>
        )}
      </div>
      {open && childrenByPath[node.id]?.map(child => (
        <TreeRow
          key={child.id}
          node={child}
          depth={depth + 1}
          expanded={expanded}
          childrenByPath={childrenByPath}
          onToggle={onToggle}
          selected={selected}
        />
      ))}
    </>
  );
}

function FileDetail({
  node, refreshing, onRefresh, onOpen,
}: {
  node: PathTreeNode;
  refreshing: boolean;
  onRefresh: () => void;
  onOpen: () => void;
}) {
  const sizeKb = node.size ? (node.size / 1024).toFixed(1) : '—';
  const mtime = node.mtime ? new Date(node.mtime * 1000).toLocaleString() : '—';
  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 500, color: '#fff', marginBottom: 8, wordBreak: 'break-word' }}>
        {node.name}
      </div>
      <div style={{ fontSize: 10, color: '#666', fontFamily: MONO, wordBreak: 'break-all', marginBottom: 12 }}>
        {node.id}
      </div>
      <DetailRow k="KIND"     v={node.kind || 'other'} />
      <DetailRow k="SIZE"     v={`${sizeKb} KB`} />
      <DetailRow k="MODIFIED" v={mtime} />
      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
        <button
          onClick={onOpen}
          style={{
            padding: '7px 14px', borderRadius: 6, fontSize: 12, fontWeight: 500,
            cursor: 'pointer', background: '#fff', color: '#000', border: 'none',
          }}
        >Reveal in Finder</button>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          style={{
            padding: '7px 14px', borderRadius: 6, fontSize: 12, fontWeight: 500,
            cursor: refreshing ? 'wait' : 'pointer',
            background: 'transparent', color: '#7aa6e0', border: '1px solid #1f3a4a',
          }}
        >{refreshing ? 'Refreshing…' : 'Refresh pointer'}</button>
      </div>
    </div>
  );
}

function DetailRow({ k, v, color }: { k: string; v: string; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #131313' }}>
      <span style={{ fontSize: 10, color: '#444', fontFamily: MONO, letterSpacing: '0.06em' }}>{k}</span>
      <span style={{ fontSize: 11, color: color || '#aaa', fontFamily: MONO }}>{v}</span>
    </div>
  );
}
