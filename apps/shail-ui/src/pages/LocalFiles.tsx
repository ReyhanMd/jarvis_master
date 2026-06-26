/**
 * LocalFiles — explicit folder/file indexing + filesystem watcher management.
 *
 * Two paths:
 *  1. One-shot index: paste an absolute path, click Index. Walks dir and
 *     updates path_index only. File content is read at answer time.
 *  2. Watch mode: paste an absolute path, click Watch. Backend uses watchdog
 *     (FSEvents on macOS) to debounce + reindex on every change.
 *
 * Browser sandbox can't read absolute filesystem paths, so we accept text input
 * rather than <input type="file"> (which only gives sandboxed File objects with
 * no real path). The macOS desktop app uses NSOpenPanel and POSTs the absolute
 * path — same backend endpoint.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { EmptyState } from '../components/primitives';

const MONO = 'ui-monospace,"SF Mono",Menlo,monospace';

interface Watch {
  user_id: string;
  path: string;
  created_at: string;
  last_event_at: string | null;
  event_count: number;
}

export function LocalFiles() {
  const [pathInput, setPathInput] = useState('');
  const [watches, setWatches] = useState<Watch[]>([]);
  const [lastIngest, setLastIngest] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null); // 'index' | 'watch' | null
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const r = await api.listFolderWatches();
      setWatches(r.watches);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  async function handleIngest() {
    if (!pathInput.trim()) return;
    setError(null);
    setBusy('index');
    setLastIngest(null);
    try {
      const r = await api.ingestLocalFiles([pathInput.trim()]);
      setLastIngest(
        `Indexed ${r.ingested} file pointer(s) from ${r.files_seen} file(s) seen` +
        (r.skipped ? `, ${r.skipped} skipped` : '') +
        (r.errors.length ? ` — errors: ${r.errors.join('; ')}` : ''),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleWatch() {
    if (!pathInput.trim()) return;
    setError(null);
    setBusy('watch');
    try {
      const r = await api.startFolderWatch(pathInput.trim());
      if (!r.ok) throw new Error(r.error ?? 'watch failed');
      setPathInput('');
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleStopWatch(path: string) {
    if (!confirm(`Stop watching ${path}? Already-indexed file pointers stay searchable.`)) return;
    try {
      await api.stopFolderWatch(path);
      await reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div style={{ flex: 1, padding: '40px 48px', overflowY: 'auto' }}>
      <h1 style={{ margin: 0, fontSize: 22, fontWeight: 500, color: '#fff', letterSpacing: '-0.4px' }}>
        Local Files
      </h1>
      <p style={{ margin: '6px 0 32px', fontSize: 13, color: '#3a3a3a' }}>
        Map files on your machine for local citations. SHAIL does not save these files as memories.
      </p>

      {error && (
        <div style={{ marginBottom: 18, padding: '10px 14px', background: '#1a0808',
                      border: '1px solid #3a1010', borderRadius: 7, color: '#ef9a9a', fontSize: 12 }}>
          {error}
        </div>
      )}

      <div style={{ background: '#0a0a0a', border: '1px solid #161616', borderRadius: 10,
                    padding: '20px 24px', maxWidth: 720, marginBottom: 18 }}>
        <div style={{ fontSize: 12, color: '#555', marginBottom: 10, fontFamily: MONO, letterSpacing: '0.05em' }}>
          ABSOLUTE PATH (file or directory)
        </div>
        <input
          type="text"
          value={pathInput}
          onChange={e => setPathInput(e.target.value)}
          placeholder="/Users/you/Documents/notes"
          spellCheck={false}
          style={{
            width: '100%', padding: '10px 12px', background: '#000',
            border: '1px solid #1f1f1f', borderRadius: 6, color: '#ccc',
            fontFamily: MONO, fontSize: 12, marginBottom: 12,
          }}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={handleIngest}
            disabled={!pathInput.trim() || !!busy}
            style={{
              padding: '7px 18px', borderRadius: 6, fontSize: 12, fontWeight: 500,
              cursor: !pathInput.trim() || busy ? 'not-allowed' : 'pointer',
              background: '#fff', color: '#000', border: 'none',
            }}
          >
            {busy === 'index' ? 'Indexing…' : 'Index once'}
          </button>
          <button
            onClick={handleWatch}
            disabled={!pathInput.trim() || !!busy}
            style={{
              padding: '7px 18px', borderRadius: 6, fontSize: 12, fontWeight: 500,
              cursor: !pathInput.trim() || busy ? 'not-allowed' : 'pointer',
              background: 'transparent', border: '1px solid #1f3a4a', color: '#7aa6e0',
            }}
          >
            {busy === 'watch' ? 'Starting…' : 'Watch folder'}
          </button>
        </div>
        {lastIngest && (
          <div style={{ marginTop: 12, padding: '10px 12px', background: '#0d1a0d',
                        border: '1px solid #1c5e2d', borderRadius: 6, color: '#7eff9e', fontSize: 11 }}>
            {lastIngest}
          </div>
        )}
      </div>

      <h2 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 500, color: '#999',
                   fontFamily: MONO, letterSpacing: '0.05em' }}>
        ACTIVE WATCHES
      </h2>
      {watches.length === 0 ? (
        <EmptyState
          title="No active watches"
          hint="Add a folder above with Watch to auto-reindex on change."
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 720 }}>
          {watches.map(w => (
            <div key={w.path} style={{
              background: '#0a0a0a', border: '1px solid #161616', borderRadius: 10,
              padding: '16px 20px', display: 'flex', justifyContent: 'space-between', gap: 16,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, color: '#ccc', fontFamily: MONO,
                              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {w.path}
                </div>
                <div style={{ fontSize: 10, color: '#555', marginTop: 6, fontFamily: MONO, letterSpacing: '0.05em' }}>
                  STARTED {new Date(w.created_at).toLocaleString()}
                  {w.event_count > 0 && (
                    <>  ·  {w.event_count} reindex event(s)</>
                  )}
                  {w.last_event_at && (
                    <>  ·  last {new Date(w.last_event_at).toLocaleString()}</>
                  )}
                </div>
              </div>
              <button
                onClick={() => handleStopWatch(w.path)}
                style={{
                  padding: '6px 14px', borderRadius: 6, fontSize: 11, cursor: 'pointer',
                  background: 'transparent', border: '1px solid #3a1010', color: '#ef4444',
                  flexShrink: 0,
                }}
              >
                Stop
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
