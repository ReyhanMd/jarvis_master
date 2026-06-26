import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactDOM from 'react-dom/client';
import {
  api, getApiKey, cleanContentForDisplay, formatFullInject,
  userFacingError, RouteCluster, SuggestedMemory, AscentSummary,
  SystemStatus,
} from '../../src/lib/api';
import { timeAgo, getSourceMeta } from '../../src/lib/utils';
import type { MemoryRecord, SourceApp } from '../../src/types/contracts';
import './style.css';

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const BASE = 'http://localhost:8000';
const CHAT_HISTORY_KEY = 'shail_sidepanel_chat_history';
const CHAT_SESSION_KEY = 'shail_sidepanel_session_id';

const SOURCE_APPS: SourceApp[] = ['chatgpt', 'claude', 'gemini', 'perplexity', 'grok', 'web'];
const SOURCE_LABEL: Record<SourceApp, string> = { chatgpt: 'ChatGPT', claude: 'Claude', gemini: 'Gemini', perplexity: 'Perplexity', grok: 'Grok', web: 'Web' };

// Source → colour mapping for suggestion cards
const SOURCE_COLORS: Record<string, string> = {
  chatgpt: '#10a37f', claude: '#cc785c', gemini: '#4285f4',
  perplexity: '#22c55e', grok: '#e5e5e5', web: '#8b5cf6', default: '#6b7280',
};

// ─── Inject helper ────────────────────────────────────────────────────────────

function injectIntoPage(text: string): boolean {
  const h = location.hostname;
  let el: HTMLElement | null = null;
  if (h.includes('chatgpt.com') || h.includes('openai.com')) el = document.querySelector<HTMLElement>('#prompt-textarea');
  else if (h.includes('claude.ai')) el = document.querySelector<HTMLElement>('.ProseMirror[contenteditable="true"]') ?? document.querySelector<HTMLElement>('[contenteditable="true"][data-placeholder]');
  else if (h.includes('gemini.google.com')) el = document.querySelector<HTMLElement>('.ql-editor[contenteditable="true"]');
  else if (h.includes('perplexity.ai')) el = document.querySelector<HTMLElement>('textarea[placeholder]') ?? document.querySelector<HTMLElement>('textarea');
  if (!el) el = document.querySelector<HTMLElement>('textarea:not([style*="display:none"])') ?? document.querySelector<HTMLElement>('[contenteditable="true"]');
  if (!el) return false;
  el.focus();
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    const current = (el as HTMLTextAreaElement).value;
    const next = current ? `${current}\n${text}` : text;
    if (nativeSetter) nativeSetter.call(el, next);
    else (el as HTMLTextAreaElement).value = next;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  } else if (el.isContentEditable) {
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel?.removeAllRanges();
    sel?.addRange(range);
    document.execCommand('insertText', false, (el.textContent?.trim() ? '\n' : '') + text);
  }
  return true;
}

// ─── Inject executor (from sidepanel → content script) ────────────────────────

async function executeInject(text: string, apiKey: string | null, setMsg: (m: string) => void) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) { setMsg('No active tab'); return; }
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: injectIntoPage, args: [text] });
    setMsg('Injected ↗');
  } catch { setMsg('Inject failed'); }
  setTimeout(() => setMsg(''), 2200);
}

// ─── Relevance dot ────────────────────────────────────────────────────────────

function RelevanceDot({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, Math.round(score * 100)));
  const color = pct >= 70 ? '#22c55e' : pct >= 45 ? '#f59e0b' : '#6b7280';
  return (
    <span title={`Relevance ${pct}%`} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, display: 'inline-block', flexShrink: 0 }} />
      <span style={{ fontSize: 9, color, fontFamily: MONO }}>{pct}%</span>
    </span>
  );
}

// ─── Suggestion card ──────────────────────────────────────────────────────────

function SuggestionCard({
  item, apiKey, onInject,
}: {
  item: SuggestedMemory;
  apiKey: string | null;
  onInject: (msg: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [injecting, setInjecting] = useState(false);
  const srcColor = SOURCE_COLORS[item.sourceApp] ?? SOURCE_COLORS.default;

  const handleInject = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setInjecting(true);
    const text = `--- Memory: ${item.title} ---\n\n${item.summary}\n\n---`;
    await executeInject(text, apiKey, onInject);
    setInjecting(false);
  };

  return (
    <div
      style={{
        background: expanded ? '#111' : '#0a0a0a',
        border: `1px solid ${expanded ? '#2a2a2a' : '#1a1a1a'}`,
        borderRadius: 8,
        overflow: 'hidden',
        transition: 'all 0.15s ease',
      }}
    >
      {/* Card header — always visible */}
      <div
        onClick={() => setExpanded(p => !p)}
        style={{ padding: '9px 12px', cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'flex-start' }}
      >
        {/* Source dot */}
        <span style={{
          marginTop: 2, width: 7, height: 7, borderRadius: '50%',
          background: srcColor, flexShrink: 0, display: 'inline-block',
        }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#e5e5e5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {item.title || 'Untitled'}
          </div>
          <div style={{ fontSize: 9, color: '#555', fontFamily: MONO, marginTop: 2 }}>
            {item.sourceApp.toUpperCase()} · {item.deliverable_hint}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
          <RelevanceDot score={item.relevance_score} />
          <span style={{ fontSize: 9, color: '#444', fontFamily: MONO }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div style={{ borderTop: '1px solid #1a1a1a' }}>
          <div style={{ padding: '8px 12px', fontSize: 11, color: '#999', lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 140, overflowY: 'auto' }}>
            {cleanContentForDisplay(item.summary)}
          </div>
          <div style={{ padding: '6px 12px 9px', display: 'flex', gap: 6 }}>
            <button
              onClick={handleInject}
              disabled={injecting}
              style={{
                flex: 1, padding: '5px 0', fontSize: 10, fontWeight: 700,
                background: injecting ? '#1a1a1a' : 'rgba(34,197,94,0.12)',
                border: '1px solid rgba(34,197,94,0.3)', borderRadius: 5,
                color: injecting ? '#666' : '#22c55e', cursor: injecting ? 'wait' : 'pointer',
                transition: 'all 0.12s',
              }}
            >
              {injecting ? 'Injecting…' : 'Inject ↗'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Ascent pinned widget ──────────────────────────────────────────────────────

function AscentWidget({
  ascent, apiKey, onInject,
}: {
  ascent: AscentSummary;
  apiKey: string | null;
  onInject: (msg: string) => void;
}) {
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<SuggestedMemory[]>([]);
  const [sugLoading, setSugLoading] = useState(false);
  const [sugError, setSugError] = useState('');
  const loadedRef = useRef(false);

  const progressPct = Math.round((ascent.progress ?? 0) * 100);
  const isDone = ascent.status === 'completed';

  const toggleSuggestions = async () => {
    const next = !suggestionsOpen;
    setSuggestionsOpen(next);
    if (next && !loadedRef.current) {
      setSugLoading(true);
      setSugError('');
      try {
        const res = await api.getAscentSuggestions(ascent.id, 8);
        setSuggestions(res.suggestions);
        loadedRef.current = true;
      } catch (err) {
        setSugError(userFacingError(err));
      }
      setSugLoading(false);
    }
  };

  return (
    <div style={{
      background: 'linear-gradient(135deg, #0d0d0d 0%, #0a0a0f 100%)',
      border: '1px solid #222',
      borderRadius: 10,
      overflow: 'hidden',
      flexShrink: 0,
    }}>
      {/* ── Widget header ── */}
      <div style={{ padding: '10px 12px 8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          {/* Ascent icon */}
          <span style={{ fontSize: 14 }}>{isDone ? '✅' : '🚀'}</span>
          {/* Title — truncated */}
          <span style={{
            flex: 1, fontSize: 12, fontWeight: 700, color: '#f0f0f0',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {ascent.name}
          </span>

          {/* ── TOGGLE BUTTON ── */}
          <button
            id={`ascent-suggest-toggle-${ascent.id}`}
            onClick={toggleSuggestions}
            title={suggestionsOpen ? 'Hide suggested memories' : 'Show suggested memories'}
            style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '3px 9px', fontSize: 9, fontFamily: MONO, letterSpacing: '0.06em',
              background: suggestionsOpen ? 'rgba(139,92,246,0.18)' : 'transparent',
              border: `1px solid ${suggestionsOpen ? 'rgba(139,92,246,0.5)' : '#2a2a2a'}`,
              borderRadius: 20, color: suggestionsOpen ? '#a78bfa' : '#555',
              cursor: 'pointer', transition: 'all 0.15s', flexShrink: 0,
            }}
          >
            <span>{suggestionsOpen ? '●' : '○'}</span>
            <span>SUGGEST</span>
          </button>
        </div>

        {/* Progress bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ flex: 1, height: 3, background: '#1a1a1a', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{
              height: '100%', borderRadius: 2,
              width: `${progressPct}%`,
              background: isDone ? '#22c55e' : 'linear-gradient(90deg, #8b5cf6, #22c55e)',
              transition: 'width 0.4s ease',
            }} />
          </div>
          <span style={{ fontSize: 9, color: '#555', fontFamily: MONO, flexShrink: 0 }}>
            {ascent.todos_completed}/{ascent.todo_count}
          </span>
          <span style={{ fontSize: 9, color: progressPct >= 100 ? '#22c55e' : '#8b5cf6', fontFamily: MONO, flexShrink: 0 }}>
            {progressPct}%
          </span>
        </div>
      </div>

      {/* ── Suggestions panel (toggleable) ── */}
      {suggestionsOpen && (
        <div style={{ borderTop: '1px solid #1a1a1a' }}>
          {/* Panel header */}
          <div style={{ padding: '7px 12px 6px', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 9, color: '#a78bfa', fontFamily: MONO, letterSpacing: '0.08em', fontWeight: 700 }}>
              ✦ SUGGESTED MEMORIES
            </span>
            <span style={{ fontSize: 8, color: '#444', fontFamily: MONO, marginLeft: 'auto' }}>
              click to expand · inject to chat
            </span>
          </div>

          {/* Loading skeleton */}
          {sugLoading && (
            <div style={{ padding: '0 12px 10px', display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[1, 2, 3].map(i => (
                <div key={i} style={{ height: 38, background: '#111', borderRadius: 6, opacity: 0.6,
                  animation: 'pulse 1.4s ease-in-out infinite' }} />
              ))}
            </div>
          )}

          {/* Error */}
          {!sugLoading && sugError && (
            <div style={{ margin: '0 12px 10px', padding: '6px 10px', background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.2)', borderRadius: 6, fontSize: 10, color: '#fca5a5' }}>
              {sugError}
            </div>
          )}

          {/* Empty state */}
          {!sugLoading && !sugError && suggestions.length === 0 && (
            <div style={{ padding: '10px 12px 12px', fontSize: 11, color: '#444', textAlign: 'center' }}>
              No relevant memories found yet — capture more!
            </div>
          )}

          {/* Suggestion cards */}
          {!sugLoading && suggestions.length > 0 && (
            <div style={{ padding: '0 10px 10px', display: 'flex', flexDirection: 'column', gap: 5 }}>
              {suggestions.map(s => (
                <SuggestionCard key={s.id} item={s} apiKey={apiKey} onInject={onInject} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Memory card (list view) ──────────────────────────────────────────────────

function MemCard({ record, onOpen, onInject, onDelete }: {
  record: MemoryRecord;
  onOpen: (r: MemoryRecord) => void;
  onInject: (r: MemoryRecord) => void;
  onDelete: (id: string) => void;
}) {
  const meta = getSourceMeta(record.sourceApp);
  const [delConfirm, setDelConfirm] = useState(false);
  const [pinned, setPinned] = useState(record.pinned ?? false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!delConfirm) return;
    const t = setTimeout(() => setDelConfirm(false), 3500);
    return () => clearTimeout(t);
  }, [delConfirm]);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(record.summary || record.title || '');
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const handlePin = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const next = !pinned;
    setPinned(next);
    api.patchMemory(record.id, { pinned: next }, record).catch(() => setPinned(!next));
  };

  return (
    <div
      onClick={() => !delConfirm && onOpen(record)}
      style={{ background: '#0d0d0d', border: '1px solid #222', borderRadius: 8, overflow: 'hidden', cursor: 'pointer', flex: '0 0 auto' }}
    >
      <div style={{ padding: '10px 12px', minHeight: 48 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
          <span style={{ fontSize: 9, color: meta.color, fontFamily: MONO, letterSpacing: '0.06em', fontWeight: 700 }}>{meta.label.toUpperCase()}</span>
          {pinned && <span style={{ fontSize: 9, color: '#f59e0b' }}>📌</span>}
          <span style={{ fontSize: 9, color: '#555', fontFamily: MONO, marginLeft: 'auto' }}>{timeAgo(record.timestamp)}</span>
        </div>
        <div style={{ fontSize: 12, color: '#e5e5e5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginBottom: 4, fontWeight: 500 }}>
          {record.title || record.summary || record.sourceUrl || 'Untitled memory'}
        </div>
        <div style={{ fontSize: 10, color: '#888', lineHeight: 1.5, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
          {cleanContentForDisplay(record.summary || record.title || '')}
        </div>
      </div>
      <div
        onClick={e => e.stopPropagation()}
        style={{ display: 'flex', gap: 4, padding: '6px 12px', borderTop: '1px solid #1a1a1a' }}
      >
        <button onClick={e => { e.stopPropagation(); onInject(record); }} style={{ flex: 1, padding: '4px 0', fontSize: 10, background: 'transparent', border: '1px solid #222', borderRadius: 4, color: '#888', cursor: 'pointer' }}>
          Inject ↗
        </button>
        <button onClick={handleCopy} style={{ flex: 1, padding: '4px 0', fontSize: 10, background: 'transparent', border: '1px solid #222', borderRadius: 4, color: copied ? '#22c55e' : '#888', cursor: 'pointer' }}>
          {copied ? 'Copied!' : 'Copy'}
        </button>
        <button onClick={handlePin} style={{ padding: '4px 8px', fontSize: 10, background: pinned ? 'rgba(245,158,11,0.12)' : 'transparent', border: '1px solid #222', borderRadius: 4, color: pinned ? '#f59e0b' : '#666', cursor: 'pointer' }} title={pinned ? 'Unpin' : 'Pin'}>
          {pinned ? '📌' : '📍'}
        </button>
        {delConfirm ? (
          <button onClick={e => { e.stopPropagation(); onDelete(record.id); }} style={{ padding: '4px 10px', fontSize: 10, background: '#ef4444', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>Confirm</button>
        ) : (
          <button onClick={e => { e.stopPropagation(); setDelConfirm(true); }} style={{ padding: '4px 8px', fontSize: 10, background: 'transparent', border: '1px solid #222', borderRadius: 4, color: '#555', cursor: 'pointer' }}>✕</button>
        )}
      </div>
    </div>
  );
}

// ─── Memory detail ────────────────────────────────────────────────────────────

function MemDetail({ record, onBack, onInject, onDelete }: { record: MemoryRecord; onBack: () => void; onInject: (r: MemoryRecord) => void; onDelete: (id: string) => void }) {
  const meta = getSourceMeta(record.sourceApp);
  const [content, setContent] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [delConfirm, setDelConfirm] = useState(false);

  useEffect(() => { api.getFullContent(record.id).then(r => setContent(r.content)).catch(() => setContent(record.summary)); }, [record.id]);
  useEffect(() => { if (!delConfirm) return; const t = setTimeout(() => setDelConfirm(false), 3500); return () => clearTimeout(t); }, [delConfirm]);

  const copyFull = () => {
    const txt = content ? formatFullInject(content, record.eventType, meta.label) : record.summary;
    navigator.clipboard.writeText(txt);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  const handleDelete = () => { if (!delConfirm) { setDelConfirm(true); return; } onDelete(record.id); onBack(); };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
      <div style={{ padding: '12px 14px', borderBottom: '1px solid #1a1a1a', display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={onBack} style={{ background: 'none', border: 'none', color: '#22c55e', fontSize: 12, cursor: 'pointer', padding: 0, fontFamily: MONO }}>← Back</button>
        <span style={{ fontSize: 9, color: meta.color, fontFamily: MONO, letterSpacing: '0.06em', fontWeight: 700 }}>{meta.label.toUpperCase()}</span>
        <span style={{ fontSize: 9, color: '#555', fontFamily: MONO, marginLeft: 'auto' }}>{timeAgo(record.timestamp)}</span>
      </div>
      {record.title && <div style={{ padding: '14px 14px 0', fontSize: 14, fontWeight: 600, color: '#fff', lineHeight: 1.4 }}>{record.title}</div>}
      <div style={{ padding: '10px 14px', flex: 1, overflow: 'auto', fontSize: 12, color: '#aaa', lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {content ?? record.summary}
      </div>
      <div style={{ padding: '10px 14px', borderTop: '1px solid #1a1a1a', display: 'flex', gap: 6 }}>
        <button onClick={copyFull} style={{ flex: 1, padding: '7px 0', fontSize: 11, background: '#111', border: '1px solid #222', borderRadius: 5, color: copied ? '#22c55e' : '#ccc', cursor: 'pointer' }}>{copied ? 'Copied!' : 'Copy'}</button>
        <button onClick={() => onInject(record)} style={{ flex: 1, padding: '7px 0', fontSize: 11, background: '#fff', border: 'none', borderRadius: 5, color: '#000', fontWeight: 600, cursor: 'pointer' }}>Inject ↗</button>
        {record.sourceUrl && (
          <a href={record.sourceUrl} target="_blank" rel="noopener noreferrer" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '7px 0', fontSize: 11, background: 'transparent', border: '1px solid #222', borderRadius: 5, color: '#888', textDecoration: 'none' }}>Open ↗</a>
        )}
        <button onClick={handleDelete} style={{ padding: '7px 10px', fontSize: 11, background: delConfirm ? '#ef4444' : 'transparent', border: `1px solid ${delConfirm ? '#ef4444' : '#222'}`, borderRadius: 5, color: delConfirm ? '#fff' : '#555', cursor: 'pointer', transition: 'all 0.15s', flexShrink: 0 }}>
          {delConfirm ? 'Confirm' : '✕'}
        </button>
      </div>
    </div>
  );
}

// ─── Browse tab ───────────────────────────────────────────────────────────────

type DateFilter = 'all' | 'today' | 'week' | 'month';

function BrowseTab({ apiKey }: { apiKey: string | null }) {
  const [query, setQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<SourceApp | 'all'>('all');
  const [dateFilter, setDateFilter] = useState<DateFilter>('all');
  const [items, setItems] = useState<MemoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [opened, setOpened] = useState<MemoryRecord | null>(null);
  const [injectMsg, setInjectMsg] = useState('');
  const [pinnedAscents, setPinnedAscents] = useState<AscentSummary[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load pinned ascents
  useEffect(() => {
    api.listAscents()
      .then(res => setPinnedAscents(res.items.filter(a => a.status === 'active').slice(0, 3)))
      .catch(() => {});
  }, []);

  const doSearch = useCallback(async (q: string, src: SourceApp | 'all', date: DateFilter) => {
    setLoading(true); setError('');
    try {
      let after: string | undefined;
      if (date === 'today') after = new Date(new Date().setHours(0, 0, 0, 0)).toISOString();
      else if (date === 'week') after = new Date(Date.now() - 7 * 86400000).toISOString();
      else if (date === 'month') after = new Date(Date.now() - 30 * 86400000).toISOString();
      const r = await api.search({ query: q, after, filters: src !== 'all' ? { sourceApp: src } : undefined });
      setItems(r.items);
    } catch (err) { setError(userFacingError(err)); setItems([]); }
    setLoading(false);
  }, []);

  useEffect(() => { doSearch('', 'all', 'all'); }, [doSearch]);

  useEffect(() => {
    const refresh = () => doSearch(query, sourceFilter, dateFilter);
    const onVisibility = () => { if (document.visibilityState === 'visible') refresh(); };
    const onStorage = (changes: Record<string, chrome.storage.StorageChange>, namespace: string) => {
      if (namespace !== 'local') return;
      if (changes['shail_doc_index'] || changes['shail_recent_saves'] || changes['shail_capture_state_cache']) {
        refresh();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    document.addEventListener('shail:refresh', refresh);
    chrome.storage.onChanged.addListener(onStorage);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      document.removeEventListener('shail:refresh', refresh);
      chrome.storage.onChanged.removeListener(onStorage);
    };
  }, [doSearch, query, sourceFilter, dateFilter]);

  const handleQueryChange = (q: string) => {
    setQuery(q);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(q, sourceFilter, dateFilter), 350);
  };

  const handleSourceChange = (s: SourceApp | 'all') => { setSourceFilter(s); doSearch(query, s, dateFilter); };
  const handleDateChange = (d: DateFilter) => { setDateFilter(d); doSearch(query, sourceFilter, d); };

  const handleInject = async (record: MemoryRecord) => {
    try {
      const full = await api.getFullContent(record.id).catch(() => ({ content: record.summary, eventType: record.eventType }));
      const meta = getSourceMeta(record.sourceApp);
      const text = formatFullInject(full.content, full.eventType, meta.label);
      await executeInject(text, apiKey, setInjectMsg);
    } catch { setInjectMsg('Inject failed'); setTimeout(() => setInjectMsg(''), 2000); }
  };

  const handleDelete = async (id: string) => {
    try { await api.deleteMemory(id); setItems(prev => prev.filter(r => r.id !== id && r.customId !== id)); setInjectMsg('Deleted'); }
    catch (err) { setInjectMsg(userFacingError(err)); }
    setTimeout(() => setInjectMsg(''), 2000);
  };

  if (opened) return <MemDetail record={opened} onBack={() => setOpened(null)} onInject={r => { handleInject(r); setOpened(null); }} onDelete={handleDelete} />;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ── Pinned Ascent widgets ── */}
      {pinnedAscents.length > 0 && (
        <div style={{ padding: '10px 12px 0', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {pinnedAscents.map(a => (
            <AscentWidget key={a.id} ascent={a} apiKey={apiKey} onInject={setInjectMsg} />
          ))}
        </div>
      )}

      {/* Search */}
      <div style={{ padding: '10px 12px 0', display: 'flex', gap: 8, alignItems: 'stretch' }}>
        <input
          value={query} onChange={e => handleQueryChange(e.target.value)} placeholder="Search memories…"
          style={{ flex: 1, minWidth: 0, padding: '8px 12px', fontSize: 12, background: '#0d0d0d', border: '1px solid #222', borderRadius: 6, color: '#e5e5e5', outline: 'none', boxSizing: 'border-box' }}
        />
        <button onClick={() => doSearch(query, sourceFilter, dateFilter)} disabled={loading}
          style={{ flexShrink: 0, padding: '0 12px', fontSize: 10, background: 'transparent', border: '1px solid #222', borderRadius: 6, color: loading ? '#444' : '#999', cursor: loading ? 'wait' : 'pointer', fontFamily: MONO, letterSpacing: '0.06em' }}>
          {loading ? 'LOADING' : 'RELOAD'}
        </button>
      </div>

      {/* Source filter pills */}
      <div style={{ padding: '8px 12px 0', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        {(['all', ...SOURCE_APPS] as const).map(s => (
          <button key={s} onClick={() => handleSourceChange(s)} style={{ padding: '3px 9px', fontSize: 9, borderRadius: 20, border: '1px solid', borderColor: sourceFilter === s ? '#22c55e' : '#222', background: sourceFilter === s ? 'rgba(34,197,94,0.12)' : 'transparent', color: sourceFilter === s ? '#22c55e' : '#666', cursor: 'pointer', fontFamily: MONO, letterSpacing: '0.04em' }}>
            {s === 'all' ? 'ALL' : SOURCE_LABEL[s].toUpperCase()}
          </button>
        ))}
      </div>

      {/* Date filter */}
      <div style={{ padding: '6px 12px 0', display: 'flex', gap: 5 }}>
        {(['all', 'today', 'week', 'month'] as DateFilter[]).map(d => (
          <button key={d} onClick={() => handleDateChange(d)} style={{ padding: '2px 7px', fontSize: 9, borderRadius: 20, border: '1px solid', borderColor: dateFilter === d ? '#444' : '#1a1a1a', background: 'transparent', color: dateFilter === d ? '#bbb' : '#444', cursor: 'pointer', fontFamily: MONO }}>
            {d === 'all' ? 'ALL TIME' : d === 'today' ? 'TODAY' : d === 'week' ? 'THIS WEEK' : 'THIS MONTH'}
          </button>
        ))}
      </div>

      {injectMsg && (
        <div style={{ margin: '6px 12px 0', padding: '5px 10px', background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.25)', borderRadius: 5, fontSize: 10, color: '#86efac' }}>
          {injectMsg}
        </div>
      )}
      {error && (
        <div style={{ margin: '6px 12px 0', padding: '5px 10px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 5, fontSize: 10, color: '#fca5a5' }}>
          {error}
        </div>
      )}

      {/* Results */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '8px 12px 12px', display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'stretch' }}>
        {loading && [1, 2, 3].map(i => (
          <div key={i} style={{ background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 8, padding: '10px 12px', height: 74, flex: '0 0 auto' }}>
            <div style={{ height: 10, background: '#1a1a1a', borderRadius: 4, width: '30%', marginBottom: 8, animation: 'pulse 1.5s ease-in-out infinite' }} />
            <div style={{ height: 12, background: '#1a1a1a', borderRadius: 4, width: '80%', marginBottom: 6, animation: 'pulse 1.5s ease-in-out infinite' }} />
            <div style={{ height: 10, background: '#1a1a1a', borderRadius: 4, width: '60%', animation: 'pulse 1.5s ease-in-out infinite' }} />
          </div>
        ))}
        {!loading && !error && items.length === 0 && (
          <div style={{ fontSize: 12, color: '#444', padding: '24px 0', textAlign: 'center' }}>
            {query ? 'No memories match this search.' : 'No memories yet — start capturing!'}
          </div>
        )}
        {!loading && items.map(r => (
          <div key={r.id} style={{ flex: '0 0 auto' }}>
            <MemCard record={r} onOpen={setOpened} onInject={handleInject} onDelete={handleDelete} />
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Ask tab ──────────────────────────────────────────────────────────────────

interface LocalFileCite { id: string; title: string; path: string; snippet?: string; file_type?: string; score?: number; }
interface ChatMsg { role: 'user' | 'assistant'; text: string; provider?: string; fellback?: boolean; localFiles?: LocalFileCite[]; }

function AskTab({ apiKey }: { apiKey: string | null }) {
  const [routes, setRoutes] = useState<RouteCluster[]>([]);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    api.routes().then(r => setRoutes(r.routes.slice(0, 4))).catch(() => {});
    chrome.storage.local.get([CHAT_HISTORY_KEY, CHAT_SESSION_KEY]).then(r => {
      const hist = r[CHAT_HISTORY_KEY] as ChatMsg[] | undefined;
      if (hist?.length) setMessages(hist);
      const sid = r[CHAT_SESSION_KEY] as string | undefined;
      if (sid) setSessionId(sid);
    });
    return () => { abortRef.current?.abort(); abortRef.current = null; };
  }, []);

  useEffect(() => { if (messages.length > 0) chrome.storage.local.set({ [CHAT_HISTORY_KEY]: messages.slice(-40) }); }, [messages]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const clearHistory = () => { setMessages([]); setSessionId(null); chrome.storage.local.remove([CHAT_HISTORY_KEY, CHAT_SESSION_KEY]); };

  const sendMessage = useCallback(async (q: string) => {
    if (!q.trim() || streaming) return;
    const userMsg = q.trim();
    setInput('');
    const newMessages = [...messages, { role: 'user' as const, text: userMsg }];
    setMessages(newMessages);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const res = await fetch(`${BASE}/browser/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(apiKey ? { 'Authorization': `Bearer ${apiKey}` } : {}) },
        body: JSON.stringify({ message: userMsg, session_id: sessionId }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error('Chat failed');
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let assistantText = '';
      let provider = '';
      let fellback = false;
      setMessages(prev => [...prev, { role: 'assistant', text: '', provider, fellback }]);
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        for (const line of chunk.split('\n')) {
          if (!line.startsWith('data:')) continue;
          const raw = line.slice(5).trim();
          if (!raw || raw === '[DONE]') continue;
          try {
            const ev = JSON.parse(raw);
            if (ev.type === 'meta') { provider = ev.provider ?? ''; fellback = ev.fellback ?? false; }
            else if (ev.type === 'delta') {
              assistantText += ev.text ?? '';
              setMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', text: assistantText, provider, fellback }; return u; });
            }
            else if (ev.type === 'local_files' && Array.isArray(ev.items)) {
              setMessages(prev => {
                const u = [...prev];
                const last = u[u.length - 1];
                if (last && last.role === 'assistant') u[u.length - 1] = { ...last, localFiles: ev.items };
                return u;
              });
            }
          } catch { /* skip malformed */ }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${userFacingError(err)}` }]);
    }
    setStreaming(false);
    abortRef.current = null;
  }, [streaming, messages, apiKey, sessionId]);

  const handleKey = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input); } };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 12px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {messages.length === 0 && (
          <div style={{ color: '#444', fontSize: 11, textAlign: 'center', marginTop: 24, lineHeight: 1.8 }}>
            Ask anything — SHAIL searches your memories<br />and the web to answer.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            {m.role === 'user' ? (
              <div style={{ maxWidth: '85%', background: '#fff', color: '#000', borderRadius: 10, padding: '8px 12px', fontSize: 12, lineHeight: 1.5 }}>{m.text}</div>
            ) : (
              <div style={{ maxWidth: '95%' }}>
                {m.provider && (
                  <div style={{ fontSize: 8, color: m.fellback ? '#f59e0b' : '#444', fontFamily: MONO, marginBottom: 3, letterSpacing: '0.06em' }}>
                    {m.fellback ? '⚠ FALLBACK · ' : ''}{m.provider.toUpperCase()}
                  </div>
                )}
                <div style={{ background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 10, padding: '8px 12px', fontSize: 12, color: '#ccc', lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {m.text || <span style={{ color: '#333' }}>…</span>}
                </div>
                {m.localFiles && m.localFiles.length > 0 && (
                  <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {m.localFiles.map(f => (
                      <button key={f.id}
                        onClick={() => fetch(`${BASE}/path-index/open?path=${encodeURIComponent(f.path)}`, { method: 'POST', headers: apiKey ? { 'Authorization': `Bearer ${apiKey}` } : {} }).catch(() => {})}
                        title={`${f.path}\n\n${f.snippet ?? ''}`}
                        style={{ fontSize: 9, fontFamily: MONO, color: '#7aa6e0', background: '#0a0a0a', border: '1px solid #7aa6e040', borderRadius: 4, padding: '2px 6px', cursor: 'pointer', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        📄 {f.title}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {routes.length > 0 && messages.length === 0 && (
        <div style={{ padding: '10px 12px 0' }}>
          <div style={{ fontSize: 9, color: '#333', fontFamily: MONO, letterSpacing: '0.08em', marginBottom: 6 }}>TRY A ROUTE</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {routes.map(r => (
              <button key={r.label} onClick={() => { setInput(`Tell me about ${r.label}`); textareaRef.current?.focus(); }}
                style={{ textAlign: 'left', padding: '6px 10px', background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 6, fontSize: 11, color: '#888', cursor: 'pointer' }}>
                <span style={{ color: '#444', fontFamily: MONO, fontSize: 9, marginRight: 6 }}>{r.axis.toUpperCase()}</span>
                {r.label}
                <span style={{ float: 'right', fontSize: 9, color: '#333', fontFamily: MONO }}>{r.count}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div style={{ padding: '10px 12px 12px' }}>
        {messages.length > 0 && !streaming && (
          <button onClick={clearHistory} style={{ width: '100%', marginBottom: 6, padding: '4px 0', fontSize: 10, background: 'transparent', border: '1px solid #1a1a1a', borderRadius: 5, color: '#444', cursor: 'pointer' }}>
            Clear history
          </button>
        )}
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end' }}>
          <textarea ref={textareaRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKey} placeholder="Ask anything… (Enter to send)" rows={2}
            style={{ flex: 1, padding: '8px 10px', fontSize: 12, background: '#0d0d0d', border: '1px solid #222', borderRadius: 7, color: '#e5e5e5', outline: 'none', resize: 'none', fontFamily: 'inherit', lineHeight: 1.5 }} />
          <button onClick={() => streaming ? abortRef.current?.abort() : sendMessage(input)} disabled={!input.trim() && !streaming}
            style={{ padding: '8px 12px', fontSize: 12, borderRadius: 7, border: 'none', background: streaming ? '#1a1a1a' : (input.trim() ? '#22c55e' : '#111'), color: streaming ? '#ef4444' : (input.trim() ? '#000' : '#333'), cursor: input.trim() || streaming ? 'pointer' : 'not-allowed', fontWeight: 700 }}>
            {streaming ? '■' : '↑'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Runtime status ───────────────────────────────────────────────────────────

function OllamaRuntimeBadge({ apiKey }: { apiKey: string | null }) {
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    api.systemStatus().then(setSystem).catch(() => setSystem(null));
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    const onVisibility = () => { if (document.visibilityState === 'visible') refresh(); };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [refresh]);

  const ollama = system?.services?.ollama;
  const status = busy ? 'starting' : (ollama?.status ?? 'unknown');
  const pending = system?.blueprint_queue?.pending ?? 0;
  const running = system?.blueprint_queue?.running ?? 0;
  const color =
    status === 'running' ? '#22c55e' :
    status === 'starting' ? '#f59e0b' :
    status === 'not_installed' ? '#555' :
    status === 'stopped' ? '#777' :
    status === 'error' ? '#ef4444' : '#444';
  const label =
    status === 'not_installed' ? 'OLLAMA MISSING' :
    status === 'starting' ? 'OLLAMA STARTING' :
    status === 'running' ? 'OLLAMA RUNNING' :
    status === 'stopped' ? 'OLLAMA STOPPED' : 'OLLAMA UNKNOWN';

  const handleStart = async () => {
    setBusy(true);
    try {
      await fetch(api.systemRestartUrl('ollama'), {
        method: 'POST',
        headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
      }).then(r => r.text().catch(() => ''));
      refresh();
    } catch {
      setSystem(null);
    }
    setBusy(false);
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, display: 'inline-block', flexShrink: 0 }} />
      <span title={`Blueprint queue: ${pending} pending, ${running} running`} style={{ fontSize: 8, color, fontFamily: MONO, letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>
        {label} · Q {pending}/{running}
      </span>
      {(status === 'stopped' || status === 'error' || status === 'unknown') && (
        <button
          onClick={handleStart}
          disabled={busy}
          style={{ padding: '2px 6px', fontSize: 9, background: 'transparent', border: '1px solid #222', borderRadius: 4, color: busy ? '#444' : '#888', cursor: busy ? 'wait' : 'pointer' }}
        >
          Start
        </button>
      )}
      {status === 'not_installed' && (
        <a href="https://ollama.com/download" target="_blank" rel="noreferrer" style={{ fontSize: 9, color: '#777', textDecoration: 'underline' }}>
          Install
        </a>
      )}
    </div>
  );
}

// ─── Main sidepanel ───────────────────────────────────────────────────────────

function Sidepanel() {
  const [tab, setTab] = useState<'browse' | 'ask'>('browse');
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [apiKey, setApiKey] = useState<string | null>(null);

  useEffect(() => {
    getApiKey().then(k => { setApiKey(k); setAuthed(!!k); });
  }, []);

  useEffect(() => {
    const handler = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area === 'sync' && 'shail_api_key' in changes) {
        getApiKey().then(k => { setApiKey(k); setAuthed(!!k); });
      }
    };
    chrome.storage.onChanged.addListener(handler);
    return () => chrome.storage.onChanged.removeListener(handler);
  }, []);

  return (
    <div style={{ width: '100%', height: '100vh', background: '#000', color: '#fff', display: 'flex', flexDirection: 'column', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', overflow: 'hidden' }}>

      {/* Header */}
      <div style={{ padding: '12px 14px 0', borderBottom: '1px solid #1a1a1a', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#fff' }}>SHAIL</span>
          <span style={{ fontSize: 9, color: '#22c55e', fontFamily: MONO, letterSpacing: '0.1em' }}>MEMORY</span>
          <OllamaRuntimeBadge apiKey={apiKey} />
          <button onClick={() => document.dispatchEvent(new CustomEvent('shail:refresh'))} title="Refresh memories"
            style={{ padding: '3px 8px', fontSize: 13, background: 'transparent', border: '1px solid #222', borderRadius: 5, color: '#666', cursor: 'pointer', lineHeight: 1 }}>↻</button>
          {!authed && (
            <button onClick={() => chrome.runtime.openOptionsPage()} style={{ padding: '3px 10px', fontSize: 10, background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)', borderRadius: 5, color: '#22c55e', cursor: 'pointer' }}>
              Sign in
            </button>
          )}
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          {(['browse', 'ask'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{ background: 'none', border: 'none', padding: '0 0 10px', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: tab === t ? '#fff' : '#444', borderBottom: tab === t ? '2px solid #22c55e' : '2px solid transparent', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 8, color: tab === t ? '#22c55e' : '#333' }}>{tab === t ? '●' : '○'}</span>
              {t === 'browse' ? 'Browse' : 'Ask'}
            </button>
          ))}
        </div>
      </div>

      {tab === 'browse' ? <BrowseTab apiKey={apiKey} /> : <AskTab apiKey={apiKey} />}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('app')!).render(
  <React.StrictMode><Sidepanel /></React.StrictMode>
);
