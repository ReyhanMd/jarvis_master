import React, { useState } from 'react';
import { Blueprint, MemoryRecord, SOURCE_COLOR, SOURCE_LABEL, api } from '../api';

interface Props {
  record: MemoryRecord;
  selected?: boolean;
  onSelect?: (id: string, checked: boolean) => void;
  onDeleted?: (id: string) => void;
  onDeleteRequest?: (id: string) => void;
  showCheckbox?: boolean;
  hasBlueprint?: boolean;
}

const MONO_F = 'ui-monospace,"SF Mono",Menlo,monospace';

export function MemoryCard({ record, selected, onSelect, onDeleted, onDeleteRequest, showCheckbox, hasBlueprint }: Props) {
  const [expanded, setExpanded]   = useState(false);
  const [content, setContent]     = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [deleting, setDeleting]   = useState(false);
  const [copied, setCopied]       = useState(false);
  const [blueprint, setBlueprint] = useState<Blueprint | null>(null);
  const [bpStatus, setBpStatus]   = useState<'idle' | 'loading' | 'pending' | 'ready' | 'none'>('idle');
  const [showPreview, setShowPreview] = useState(false);
  const hoverTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const color = SOURCE_COLOR[record.sourceApp] ?? '#6b7280';
  const label = SOURCE_LABEL[record.sourceApp] ?? record.sourceApp;

  async function handleExpand() {
    if (expanded) { setExpanded(false); return; }
    setExpanded(true);
    if (content === null) {
      setLoadingContent(true);
      try {
        const full = await api.getMemory(record.id);
        setContent(full.content ?? full.summary ?? '');
      } catch {
        setContent(record.summary);
      } finally {
        setLoadingContent(false);
      }
    }
    if (bpStatus === 'idle') {
      setBpStatus('loading');
      try {
        const bp = await api.getBlueprint(record.id);
        setBlueprint(bp);
        setBpStatus('ready');
      } catch (err) {
        // 404 means extraction is still running (or content was too thin).
        // Mark pending so the UI can offer a retry without spamming.
        const msg = (err as Error).message || '';
        setBpStatus(msg.includes('404') ? 'pending' : 'none');
      }
    }
  }

  async function refreshBlueprint() {
    setBpStatus('loading');
    try {
      const bp = await api.getBlueprint(record.id);
      setBlueprint(bp);
      setBpStatus('ready');
    } catch {
      setBpStatus('pending');
    }
  }

  async function handleDelete(e: React.MouseEvent) {
    e.stopPropagation();
    if (deleting) return;
    if (onDeleteRequest) {
      onDeleteRequest(record.id);
      return;
    }
    setDeleting(true);
    try {
      await api.deleteMemory(record.id);
      onDeleted?.(record.id);
    } catch {
      setDeleting(false);
    }
  }

  const ts = new Date(record.timestamp);
  const timeStr = ts.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

  // Derive health badge from state + eventType
  const stateBadge = (() => {
    const s = record.state;
    if (s === 'replayable') return { label: 'Replayable', color: 'var(--shail-success)', bg: 'rgba(95,210,154,0.1)' };
    if (s === 'trusted')    return { label: 'Trusted',    color: 'var(--shail-evidence)', bg: 'var(--shail-evidence-soft)' };
    if (s === 'partial' || s === 'incomplete') return { label: 'Partial', color: 'var(--shail-warning)', bg: 'rgba(224,182,90,0.1)' };
    if (record.eventType === 'ai_conversation') return { label: 'Conversation', color: 'var(--shail-evidence)', bg: 'var(--shail-evidence-soft)' };
    return null;
  })();

  return (
    <div
      style={{
        position: 'relative',
        background: selected ? 'var(--shail-bg-raised)' : 'var(--shail-bg-surface)',
        border: `1px solid ${selected ? 'var(--shail-border-strong)' : 'var(--shail-border-subtle)'}`,
        borderRadius: 10,
        padding: '14px 16px',
        cursor: 'pointer',
        transition: 'border-color 0.15s, background 0.15s',
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--shail-border-strong)';
        if (!expanded) {
          hoverTimer.current = setTimeout(() => setShowPreview(true), 400);
        }
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLDivElement).style.borderColor = selected ? 'var(--shail-border-strong)' : 'var(--shail-border-subtle)';
        setShowPreview(false);
        if (hoverTimer.current) clearTimeout(hoverTimer.current);
      }}
      onClick={handleExpand}
    >
      {/* Hover preview popover */}
      {showPreview && !expanded && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            right: 'calc(100% + 10px)',
            width: 240,
            zIndex: 50,
            background: 'var(--shail-bg-surface)',
            border: '1px solid var(--shail-border-strong)',
            borderRadius: 10,
            padding: '12px 14px',
            pointerEvents: 'none',
            boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          }}
          onClick={e => e.stopPropagation()}
        >
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--shail-text-primary)', marginBottom: 6, lineHeight: 1.35 }}>
            {record.title || record.sourceUrl}
          </div>
          {stateBadge && (
            <span style={{ fontSize: 9, color: stateBadge.color, background: stateBadge.bg, borderRadius: 4, padding: '1px 6px', marginBottom: 6, display: 'inline-block' }}>
              {stateBadge.label}
            </span>
          )}
          <div style={{ fontSize: 11, color: 'var(--shail-text-secondary)', lineHeight: 1.6 }}>
            {(record.summary || '').slice(0, 180)}{(record.summary || '').length > 180 ? '…' : ''}
          </div>
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        {showCheckbox && (
          <input
            type="checkbox"
            checked={!!selected}
            onChange={e => { e.stopPropagation(); onSelect?.(record.id, e.target.checked); }}
            onClick={e => e.stopPropagation()}
            style={{ marginTop: 2, accentColor: 'var(--shail-evidence)', flexShrink: 0 }}
          />
        )}

        {/* Source chip */}
        <span style={{
          fontSize: 11,
          fontWeight: 600,
          color,
          background: color + '18',
          border: `1px solid ${color}30`,
          borderRadius: 5,
          padding: '2px 8px',
          flexShrink: 0,
          marginTop: 1,
        }}>
          {label}
        </span>

        {/* State / health badge */}
        {stateBadge && (
          <span style={{
            fontSize: 10,
            fontWeight: 600,
            color: stateBadge.color,
            background: stateBadge.bg,
            border: `1px solid ${stateBadge.color}30`,
            borderRadius: 5,
            padding: '2px 8px',
            flexShrink: 0,
            marginTop: 1,
          }}>
            {stateBadge.label}
          </span>
        )}

        {/* Blueprint badge — visible only when extraction has produced a row */}
        {hasBlueprint && (
          <span
            title="Structured blueprint extracted from this memory"
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: '0.06em',
              color: 'var(--shail-evidence)',
              background: 'var(--shail-evidence-soft)',
              border: '1px solid rgba(138,138,212,0.2)',
              borderRadius: 5,
              padding: '2px 8px',
              flexShrink: 0,
              marginTop: 1,
              fontFamily: MONO_F,
            }}
          >
            BLUEPRINT
          </span>
        )}

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
            <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: 'var(--shail-text-primary)', lineHeight: 1.4, letterSpacing: '-0.01em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
              {record.title || record.sourceUrl}
            </p>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
              <span style={{ fontSize: 11, color: 'var(--shail-text-muted)' }}>{timeStr}</span>
              <button
                onClick={handleDelete}
                disabled={deleting}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--shail-border-strong)', fontSize: 13, padding: '0 2px', lineHeight: 1, transition: 'color 0.1s' }}
                onMouseEnter={e => (e.currentTarget.style.color = 'var(--shail-danger)')}
                onMouseLeave={e => (e.currentTarget.style.color = 'var(--shail-border-strong)')}
                title="Delete"
              >
                {deleting ? '…' : '×'}
              </button>
            </div>
          </div>

          {!expanded && (
            <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--shail-text-secondary)', lineHeight: 1.6, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
              {record.summary}
            </p>
          )}
        </div>
      </div>

      {/* Tags */}
      {record.tags?.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10, paddingLeft: showCheckbox ? 26 : 0 }}>
          {record.tags.map(t => (
            <span key={t} style={{ fontSize: 11, color: 'var(--shail-text-muted)', background: 'var(--shail-bg-raised)', border: '1px solid var(--shail-border-subtle)', borderRadius: 4, padding: '1px 7px' }}>
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Expanded content */}
      {expanded && (
        <div style={{ marginTop: 14, paddingLeft: showCheckbox ? 26 : 0 }} onClick={e => e.stopPropagation()}>
          {loadingContent ? (
            <div style={{ color: 'var(--shail-text-muted)', fontSize: 12 }}>Loading…</div>
          ) : (
            <pre style={{ margin: 0, fontSize: 12, color: 'var(--shail-text-secondary)', lineHeight: 1.65, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 320, overflowY: 'auto', fontFamily: 'inherit' }}>
              {content}
            </pre>
          )}

          {/* Blueprint — structured knowledge atoms */}
          <BlueprintPanel
            blueprint={blueprint}
            status={bpStatus}
            onRetry={refreshBlueprint}
          />

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 10 }}>
            <a
              href={record.sourceUrl}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: 11, color: 'var(--shail-text-muted)', textDecoration: 'none', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              onMouseEnter={e => (e.currentTarget.style.color = 'var(--shail-text-primary)')}
              onMouseLeave={e => (e.currentTarget.style.color = 'var(--shail-text-muted)')}
            >
              {record.sourceUrl} ↗
            </a>
            <button
              onClick={() => {
                const text = content || record.summary || record.title || '';
                navigator.clipboard.writeText(text);
                setCopied(true);
                setTimeout(() => setCopied(false), 1600);
              }}
              style={{
                padding: '4px 12px', fontSize: 11, borderRadius: 5, cursor: 'pointer',
                background: 'none', border: '1px solid var(--shail-border-subtle)', flexShrink: 0,
                color: copied ? 'var(--shail-success)' : 'var(--shail-text-muted)', fontFamily: MONO_F,
                transition: 'color 0.1s',
              }}
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}


// ── Blueprint panel ──────────────────────────────────────────────────────────

function BlueprintPanel({
  blueprint, status, onRetry,
}: {
  blueprint: Blueprint | null;
  status: 'idle' | 'loading' | 'pending' | 'ready' | 'none';
  onRetry: () => void;
}) {
  if (status === 'idle' || status === 'none') return null;

  const HEADER = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 14, marginBottom: 6 }}>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', color: 'var(--shail-evidence)', fontFamily: MONO_F }}>
        BLUEPRINT
      </span>
      <span style={{ flex: 1, height: 1, background: 'var(--shail-border-subtle)' }} />
      {status === 'pending' && (
        <button
          onClick={onRetry}
          style={{ fontSize: 10, color: 'var(--shail-text-muted)', background: 'none', border: '1px solid var(--shail-border-subtle)', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontFamily: MONO_F }}
        >
          retry
        </button>
      )}
    </div>
  );

  if (status === 'loading') {
    return (
      <>
        {HEADER}
        <div style={{ fontSize: 11, color: 'var(--shail-text-muted)' }}>Reading…</div>
      </>
    );
  }
  if (status === 'pending') {
    return (
      <>
        {HEADER}
        <div style={{ fontSize: 11, color: 'var(--shail-text-secondary)', lineHeight: 1.6 }}>
          Still extracting — blueprints generate in the background after capture.
          Tap retry in a moment.
        </div>
      </>
    );
  }
  if (!blueprint) return null;

  // decisions can be string | { statement: string; ... }
  const decisionTexts = blueprint.decisions.map(d =>
    typeof d === 'string' ? d : d.statement
  );

  const sections: { label: string; items: string[]; tone: string }[] = [
    { label: 'Decisions',      items: decisionTexts,              tone: 'var(--shail-evidence)' },
    { label: 'Open questions', items: blueprint.open_questions,   tone: 'var(--shail-warning)' },
    { label: 'Next actions',   items: blueprint.next_actions,     tone: 'var(--shail-success)' },
  ];

  return (
    <>
      {HEADER}
      {blueprint.summary && (
        <div style={{ fontSize: 12, color: 'var(--shail-text-secondary)', lineHeight: 1.6, marginBottom: 10 }}>
          {blueprint.summary}
        </div>
      )}
      {sections.map(s => s.items.length > 0 && (
        <div key={s.label} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 10, color: s.tone, fontFamily: MONO_F, letterSpacing: '0.06em', marginBottom: 4 }}>
            {s.label.toUpperCase()}
          </div>
          {s.items.map((item, i) => (
            <div key={i} style={{ fontSize: 12, color: 'var(--shail-text-secondary)', lineHeight: 1.6, marginBottom: 2, paddingLeft: 10, position: 'relative' }}>
              <span style={{ position: 'absolute', left: 0, color: s.tone }}>·</span>
              {item}
            </div>
          ))}
        </div>
      ))}
      {blueprint.questions_answered.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--shail-text-muted)', fontFamily: MONO_F, letterSpacing: '0.06em', marginBottom: 4 }}>
            Q&amp;A
          </div>
          {blueprint.questions_answered.map((qa, i) => (
            <div key={i} style={{ fontSize: 12, color: 'var(--shail-text-secondary)', lineHeight: 1.6, marginBottom: 6, paddingLeft: 10 }}>
              <span style={{ color: 'var(--shail-text-primary)' }}>Q.</span> {qa.q}
              {qa.a && <><br/><span style={{ color: 'var(--shail-text-muted)' }}>A.</span> {qa.a}</>}
            </div>
          ))}
        </div>
      )}
      {blueprint.key_entities.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 4 }}>
          {blueprint.key_entities.map(e => (
            <span key={e} style={{ fontSize: 10, color: 'var(--shail-text-muted)', background: 'var(--shail-bg-raised)', border: '1px solid var(--shail-border-subtle)', borderRadius: 4, padding: '2px 8px', fontFamily: MONO_F }}>
              {e}
            </span>
          ))}
        </div>
      )}
    </>
  );
}
