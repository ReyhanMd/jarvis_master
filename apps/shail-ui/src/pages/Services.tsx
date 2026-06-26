import React, { useEffect, useRef, useState, useCallback } from 'react';
import { api, ServiceInfo, SystemStatus } from '../api';

const SERVICE_META: Record<string, { label: string; description: string }> = {
  backend:  { label: 'Backend',      description: 'FastAPI · localhost:8000' },
  chroma:   { label: 'Memory Store', description: 'ChromaDB · embedded' },
  ollama:   { label: 'Ollama',       description: 'Local LLM · localhost:11434' },
  redis:    { label: 'Redis',        description: 'Task queue · localhost:6379' },
  worker:   { label: 'Task Worker',  description: 'Background AI tasks' },
};

const FREE_ORDER = ['backend', 'chroma', 'ollama'];
const PRO_ORDER  = ['backend', 'chroma', 'ollama', 'redis', 'worker'];

function StatusDot({ status }: { status: ServiceInfo['status'] }) {
  const color =
    status === 'running'       ? '#22c55e' :
    status === 'starting'      ? '#f59e0b' :
    status === 'not_installed' ? '#6b7280' :
    status === 'error'         ? '#ef4444' : '#3a3a3a';
  return (
    <span style={{
      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
      background: color, flexShrink: 0,
      boxShadow: status === 'running' ? `0 0 6px ${color}88` : 'none',
    }} />
  );
}

function StatusBadge({ status }: { status: ServiceInfo['status'] }) {
  const label =
    status === 'running'       ? 'running' :
    status === 'starting'      ? 'starting…' :
    status === 'not_installed' ? 'not installed' :
    status === 'error'         ? 'error' :
    status === 'stopped'       ? 'stopped' : status;
  const color =
    status === 'running'       ? '#22c55e' :
    status === 'starting'      ? '#f59e0b' :
    status === 'not_installed' ? '#555' :
    status === 'error'         ? '#ef4444' : '#444';
  return (
    <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', color, textTransform: 'uppercase' }}>
      {label}
    </span>
  );
}

export function Services() {
  const [data, setData]           = useState<SystemStatus | null>(null);
  const [liveStatus, setLiveStatus] = useState<Record<string, ServiceInfo['status']>>({});
  const [starting, setStarting]   = useState(false);
  const [stopping, setStopping]   = useState(false);
  const [startLog, setStartLog]   = useState<string[]>([]);
  const [stopNote, setStopNote]   = useState('');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = async () => {
    try {
      const d = await api.systemStatus();
      setData(d);
      // Seed liveStatus from fetched data (don't override mid-start SSE state)
      if (!starting) {
        const s: Record<string, ServiceInfo['status']> = {};
        for (const [k, v] of Object.entries(d.services)) s[k] = v.status;
        setLiveStatus(s);
      }
    } catch { /* backend may be unreachable briefly */ }
  };

  useEffect(() => {
    fetchStatus();
    intervalRef.current = setInterval(fetchStatus, 5000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  const order = data?.tier === 'pro' ? PRO_ORDER : FREE_ORDER;

  async function handleStart() {
    setStarting(true);
    setStartLog([]);
    setStopNote('');
    const key = localStorage.getItem('shail_api_key') ?? '';
    const res = await fetch(api.systemStartUrl(), {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}` },
    });
    if (!res.ok || !res.body) { setStarting(false); return; }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.service) {
            setLiveStatus(prev => ({ ...prev, [evt.service]: evt.status }));
            const meta = SERVICE_META[evt.service];
            const msg = evt.status === 'error'
              ? `✗ ${meta?.label ?? evt.service}: ${evt.message ?? 'failed'}`
              : evt.status === 'already_running'
              ? `— ${meta?.label ?? evt.service}: already running`
              : `✓ ${meta?.label ?? evt.service}: ${evt.status}`;
            setStartLog(l => [...l, msg]);
          }
          if (evt.done) { setStarting(false); fetchStatus(); }
        } catch { /* malformed SSE line */ }
      }
    }
    setStarting(false);
  }

  async function handleStop() {
    setStopping(true);
    setStartLog([]);
    try {
      const result = await api.systemStop();
      setStopNote(result.note);
      await fetchStatus();
    } catch { /* ignore */ }
    setStopping(false);
  }

  async function handleRestart(service: string) {
    setLiveStatus(prev => ({ ...prev, [service]: 'starting' }));
    const key = localStorage.getItem('shail_api_key') ?? '';
    const res = await fetch(api.systemRestartUrl(service), {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}` },
    });
    if (!res.ok || !res.body) { fetchStatus(); return; }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.service) setLiveStatus(prev => ({ ...prev, [evt.service]: evt.status }));
          if (evt.done) fetchStatus();
        } catch { /* ignore */ }
      }
    }
  }

  const allRunning = data
    ? order.filter(k => k !== 'backend').every(k => (liveStatus[k] ?? data.services[k]?.status) === 'running')
    : false;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: '40px 48px 0' }}>
      <h1 style={{ margin: '0 0 4px', fontSize: 22, fontWeight: 500, color: '#fff', letterSpacing: '-0.4px' }}>Services</h1>
      <p style={{ margin: '0 0 36px', fontSize: 13, color: '#333' }}>Manage the SHAIL runtime stack.</p>

      {/* Action buttons */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 32 }}>
        <button
          onClick={handleStart}
          disabled={starting || stopping}
          style={{
            padding: '9px 22px', borderRadius: 7, fontSize: 12, fontWeight: 500,
            cursor: (starting || stopping) ? 'default' : 'pointer',
            background: '#0d0d0d', border: '1px solid #1e1e1e',
            color: (starting || stopping) ? '#333' : (allRunning ? '#2a2a2a' : '#bbb'),
            transition: 'color 0.1s',
          }}
          onMouseEnter={e => { if (!starting && !stopping && !allRunning) e.currentTarget.style.color = '#fff'; }}
          onMouseLeave={e => { e.currentTarget.style.color = (starting || stopping) ? '#333' : (allRunning ? '#2a2a2a' : '#bbb'); }}
        >
          {starting ? 'Starting…' : '▶ Start All'}
        </button>
        <button
          onClick={handleStop}
          disabled={starting || stopping}
          style={{
            padding: '9px 22px', borderRadius: 7, fontSize: 12, fontWeight: 500,
            cursor: (starting || stopping) ? 'default' : 'pointer',
            background: '#0d0d0d', border: '1px solid #1e1e1e',
            color: (starting || stopping) ? '#333' : '#555',
            transition: 'color 0.1s',
          }}
          onMouseEnter={e => { if (!starting && !stopping) e.currentTarget.style.color = '#ef4444'; }}
          onMouseLeave={e => { e.currentTarget.style.color = (starting || stopping) ? '#333' : '#555'; }}
        >
          {stopping ? 'Stopping…' : '■ Stop All'}
        </button>
      </div>

      {/* Service cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 24 }}>
        {order.map(key => {
          const info = data?.services[key];
          const status: ServiceInfo['status'] = liveStatus[key] ?? info?.status ?? 'stopped';
          const meta = SERVICE_META[key] ?? { label: key, description: '' };
          const canRestart = key !== 'backend' && status !== 'not_installed';
          const queue = data?.blueprint_queue;
          const ollamaDetail = key === 'ollama'
            ? [
                queue ? `blueprint queue ${queue.pending} pending / ${queue.running} running` : null,
                info?.managed_owner ? `owner ${info.managed_owner}` : null,
              ].filter(Boolean).join(' · ')
            : '';
          return (
            <div
              key={key}
              style={{
                display: 'flex', alignItems: 'center', gap: 14,
                padding: '14px 18px', borderRadius: 8,
                background: '#0a0a0a', border: '1px solid #161616',
              }}
            >
              <StatusDot status={status} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: '#ccc' }}>{meta.label}</div>
                <div style={{ fontSize: 11, color: '#2f2f2f', marginTop: 1 }}>{meta.description}</div>
                {ollamaDetail && (
                  <div style={{ fontSize: 10, color: '#444', marginTop: 4 }}>{ollamaDetail}</div>
                )}
              </div>
              <StatusBadge status={status} />
              {key === 'ollama' && status === 'not_installed' && (
                <a
                  href="https://ollama.com/download"
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: 11, color: '#444', marginLeft: 12, textDecoration: 'underline' }}
                >
                  Install
                </a>
              )}
              {canRestart && status !== 'starting' && (
                <button
                  onClick={() => handleRestart(key)}
                  style={{
                    marginLeft: 10, padding: '4px 10px', borderRadius: 5, fontSize: 11,
                    cursor: 'pointer', background: 'none', border: '1px solid #1e1e1e',
                    color: '#333', transition: 'color 0.1s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.color = '#888')}
                  onMouseLeave={e => (e.currentTarget.style.color = '#333')}
                >
                  Restart
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* Start log */}
      {startLog.length > 0 && (
        <div style={{ marginBottom: 16, padding: '12px 16px', borderRadius: 7, background: '#080808', border: '1px solid #161616' }}>
          {startLog.map((line, i) => (
            <div key={i} style={{ fontSize: 11, color: line.startsWith('✗') ? '#ef4444' : '#444', lineHeight: 1.8 }}>
              {line}
            </div>
          ))}
        </div>
      )}

      {/* Stop note */}
      {stopNote && (
        <div style={{ padding: '10px 14px', borderRadius: 7, background: '#080808', border: '1px solid #1e1e1e', fontSize: 11, color: '#444' }}>
          {stopNote}
        </div>
      )}

      {/* Shell scripts reference */}
      <ScriptsReference />
    </div>
  );
}

const MONO_F = 'ui-monospace,"SF Mono",Menlo,monospace';

const SCRIPTS: { label: string; what: string; cmd: string }[] = [
  { label: 'Start all',     what: 'Starts backend, Ollama, Chroma, Redis, and worker. Health-checks each service.',        cmd: './shailctl start' },
  { label: 'Stop all',      what: 'Stops all services — handles orphans, zombies, and untracked PIDs. Kills by PID file AND port AND process name.', cmd: './shailctl stop' },
  { label: 'Restart',       what: 'Stop + start in one command. Use this after any backend code edit — no stale processes.', cmd: './shailctl restart' },
  { label: 'Status',        what: 'Shows what is running, what is stopped, and PID for each service.',                     cmd: './shailctl status' },
  { label: 'Tail logs',     what: 'Stream live logs for any service. Replace shail_api with: ollama, chroma, worker, etc.', cmd: './shailctl logs shail_api' },
  { label: 'Clean',         what: 'Nukes all PID files and resets state. Use when stop fails or processes are stuck.',      cmd: './shailctl clean' },
];

function ScriptsReference() {
  const [copiedIdx, setCopiedIdx] = React.useState<number | null>(null);

  const copy = (cmd: string, i: number) => {
    navigator.clipboard.writeText(cmd);
    setCopiedIdx(i);
    setTimeout(() => setCopiedIdx(null), 1800);
  };

  return (
    <div style={{ marginTop: 36, paddingBottom: 48 }}>
      <div style={{ fontSize: 11, color: '#3a3a3a', fontFamily: MONO_F, letterSpacing: '0.08em', marginBottom: 6 }}>
        TERMINAL — SINGLE COMMAND FOR EVERYTHING
      </div>
      <p style={{ margin: '0 0 16px', fontSize: 12, color: '#2f2f2f', lineHeight: 1.6 }}>
        Run from <code style={{ fontFamily: MONO_F, color: '#444' }}>~/jarvis_master/</code> in your terminal.
        After any backend code edit, use <code style={{ fontFamily: MONO_F, color: '#666' }}>./shailctl restart</code>.
      </p>

      {/* Code block */}
      <div style={{ background: '#080808', border: '1px solid #141414', borderRadius: 9, padding: '16px 20px', marginBottom: 16 }}>
        {SCRIPTS.map((s, i) => (
          <div
            key={s.label}
            style={{ display: 'flex', alignItems: 'baseline', gap: 0, marginBottom: i < SCRIPTS.length - 1 ? 6 : 0 }}
          >
            <code style={{ fontFamily: MONO_F, fontSize: 12, color: '#fff', minWidth: 200 }}>{s.cmd}</code>
            <span style={{ fontFamily: MONO_F, fontSize: 12, color: '#3a3a3a' }}>&nbsp;&nbsp;# {s.what.split('.')[0].toLowerCase()}</span>
          </div>
        ))}
      </div>

      {/* Detail rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {SCRIPTS.map((s, i) => (
          <div
            key={s.label}
            style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '9px 14px', background: '#080808', border: '1px solid #0f0f0f', borderRadius: 6 }}
          >
            <code style={{ fontFamily: MONO_F, fontSize: 11, color: '#fff', minWidth: 160, flexShrink: 0 }}>{s.cmd}</code>
            <span style={{ fontSize: 11, color: '#333', flex: 1, lineHeight: 1.4 }}>{s.what}</span>
            <button
              onClick={() => copy(s.cmd, i)}
              style={{ fontSize: 10, padding: '3px 10px', borderRadius: 4, background: 'none', border: '1px solid #1a1a1a', color: copiedIdx === i ? '#22c55e' : '#2a2a2a', cursor: 'pointer', flexShrink: 0, fontFamily: MONO_F, transition: 'color 0.1s' }}
            >
              {copiedIdx === i ? 'copied' : 'copy'}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
