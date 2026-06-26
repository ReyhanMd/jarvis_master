import { useState } from 'react';
import { api } from '../../api';

type Source = 'chatgpt' | 'claude' | 'cursor';

/**
 * Sprint 4: drag-drop or click-to-upload importer.
 *
 * Accepts JSON exports from ChatGPT (conversations.json), Claude.ai,
 * or Cursor. Server parses + creates chat_sessions + enqueues backfill.
 *
 * NOT yet browser-smoke tested.
 */
export function ImportDropzone({ onImported }: { onImported?: (sessionIds: string[]) => void }) {
  const [source, setSource] = useState<Source>('chatgpt');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{
    conversations_seen: number;
    sessions_created: number;
    messages_inserted: number;
    session_ids: string[];
    errors: string[];
  } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function upload(file: File) {
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const r = await api.importChats(file, source, true);
      setResult(r);
      onImported?.(r.session_ids);
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{
      padding: 14, background: '#0d0d0d', border: '1px solid #1e1e1e', borderRadius: 7,
      color: '#bbb',
    }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10 }}>
        <label style={{ fontSize: 12, color: '#888' }}>Source:</label>
        <select
          value={source}
          onChange={(e) => setSource(e.target.value as Source)}
          style={{
            padding: '5px 8px', fontSize: 12, background: '#1a1a1a',
            color: '#fff', border: '1px solid #262626', borderRadius: 5,
          }}
        >
          <option value="chatgpt">ChatGPT (conversations.json)</option>
          <option value="claude">Claude.ai export</option>
          <option value="cursor">Cursor chat log</option>
        </select>
      </div>
      <div
        style={{
          padding: 26, textAlign: 'center', background: '#080808',
          border: '1px dashed #262626', borderRadius: 6,
        }}
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          const f = e.dataTransfer.files?.[0];
          if (f) upload(f);
        }}
      >
        <input
          type="file"
          accept="application/json,.json"
          disabled={busy}
          style={{ color: '#888', fontSize: 12 }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload(f);
          }}
        />
        <div style={{ fontSize: 11, color: '#555', marginTop: 8 }}>
          {busy ? 'Uploading & parsing…' : 'Drop a JSON export here or click to select'}
        </div>
      </div>
      {result && (
        <div style={{ marginTop: 10, fontSize: 12, color: '#aaa' }}>
          Imported <strong style={{ color: '#22c55e' }}>{result.sessions_created}</strong> sessions
          ({result.messages_inserted} messages). Backfill running in background.
          {result.errors.length > 0 && (
            <div style={{ color: '#ef4444' }}>Errors: {result.errors.length}</div>
          )}
        </div>
      )}
      {err && <div style={{ color: '#ef4444', fontSize: 11, marginTop: 6 }}>{err}</div>}
    </div>
  );
}
