/**
 * ChatRenderer — lightweight markdown + citation renderer for assistant messages.
 *
 * Supports: code blocks, inline code, bold, headings (##), bullet lists (-),
 * simple pipe tables, bare URLs, line breaks, and {{cite:...}} tokens.
 */

import React from 'react';
import { CitationLink } from './CitationLink';
import type { StoredCitation } from '../api';

const MONO = 'ui-monospace,"SF Mono",Menlo,monospace';
const TOKEN_RE = /\{\{cite:(memory|chat|web|mcp|local_file):([^\}]+)\}\}/g;

// Build citation lookup (same approach as renderWithCitations)
function buildLookup(citations: StoredCitation[]) {
  const memById  = new Map<string, StoredCitation>();
  const chatById = new Map<string, StoredCitation>();
  const webByIdx = new Map<string, StoredCitation>();
  const mcpByKey = new Map<string, StoredCitation>();
  const localFileById = new Map<string, StoredCitation>();
  for (const c of citations) {
    if (c.type === 'memory')    memById.set(c.id, c);
    else if (c.type === 'chat') chatById.set(c.id, c);
    else if (c.type === 'web')  webByIdx.set(c.id, c);
    else if (c.type === 'mcp')  mcpByKey.set(`${c.provider}:${c.id}`, c);
    else if (c.type === 'local_file') localFileById.set(c.id, c);
  }
  return { memById, chatById, webByIdx, mcpByKey, localFileById };
}

function resolveCite(
  kind: string, payload: string,
  lookup: ReturnType<typeof buildLookup>,
): StoredCitation | undefined {
  if (kind === 'memory') return lookup.memById.get(payload);
  if (kind === 'chat')   return lookup.chatById.get(payload);
  if (kind === 'web')    return lookup.webByIdx.get(payload);
  if (kind === 'mcp')    return lookup.mcpByKey.get(payload);
  if (kind === 'local_file') return lookup.localFileById.get(payload);
}

// ── Inline renderer: bold + inline code + bare URLs + citation tokens ─────────

function renderInline(
  text: string,
  lookup: ReturnType<typeof buildLookup>,
  keyBase: { n: number },
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let i = 0;

  while (i < text.length) {
    // Citation token {{cite:...}}
    if (text.startsWith('{{cite:', i)) {
      TOKEN_RE.lastIndex = i;
      const m = TOKEN_RE.exec(text);
      if (m && m.index === i) {
        const c = resolveCite(m[1], m[2], lookup);
        if (c) out.push(<CitationLink key={keyBase.n++} citation={c} />);
        i += m[0].length;
        continue;
      }
    }

    // ** bold **
    if (text.startsWith('**', i)) {
      const end = text.indexOf('**', i + 2);
      if (end !== -1) {
        out.push(
          <strong key={keyBase.n++} style={{ color: 'var(--shail-text-primary)', fontWeight: 600 }}>
            {text.slice(i + 2, end)}
          </strong>
        );
        i = end + 2;
        continue;
      }
    }

    // `inline code`
    if (text[i] === '`') {
      const end = text.indexOf('`', i + 1);
      if (end !== -1) {
        out.push(
          <code key={keyBase.n++} style={{
            fontFamily: MONO,
            fontSize: '0.88em',
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid var(--shail-border-subtle)',
            borderRadius: 4,
            padding: '1px 5px',
            color: 'var(--shail-accent, #7aa6e0)',
          }}>
            {text.slice(i + 1, end)}
          </code>
        );
        i = end + 1;
        continue;
      }
    }

    // Bare URL http(s)://...
    if (text.startsWith('http://', i) || text.startsWith('https://', i)) {
      let end = i;
      while (end < text.length && !/\s/.test(text[end])) end++;
      const url = text.slice(i, end);
      out.push(
        <a key={keyBase.n++} href={url} target="_blank" rel="noreferrer" style={{
          color: 'var(--shail-accent, #7aa6e0)',
          textDecoration: 'none',
          borderBottom: '1px solid rgba(122,166,224,0.4)',
        }}>
          {url}
        </a>
      );
      i = end;
      continue;
    }

    // Accumulate plain text
    let j = i + 1;
    while (j < text.length) {
      if (text[j] === '`' || text[j] === '*' || text.startsWith('{{cite:', j) ||
          text.startsWith('http://', j) || text.startsWith('https://', j)) break;
      j++;
    }
    out.push(<span key={keyBase.n++}>{text.slice(i, j)}</span>);
    i = j;
  }

  return out;
}

// ── Block renderer ─────────────────────────────────────────────────────────────

function renderBlocks(
  text: string,
  lookup: ReturnType<typeof buildLookup>,
): React.ReactNode[] {
  const blocks: React.ReactNode[] = [];
  const keyBase = { n: 0 };
  const lines = text.split('\n');
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // ``` code block ```
    if (line.trimStart().startsWith('```')) {
      const lang = line.trimStart().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push(
        <pre key={keyBase.n++} style={{
          margin: '10px 0',
          padding: '12px 14px',
          background: 'rgba(0,0,0,0.4)',
          border: '1px solid var(--shail-border-subtle)',
          borderRadius: 8,
          fontSize: 12,
          color: 'var(--shail-text-secondary)',
          overflowX: 'auto',
          fontFamily: MONO,
          lineHeight: 1.55,
        }}>
          {lang && (
            <span style={{ display: 'block', fontSize: 10, color: 'var(--shail-text-muted)', marginBottom: 8, letterSpacing: '0.06em' }}>
              {lang}
            </span>
          )}
          {codeLines.join('\n')}
        </pre>
      );
      continue;
    }

    // ## heading
    const headingMatch = line.match(/^(#{1,3})\s+(.*)/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const sz = level === 1 ? 18 : level === 2 ? 15 : 13;
      blocks.push(
        <div key={keyBase.n++} style={{
          fontSize: sz,
          fontWeight: 600,
          color: 'var(--shail-text-primary)',
          margin: `${level === 1 ? 16 : 10}px 0 4px`,
          letterSpacing: '-0.02em',
          lineHeight: 1.3,
        }}>
          {renderInline(headingMatch[2], lookup, keyBase)}
        </div>
      );
      i++;
      continue;
    }

    // Bullet list: lines starting with - or *
    if (/^[\-\*] /.test(line)) {
      const listItems: string[] = [];
      while (i < lines.length && /^[\-\*] /.test(lines[i])) {
        listItems.push(lines[i].slice(2));
        i++;
      }
      blocks.push(
        <ul key={keyBase.n++} style={{ margin: '6px 0', paddingLeft: 18, listStyle: 'none' }}>
          {listItems.map((item, idx) => (
            <li key={idx} style={{ fontSize: 14, color: 'var(--shail-text-primary)', lineHeight: 1.65, marginBottom: 3, position: 'relative', paddingLeft: 12 }}>
              <span style={{ position: 'absolute', left: 0, color: 'var(--shail-evidence, #8a8ad4)' }}>·</span>
              {renderInline(item, lookup, keyBase)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // Simple pipe table: line contains | separators
    if (line.includes('|') && line.trim().startsWith('|')) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i]);
        i++;
      }
      // Filter out separator rows (---|---|)
      const rows = tableLines.filter(l => !/^\s*\|[\s\-|:]+\|\s*$/.test(l));
      if (rows.length > 0) {
        const [header, ...body] = rows;
        const parseCells = (row: string) =>
          row.split('|').slice(1, -1).map(c => c.trim());
        const headerCells = parseCells(header);
        blocks.push(
          <div key={keyBase.n++} style={{ overflowX: 'auto', margin: '8px 0' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  {headerCells.map((cell, ci) => (
                    <th key={ci} style={{
                      padding: '6px 10px', textAlign: 'left', fontWeight: 600,
                      color: 'var(--shail-text-primary)',
                      borderBottom: '1px solid var(--shail-border-strong)',
                      fontSize: 11, letterSpacing: '0.04em',
                    }}>
                      {renderInline(cell, lookup, keyBase)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.map((row, ri) => (
                  <tr key={ri} style={{ background: ri % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}>
                    {parseCells(row).map((cell, ci) => (
                      <td key={ci} style={{
                        padding: '6px 10px',
                        color: 'var(--shail-text-secondary)',
                        borderBottom: '1px solid var(--shail-border-subtle)',
                      }}>
                        {renderInline(cell, lookup, keyBase)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      continue;
    }

    // Blank line → spacer
    if (line.trim() === '') {
      blocks.push(<div key={keyBase.n++} style={{ height: 8 }} />);
      i++;
      continue;
    }

    // Regular paragraph line
    blocks.push(
      <div key={keyBase.n++} style={{ lineHeight: 1.7, color: 'var(--shail-text-primary)' }}>
        {renderInline(line, lookup, keyBase)}
      </div>
    );
    i++;
  }

  return blocks;
}

// ── Public component ──────────────────────────────────────────────────────────

interface ChatRendererProps {
  content: string;
  citations: StoredCitation[];
  fontSize?: number;
}

export function ChatRenderer({ content, citations, fontSize = 14 }: ChatRendererProps) {
  const lookup = buildLookup(citations);
  const blocks = renderBlocks(content, lookup);

  return (
    <div style={{ fontSize, wordBreak: 'break-word' }}>
      {blocks}
    </div>
  );
}
