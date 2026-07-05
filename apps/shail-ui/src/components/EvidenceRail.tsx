import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, StoredCitation } from '../api';
import { useUIStore } from '../stores/ui';
import { ConfidenceBadge, EmptyState } from './primitives';

const RAIL_WIDTH = 340;

// Type-specific accent colors for left border
const TYPE_ACCENT: Record<string, string> = {
  memory:    'var(--shail-evidence)',
  web:       'var(--shail-accent, #7aa6e0)',
  mcp:       'var(--shail-success)',
  chat:      'var(--shail-warning)',
  past_chat: 'var(--shail-warning)',
  local_file:'var(--shail-accent, #7aa6e0)',
};

function CitationCard({ cite, onOpenInspector, isNew }: {
  cite: StoredCitation;
  onOpenInspector: (id: string) => void;
  isNew?: boolean;
}) {
  const memQuery = useQuery({
    queryKey: ['memory', 'detail', cite.type === 'memory' ? cite.id : null],
    queryFn: () => api.getMemory((cite as { id: string }).id),
    enabled: cite.type === 'memory',
    staleTime: 5 * 60_000,
  });

  const isMemory = cite.type === 'memory';
  const isLocalFile = cite.type === 'local_file';
  const title = (cite as any).title ?? 'Untitled';
  const score = (cite as { score?: number }).score;
  const snippet = (cite as { snippet?: string }).snippet ?? memQuery.data?.summary ?? '';
  const accent = TYPE_ACCENT[cite.type] ?? 'var(--shail-border-strong)';

  return (
    <>
      {isNew && (
        <style>{`
          @keyframes shailCitationPulse {
            0%   { box-shadow: 0 0 0 0 var(--shail-evidence); opacity: 0.6; }
            60%  { box-shadow: 0 0 0 6px transparent; opacity: 1; }
            100% { box-shadow: 0 0 0 0 transparent; opacity: 1; }
          }
          .shail-cite-new { animation: shailCitationPulse 0.6s ease both; }
        `}</style>
      )}
      <button
        onClick={() => {
          if (isMemory) onOpenInspector((cite as { id: string }).id);
          else if (isLocalFile) api.pathIndexOpen((cite as { path: string }).path).catch(() => {});
        }}
        className={isNew ? 'shail-cite-new' : ''}
        style={{
          width: '100%', textAlign: 'left',
          background: 'var(--shail-bg-raised)',
          border: '1px solid var(--shail-border-subtle)',
          borderLeft: `3px solid ${accent}`,
          borderRadius: 8, padding: '10px 12px',
          cursor: isMemory || isLocalFile ? 'pointer' : 'default',
          display: 'flex', flexDirection: 'column', gap: 5,
          transition: 'border-color 0.12s',
        }}
        onMouseEnter={e => { if (isMemory || isLocalFile) (e.currentTarget as HTMLElement).style.borderColor = 'var(--shail-border-strong)'; }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--shail-border-subtle)'; }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'space-between' }}>
          <span style={{
            fontSize: 9, fontWeight: 700,
            color: accent,
            textTransform: 'uppercase', letterSpacing: '0.07em',
          }}>
            {cite.type}
          </span>
          {typeof score === 'number' && <ConfidenceBadge value={score} />}
        </div>
        <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--shail-text-primary)', lineHeight: 1.4 }}>
          {title}
        </div>
        {snippet && (
          <div style={{
            fontSize: 11, color: 'var(--shail-text-secondary)', lineHeight: 1.55,
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }}>
            {snippet}
          </div>
        )}
        {isMemory && (
          <div style={{ fontSize: 10, color: 'var(--shail-text-muted)', marginTop: 1 }}>
            {memQuery.data?.sourceApp ?? '…'} · inspect →
          </div>
        )}
        {isLocalFile && (
          <div style={{ fontSize: 10, color: 'var(--shail-text-muted)', marginTop: 1 }}>
            local file · reveal →
          </div>
        )}
      </button>
    </>
  );
}

export function EvidenceRail() {
  const open = useUIStore(s => s.evidenceRailOpen);
  const setOpen = useUIStore(s => s.setEvidenceRailOpen);
  const cites = useUIStore(s => s.lastAnswerCitations);
  const openInspector = useUIStore(s => s.openInspector);

  // Track which citations are newly arrived for pulse animation
  const [prevCount, setPrevCount] = React.useState(cites.length);
  const newStartIdx = prevCount < cites.length ? prevCount : cites.length;
  React.useEffect(() => { setPrevCount(cites.length); }, [cites.length]);

  if (!open) return null;

  return (
    <aside
      style={{
        width: RAIL_WIDTH, flexShrink: 0,
        height: '100%', overflowY: 'auto',
        background: 'var(--shail-bg-surface)',
        borderLeft: '1px solid var(--shail-border-subtle)',
        padding: '20px 16px',
        display: 'flex', flexDirection: 'column', gap: 10,
      }}
      aria-label="Sources"
    >
      {/* Header with count badge */}
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <h2 style={{
            margin: 0, fontSize: 11, fontWeight: 700,
            color: 'var(--shail-text-secondary)',
            textTransform: 'uppercase', letterSpacing: '0.08em',
          }}>
            Sources
          </h2>
          {cites.length > 0 && (
            <span style={{
              fontSize: 10, fontWeight: 600,
              color: 'var(--shail-evidence)',
              background: 'var(--shail-evidence-soft)',
              border: '1px solid rgba(138,138,212,0.2)',
              borderRadius: 10,
              padding: '1px 6px',
            }}>
              {cites.length}
            </span>
          )}
        </div>
        <button
          onClick={() => setOpen(false)}
          aria-label="Close sources"
          style={{
            background: 'none', border: 'none',
            color: 'var(--shail-text-muted)', cursor: 'pointer',
            fontSize: 14, lineHeight: 1, opacity: 0.6,
            transition: 'opacity 0.1s',
          }}
          onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
          onMouseLeave={e => (e.currentTarget.style.opacity = '0.6')}
        >
          ✕
        </button>
      </header>

      {cites.length === 0 ? (
        <EmptyState
          title="No sources yet"
          hint="Ask a question — sources used to answer will appear here."
        />
      ) : (
        cites.map((c, i) => (
          <CitationCard
            key={`${c.type}:${(c as { id?: string }).id ?? i}`}
            cite={c}
            onOpenInspector={openInspector}
            isNew={i >= newStartIdx}
          />
        ))
      )}
    </aside>
  );
}
