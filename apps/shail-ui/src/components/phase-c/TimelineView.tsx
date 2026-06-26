import { useEffect, useState } from 'react';
import { api } from '../../api';

type Timeline = Awaited<ReturnType<typeof api.getSessionTimeline>>;

/**
 * Sprint 4: read-only timeline of a session.
 *
 * Shows paired (user, assistant) turns + session blueprint atoms.
 * If transcript was redacted (retention.policy === 'transcript_deleted'),
 * shows blueprint only with a notice.
 *
 * NOT yet browser-smoke tested.
 */
export function TimelineView({ sessionId }: { sessionId: string }) {
  const [tl, setTl] = useState<Timeline | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.getSessionTimeline(sessionId).then(setTl).catch((e) => setErr(String(e)));
  }, [sessionId]);

  if (err) return <div style={{ color: '#c00' }}>Failed to load timeline: {err}</div>;
  if (!tl) return <div>Loading…</div>;

  const redacted = !tl.retention.raw_available;

  return (
    <div style={{ color: '#bbb', fontSize: 13 }}>
      <div style={{ fontSize: 11, color: '#555', marginBottom: 12, fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace' }}>
        {tl.session.created_at} · Retention: {tl.session.retention_policy}
        {tl.session.backfilled_at && ` · Backfilled ${tl.session.backfilled_at}`}
      </div>

      {redacted && (
        <div style={{
          padding: '8px 10px', background: '#1f1a0a', border: '1px solid #3a2a0a',
          borderRadius: 4, marginBottom: 12, fontSize: 12, color: '#fbbf24',
        }}>
          Raw transcript was redacted. Showing blueprint only.
        </div>
      )}

      {!redacted && tl.turns.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: '#555', marginBottom: 6, fontFamily: 'ui-monospace, monospace', letterSpacing: '0.1em' }}>
            TURNS ({tl.turns.length})
          </div>
          {tl.turns.map((t: any, i: number) => (
            <div
              key={i}
              style={{ borderLeft: '2px solid #262626', padding: '6px 12px', marginBottom: 10 }}
            >
              <div style={{ fontWeight: 500, fontSize: 12, color: '#ddd' }}>
                {t.user_msg?.content}
              </div>
              {t.asst_msg && (
                <div style={{ marginTop: 4, fontSize: 12, color: '#888' }}>
                  {t.asst_msg.content}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {tl.blueprint && (
        <div>
          <div style={{ fontSize: 11, color: '#555', marginBottom: 6, fontFamily: 'ui-monospace, monospace', letterSpacing: '0.1em' }}>
            BLUEPRINT
          </div>
          <div style={{ marginBottom: 8, color: '#ddd' }}>
            <strong>Summary:</strong> {tl.blueprint.summary}
          </div>
          {tl.blueprint.key_entities?.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <strong style={{ color: '#888' }}>Entities:</strong> {tl.blueprint.key_entities.join(', ')}
            </div>
          )}
          {tl.blueprint.decisions?.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <strong style={{ color: '#888' }}>Decisions:</strong>
              <ul style={{ margin: '4px 0', paddingLeft: 20 }}>
                {tl.blueprint.decisions.map((d: any, i: number) => (
                  <li key={i}>
                    {d.statement} <em style={{ color: '#666' }}>({d.confidence})</em>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {tl.blueprint.next_actions?.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <strong style={{ color: '#888' }}>Next actions:</strong>
              <ul style={{ margin: '4px 0', paddingLeft: 20 }}>
                {tl.blueprint.next_actions.map((a: string, i: number) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
