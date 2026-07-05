/**
 * CitationLink — renders a structured citation token as a clickable icon
 * with a hover-preview widget.
 *
 * Citation token grammar emitted by the model:
 *   {{cite:memory:<id>}}
 *   {{cite:chat:<message_id>}}
 *   {{cite:web:<index>}}                       (1-based; resolves via web list)
 *   {{cite:mcp:<provider>:<id>}}
 *   {{cite:local_file:<path_index_id>}}
 *
 * The renderer runs over the assistant message text, replacing every match
 * with a small <CitationLink>. Unknown / unresolved tokens are dropped from
 * output rather than rendered as broken stubs.
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { StoredCitation } from '../api';

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

interface Props {
  citation: StoredCitation;
}

const SOURCE_LABEL: Record<string, string> = {
  memory: 'Memory',
  chat:   'Past chat',
  web:    'Web',
  drive:  'Google Drive',
  notion: 'Notion',
  github: 'GitHub',
  gmail:  'Gmail',
  local_file: 'Local file',
};

const SOURCE_COLOR: Record<string, string> = {
  memory: '#8ab4f8',
  chat:   '#22c55e',
  web:    '#f59e0b',
  drive:  '#34a853',
  notion: '#ffffff',
  github: '#c9d1d9',
  gmail:  '#ea4335',
  local_file: '#7aa6e0',
};

export function CitationLink({ citation }: Props) {
  const [hover, setHover] = useState(false);
  const navigate = useNavigate();

  const meta = describe(citation);
  const tone = SOURCE_COLOR[meta.kind] ?? '#aaa';

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (meta.kind === 'memory') {
      navigate(`/memories?open=${citation.id}`);
    } else if (meta.kind === 'chat' && citation.type === 'chat') {
      navigate(`/chat/${citation.session_id}`);
    } else if (meta.kind === 'web' && citation.type === 'web') {
      window.open(citation.url, '_blank', 'noreferrer');
    } else if (citation.type === 'mcp') {
      if (citation.url) window.open(citation.url, '_blank', 'noreferrer');
      else navigate(`/connections?source=${citation.provider}&doc=${citation.id}`);
    } else if (citation.type === 'local_file') {
      fetch(`http://localhost:8000/path-index/open?path=${encodeURIComponent(citation.path)}`, {
        method: 'POST',
      }).catch(() => {});
    }
  };

  return (
    <span
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={handleClick}
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 18, height: 18,
        marginLeft: 2, marginRight: 2,
        verticalAlign: '-2px',
        background: '#0d0d0d',
        border: `1px solid ${tone}40`,
        borderRadius: 4,
        color: tone,
        fontSize: 10,
        fontFamily: MONO,
        cursor: 'pointer',
        transition: 'background 0.1s, border-color 0.1s',
      }}
      title={`${meta.label} — click to open`}
    >
      ↗
      {hover && (
        <span
          style={{
            position: 'absolute',
            bottom: 'calc(100% + 6px)',
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 50,
            width: 240,
            padding: '10px 12px',
            background: '#0a0a0a',
            border: `1px solid ${tone}40`,
            borderRadius: 8,
            boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
            cursor: 'default',
            pointerEvents: 'none',
            textAlign: 'left',
          }}
        >
          <div style={{ fontSize: 9, color: tone, fontFamily: MONO, letterSpacing: '0.08em', marginBottom: 4 }}>
            {meta.label.toUpperCase()}
          </div>
          <div style={{ fontSize: 12, color: '#fff', lineHeight: 1.4, marginBottom: 4, fontWeight: 500 }}>
            {meta.title}
          </div>
          <div style={{ fontSize: 11, color: '#888', lineHeight: 1.5, whiteSpace: 'normal' }}>
            {meta.snippet || '(no preview available)'}
          </div>
        </span>
      )}
    </span>
  );
}

function describe(c: StoredCitation): { kind: string; label: string; title: string; snippet: string } {
  if (c.type === 'memory') {
    return { kind: 'memory', label: SOURCE_LABEL.memory, title: c.title, snippet: '' };
  }
  if (c.type === 'chat') {
    return { kind: 'chat', label: SOURCE_LABEL.chat, title: c.title, snippet: c.snippet || '' };
  }
  if (c.type === 'web') {
    return { kind: 'web', label: SOURCE_LABEL.web, title: c.title, snippet: c.snippet || c.url };
  }
  if (c.type === 'local_file') {
    return {
      kind: 'local_file',
      label: SOURCE_LABEL.local_file,
      title: c.title,
      snippet: c.snippet || c.path,
    };
  }
  // mcp
  return {
    kind: c.provider,
    label: SOURCE_LABEL[c.provider] || c.provider,
    title: c.title,
    snippet: c.snippet || '',
  };
}


// ── Token-string renderer ────────────────────────────────────────────────────

const TOKEN_RE = /\{\{cite:(memory|chat|web|mcp|local_file):([^\}]+)\}\}/g;

/**
 * Render an assistant message string, replacing every citation token with a
 * <CitationLink> component. Tokens whose IDs aren't in the available citations
 * list are stripped from output (better than showing a broken link).
 */
export function renderWithCitations(
  text: string,
  citations: StoredCitation[],
): React.ReactNode[] {
  if (!text) return [];

  // Build lookup tables for O(1) resolve
  const memById:   Map<string, StoredCitation> = new Map();
  const chatById:  Map<string, StoredCitation> = new Map();
  const webByIdx:  Map<string, StoredCitation> = new Map();
  const mcpByKey:  Map<string, StoredCitation> = new Map(); // key: "provider:id"
  const localFileById: Map<string, StoredCitation> = new Map();
  for (const c of citations) {
    if (c.type === 'memory') memById.set(c.id, c);
    else if (c.type === 'chat') chatById.set(c.id, c);
    else if (c.type === 'web') webByIdx.set(c.id, c);
    else if (c.type === 'mcp') mcpByKey.set(`${c.provider}:${c.id}`, c);
    else if (c.type === 'local_file') localFileById.set(c.id, c);
  }

  const out: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  let key = 0;

  while ((match = TOKEN_RE.exec(text)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    if (start > lastIndex) out.push(text.slice(lastIndex, start));

    const kind = match[1];
    const payload = match[2];
    let resolved: StoredCitation | undefined;
    if (kind === 'memory') resolved = memById.get(payload);
    else if (kind === 'chat') resolved = chatById.get(payload);
    else if (kind === 'web') resolved = webByIdx.get(payload);
    else if (kind === 'mcp') {
      // payload is "<provider>:<id>"
      resolved = mcpByKey.get(payload);
    } else if (kind === 'local_file') {
      resolved = localFileById.get(payload);
    }

    if (resolved) {
      out.push(<CitationLink key={`c${key++}`} citation={resolved} />);
    }
    // else: drop the token silently — model hallucinated an id

    lastIndex = end;
  }
  if (lastIndex < text.length) out.push(text.slice(lastIndex));
  return out;
}
