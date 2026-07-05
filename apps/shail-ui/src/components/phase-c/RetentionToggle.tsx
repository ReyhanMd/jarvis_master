import { useEffect, useState } from 'react';
import { api } from '../../api';

type Props = {
  sessionId: string;
  initialCaptureEnabled?: boolean;
  initialRetentionPolicy?: 'keep_raw' | 'blueprint_only' | 'transcript_deleted';
};

/**
 * Sprint 4: capture + retention controls for a session.
 *
 * Continue-capture toggle: if off, future turns won't be indexed.
 * Retention policy selector: keep_raw (default) | blueprint_only.
 * 'transcript_deleted' is set by redact action — not user-selectable here.
 *
 * NOT yet browser-smoke tested.
 */
export function RetentionToggle({
  sessionId,
  initialCaptureEnabled = true,
  initialRetentionPolicy = 'keep_raw',
}: Props) {
  const [captureEnabled, setCaptureEnabled] = useState(initialCaptureEnabled);
  const [policy, setPolicy] = useState(initialRetentionPolicy);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save(next: { capture_enabled?: boolean; retention_policy?: string }) {
    setSaving(true);
    setErr(null);
    try {
      await api.patchChatSession(sessionId, next);
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function onRedact() {
    if (!confirm('Delete raw transcript? Blueprint will be preserved.')) return;
    try {
      await api.redactSession(sessionId);
      setPolicy('transcript_deleted');
    } catch (e: any) {
      setErr(String(e));
    }
  }

  return (
    <div style={{
      padding: 10, background: '#0d0d0d', border: '1px solid #1e1e1e',
      borderRadius: 6, color: '#bbb', fontSize: 12,
    }}>
      <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
        <input
          type="checkbox"
          checked={captureEnabled}
          disabled={saving}
          style={{ accentColor: '#22c55e' }}
          onChange={(e) => {
            setCaptureEnabled(e.target.checked);
            save({ capture_enabled: e.target.checked });
          }}
        />
        Capture future turns (per-turn live indexing)
      </label>
      <div style={{ marginTop: 10 }}>
        <label style={{ display: 'block', fontSize: 11, color: '#666', marginBottom: 4 }}>
          RETENTION POLICY
        </label>
        <select
          value={policy}
          disabled={saving || policy === 'transcript_deleted'}
          style={{
            padding: '5px 8px', fontSize: 12, background: '#1a1a1a',
            color: '#fff', border: '1px solid #262626', borderRadius: 5,
          }}
          onChange={(e) => {
            const v = e.target.value as typeof policy;
            setPolicy(v);
            save({ retention_policy: v });
          }}
        >
          <option value="keep_raw">Keep raw transcript</option>
          <option value="blueprint_only">Blueprint only (no new raw retention)</option>
          {policy === 'transcript_deleted' && (
            <option value="transcript_deleted">Transcript deleted</option>
          )}
        </select>
      </div>
      {policy !== 'transcript_deleted' && (
        <button
          onClick={onRedact}
          disabled={saving}
          style={{
            marginTop: 10, padding: '5px 12px', fontSize: 11,
            background: '#1a1a1a', border: '1px solid #3a1010', color: '#ef4444',
            borderRadius: 5, cursor: 'pointer',
          }}
        >
          Redact raw transcript (keeps blueprint)
        </button>
      )}
      {err && <div style={{ color: '#ef4444', fontSize: 11, marginTop: 6 }}>{err}</div>}
    </div>
  );
}
