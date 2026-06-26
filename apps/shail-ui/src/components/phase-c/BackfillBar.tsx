import { useEffect, useState } from 'react';
import { api } from '../../api';

type Status = {
  state: 'idle' | 'running' | 'done' | 'failed' | 'degraded';
  cursor: number;
  total_messages: number;
  progress_pct: number;
  remaining: number;
  job_id: string | null;
  error: string | null;
};

/**
 * Sprint 2: backfill control + progress.
 *
 * Polls /backfill/status every 2s while state === 'running'. Surfaces
 * degraded-mode banner when state === 'degraded' (Sprint 1 — Ollama down,
 * FTS keyword fallback in use).
 *
 * NOT yet browser-smoke tested — wire into ChatRenderer / session header.
 */
export function BackfillBar({ sessionId }: { sessionId: string }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      const s = await api.getBackfillStatus(sessionId);
      setStatus(s);
    } catch (e: any) {
      setErr(String(e));
    }
  }

  useEffect(() => {
    refresh();
  }, [sessionId]);

  useEffect(() => {
    if (status?.state !== 'running') return;
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, [status?.state, sessionId]);

  async function start() {
    setBusy(true);
    setErr(null);
    try {
      await api.backfillSession(sessionId, { synchronous: false });
      await refresh();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  const state = status?.state ?? 'idle';
  const pct = status?.progress_pct ?? 0;
  const running = state === 'running';
  const degraded = state === 'degraded';

  return (
    <div style={{
      padding: 10, background: '#0d0d0d', border: '1px solid #1e1e1e',
      borderRadius: 6, color: '#bbb', fontSize: 12,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>
          Backfill: <strong style={{
            color: degraded ? '#f59e0b' : state === 'done' ? '#22c55e' : '#fff',
          }}>{state}</strong>
        </span>
        <button
          onClick={start}
          disabled={busy || running}
          style={{
            padding: '5px 12px', fontSize: 11, fontWeight: 500,
            background: running ? '#1a1a1a' : '#fff',
            color: running ? '#555' : '#000',
            border: 'none', borderRadius: 5,
            cursor: running ? 'not-allowed' : 'pointer',
          }}
        >
          {running ? 'Running…' : state === 'failed' ? 'Resume' : 'Run backfill'}
        </button>
      </div>
      {status && (
        <div style={{ marginTop: 6, fontSize: 11, color: '#666' }}>
          {status.cursor} / {status.total_messages} messages ({pct.toFixed(1)}%)
        </div>
      )}
      <div style={{ marginTop: 4, height: 3, background: '#1a1a1a', borderRadius: 2 }}>
        <div
          style={{
            width: `${pct}%`,
            height: 3,
            background: degraded ? '#f59e0b' : '#22c55e',
            borderRadius: 2,
            transition: 'width 300ms',
          }}
        />
      </div>
      {degraded && (
        <div style={{
          marginTop: 6, padding: '6px 8px', background: '#1f1a0a',
          border: '1px solid #3a2a0a', borderRadius: 4, fontSize: 11, color: '#fbbf24',
        }}>
          ⚠ Embedder unavailable. Keyword (FTS) fallback in use — vector search degraded.
        </div>
      )}
      {status?.error && (
        <div style={{
          marginTop: 6, padding: '6px 8px', background: '#1f0a0a',
          border: '1px solid #3a1010', borderRadius: 4, fontSize: 11, color: '#ef4444',
        }}>
          Error: {status.error}
        </div>
      )}
      {err && <div style={{ color: '#ef4444', fontSize: 11, marginTop: 4 }}>{err}</div>}
    </div>
  );
}
