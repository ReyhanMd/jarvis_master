import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactDOM from 'react-dom/client';
import { api, getApiKey, cleanContentForDisplay, formatFullInject, userFacingError, RouteCluster } from '../../src/lib/api';
import { timeAgo, getSourceMeta } from '../../src/lib/utils';
import type { MemoryRecord, SourceApp } from '../../src/types/contracts';
import './style.css';

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const BASE = 'http://localhost:8000';
const CHAT_HISTORY_KEY = 'shail_sidepanel_chat_history';
const CHAT_SESSION_KEY = 'shail_sidepanel_session_id';

const SOURCE_APPS: SourceApp[] = ['chatgpt', 'claude', 'gemini', 'perplexity', 'web'];
const SOURCE_LABEL: Record<SourceApp, string> = { chatgpt: 'ChatGPT', claude: 'Claude', gemini: 'Gemini', perplexity: 'Perplexity', web: 'Web' };

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
        <button
          onClick={e => { e.stopPropagation(); onInject(record); }}
          style={{ flex: 1, padding: '4px 0', fontSize: 10, background: 'transparent', border: '1px solid #222', borderRadius: 4, color: '#888', cursor: 'pointer' }}
        >
          Inject ↗
        </button>
        <button
          onClick={handleCopy}
          style={{ flex: 1, padding: '4px 0', fontSize: 10, background: 'transparent', border: '1px solid #222', borderRadius: 4, color: copied ? '#22c55e' : '#888', cursor: 'pointer' }}
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
        <button
          onClick={handlePin}
          style={{ padding: '4px 8px', fontSize: 10, background: pinned ? 'rgba(245,158,11,0.12)' : 'transparent', border: '1px solid #222', borderRadius: 4, color: pinned ? '#f59e0b' : '#666', cursor: 'pointer' }}
          title={pinned ? 'Unpin' : 'Pin'}
        >
          {pinned ? '📌' : '📍'}
        </button>
        {delConfirm ? (
          <button
            onClick={e => { e.stopPropagation(); onDelete(record.id); }}
            style={{ padding: '4px 10px', fontSize: 10, background: '#ef4444', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}
          >
            Confirm
          </button>
        ) : (
          <button
            onClick={e => { e.stopPropagation(); setDelConfirm(true); }}
            style={{ padding: '4px 8px', fontSize: 10, background: 'transparent', border: '1px solid #222', borderRadius: 4, color: '#555', cursor: 'pointer' }}
          >
            ✕
          </button>
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

  useEffect(() => {
    api.getFullContent(record.id).then(r => setContent(r.content)).catch(() => setContent(record.summary));
  }, [record.id]);

  useEffect(() => {
    if (!delConfirm) return;
    const t = setTimeout(() => setDelConfirm(false), 3500);
    return () => clearTimeout(t);
  }, [delConfirm]);

  const copyFull = () => {
    const txt = content ? formatFullInject(content, record.eventType, meta.label) : record.summary;
    navigator.clipboard.writeText(txt);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  const handleDelete = () => {
    if (!delConfirm) { setDelConfirm(true); return; }
    onDelete(record.id);
    onBack();
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
      <div style={{ padding: '12px 14px', borderBottom: '1px solid #1a1a1a', display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={onBack} style={{ background: 'none', border: 'none', color: '#22c55e', fontSize: 12, cursor: 'pointer', padding: 0, fontFamily: MONO }}>← Back</button>
        <span style={{ fontSize: 9, color: meta.color, fontFamily: MONO, letterSpacing: '0.06em', fontWeight: 700 }}>{meta.label.toUpperCase()}</span>
        <span style={{ fontSize: 9, color: '#555', fontFamily: MONO, marginLeft: 'auto' }}>{timeAgo(record.timestamp)}</span>
      </div>
      {record.title && (
        <div style={{ padding: '14px 14px 0', fontSize: 14, fontWeight: 600, color: '#fff', lineHeight: 1.4 }}>{record.title}</div>
      )}
      <div style={{ padding: '10px 14px', flex: 1, overflow: 'auto', fontSize: 12, color: '#aaa', lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {content ?? record.summary}
      </div>
      <div style={{ padding: '10px 14px', borderTop: '1px solid #1a1a1a', display: 'flex', gap: 6 }}>
        <button onClick={copyFull} style={{ flex: 1, padding: '7px 0', fontSize: 11, background: '#111', border: '1px solid #222', borderRadius: 5, color: copied ? '#22c55e' : '#ccc', cursor: 'pointer' }}>
          {copied ? 'Copied!' : 'Copy'}
        </button>
        <button onClick={() => onInject(record)} style={{ flex: 1, padding: '7px 0', fontSize: 11, background: '#fff', border: 'none', borderRadius: 5, color: '#000', fontWeight: 600, cursor: 'pointer' }}>
          Inject ↗
        </button>
        {record.sourceUrl && (
          <a href={record.sourceUrl} target="_blank" rel="noopener noreferrer" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '7px 0', fontSize: 11, background: 'transparent', border: '1px solid #222', borderRadius: 5, color: '#888', textDecoration: 'none' }}>
            Open ↗
          </a>
        )}
        <button
          onClick={handleDelete}
          style={{ padding: '7px 10px', fontSize: 11, background: delConfirm ? '#ef4444' : 'transparent', border: `1px solid ${delConfirm ? '#ef4444' : '#222'}`, borderRadius: 5, color: delConfirm ? '#fff' : '#555', cursor: 'pointer', transition: 'all 0.15s', flexShrink: 0 }}
        >
          {delConfirm ? 'Confirm' : '✕'}
        </button>
      </div>
    </div>
  );
}

// ─── Browse tab ───────────────────────────────────────────────────────────────

type DateFilter = 'all' | 'today' | 'week' | 'month';

function BrowseTab() {
  const [query, setQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<SourceApp | 'all'>('all');
  const [dateFilter, setDateFilter] = useState<DateFilter>('all');
  const [items, setItems] = useState<MemoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [opened, setOpened] = useState<MemoryRecord | null>(null);
  const [injectMsg, setInjectMsg] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = useCallback(async (q: string, src: SourceApp | 'all', date: DateFilter) => {
    setLoading(true);
    setError('');
    try {
      let after: string | undefined;
      if (date === 'today') after = new Date(new Date().setHours(0, 0, 0, 0)).toISOString();
      else if (date === 'week') after = new Date(Date.now() - 7 * 86400000).toISOString();
      else if (date === 'month') after = new Date(Date.now() - 30 * 86400000).toISOString();
      const r = await api.search({ query: q, after, filters: src !== 'all' ? { sourceApp: src } : undefined });
      setItems(r.items);
    } catch (err) {
      setError(userFacingError(err));
      setItems([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { doSearch('', 'all', 'all'); }, [doSearch]);

  // Auto-refresh when sidepanel regains visibility (user reopens panel or
  // switches back to Browse tab). Also listen for the manual refresh event
  // dispatched by the header's Refresh button.
  useEffect(() => {
    const refresh = () => doSearch(query, sourceFilter, dateFilter);
    const onVisibility = () => { if (document.visibilityState === 'visible') refresh(); };
    document.addEventListener('visibilitychange', onVisibility);
    document.addEventListener('shail:refresh', refresh);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      document.removeEventListener('shail:refresh', refresh);
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
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab?.id) { setInjectMsg('No active tab'); return; }
      const full = await api.getFullContent(record.id).catch(() => ({ content: record.summary, eventType: record.eventType }));
      const meta = getSourceMeta(record.sourceApp);
      const text = formatFullInject(full.content, full.eventType, meta.label);
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: injectIntoPage, args: [text] });
      setInjectMsg('Injected!');
    } catch { setInjectMsg('Inject failed'); }
    setTimeout(() => setInjectMsg(''), 2000);
  };

  const handleDelete = async (id: string) => {
    try { await api.deleteMemory(id); setItems(prev => prev.filter(r => r.id !== id)); } catch { /* ignore */ }
  };

  const handleRefresh = () => {
    doSearch(query, sourceFilter, dateFilter);
  };

  if (opened) return <MemDetail record={opened} onBack={() => setOpened(null)} onInject={r => { handleInject(r); setOpened(null); }} onDelete={handleDelete} />;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* Search */}
      <div style={{ padding: '10px 12px 0', display: 'flex', gap: 8, alignItems: 'stretch' }}>
        <input
          value={query}
          onChange={e => handleQueryChange(e.target.value)}
          placeholder="Search memories…"
          style={{ flex: 1, minWidth: 0, padding: '8px 12px', fontSize: 12, background: '#0d0d0d', border: '1px solid #222', borderRadius: 6, color: '#e5e5e5', outline: 'none', boxSizing: 'border-box' }}
        />
        <button
          onClick={handleRefresh}
          disabled={loading}
          title="Reload memories"
          style={{
            flexShrink: 0,
            padding: '0 12px',
            fontSize: 10,
            background: 'transparent',
            border: '1px solid #222',
            borderRadius: 6,
            color: loading ? '#444' : '#999',
            cursor: loading ? 'wait' : 'pointer',
            fontFamily: MONO,
            letterSpacing: '0.06em',
          }}
        >
          {loading ? 'LOADING' : 'RELOAD'}
        </button>
      </div>

      {/* Source filter pills */}
      <div style={{ padding: '8px 12px 0', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        {(['all', ...SOURCE_APPS] as const).map(s => (
          <button
            key={s}
            onClick={() => handleSourceChange(s)}
            style={{
              padding: '3px 9px', fontSize: 9, borderRadius: 20, border: '1px solid',
              borderColor: sourceFilter === s ? '#22c55e' : '#222',
              background: sourceFilter === s ? 'rgba(34,197,94,0.12)' : 'transparent',
              color: sourceFilter === s ? '#22c55e' : '#666',
              cursor: 'pointer', fontFamily: MONO, letterSpacing: '0.04em',
            }}
          >
            {s === 'all' ? 'ALL' : SOURCE_LABEL[s].toUpperCase()}
          </button>
        ))}
      </div>

      {/* Date filter chips */}
      <div style={{ padding: '6px 12px 0', display: 'flex', gap: 5 }}>
        {(['all', 'today', 'week', 'month'] as DateFilter[]).map(d => (
          <button
            key={d}
            onClick={() => handleDateChange(d)}
            style={{
              padding: '2px 7px', fontSize: 9, borderRadius: 20, border: '1px solid',
              borderColor: dateFilter === d ? '#444' : '#1a1a1a',
              background: 'transparent',
              color: dateFilter === d ? '#bbb' : '#444',
              cursor: 'pointer', fontFamily: MONO,
            }}
          >
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
        {loading && (
          <>
            {[1,2,3].map(i => (
              <div key={i} style={{ background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 8, padding: '10px 12px', height: 74, flex: '0 0 auto' }}>
                <div style={{ height: 10, background: '#1a1a1a', borderRadius: 4, width: '30%', marginBottom: 8, animation: 'pulse 1.5s ease-in-out infinite' }} />
                <div style={{ height: 12, background: '#1a1a1a', borderRadius: 4, width: '80%', marginBottom: 6, animation: 'pulse 1.5s ease-in-out infinite' }} />
                <div style={{ height: 10, background: '#1a1a1a', borderRadius: 4, width: '60%', animation: 'pulse 1.5s ease-in-out infinite' }} />
              </div>
            ))}
          </>
        )}
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

interface ChatMsg { role: 'user' | 'assistant'; text: string; provider?: string; fellback?: boolean; }

function AskTab() {
  const [routes, setRoutes] = useState<RouteCluster[]>([]);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load persisted chat history, session ID, and routes on mount
  useEffect(() => {
    getApiKey().then(k => setApiKey(k));
    api.routes().then(r => setRoutes(r.routes.slice(0, 4))).catch(() => {});
    chrome.storage.local.get([CHAT_HISTORY_KEY, CHAT_SESSION_KEY]).then(r => {
      const hist = r[CHAT_HISTORY_KEY] as ChatMsg[] | undefined;
      if (hist?.length) setMessages(hist);
      const sid = r[CHAT_SESSION_KEY] as string | undefined;
      if (sid) setSessionId(sid);
    });

    // Abort stream when tab unmounts (user switches to Browse)
    return () => { abortRef.current?.abort(); abortRef.current = null; };
  }, []);

  // Persist history + session ID when messages change
  useEffect(() => {
    if (messages.length > 0) {
      chrome.storage.local.set({ [CHAT_HISTORY_KEY]: messages.slice(-40) });
    }
  }, [messages]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const clearHistory = () => {
    setMessages([]);
    setSessionId(null);
    chrome.storage.local.remove([CHAT_HISTORY_KEY, CHAT_SESSION_KEY]);
  };

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
          } catch { /* skip malformed */ }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${userFacingError(err)}` }]);
      }
    }
    setStreaming(false);
    abortRef.current = null;
  }, [streaming, messages, apiKey]);

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 12px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {messages.length === 0 && (
          <div style={{ color: '#444', fontSize: 11, textAlign: 'center', marginTop: 24, lineHeight: 1.8 }}>
            Ask anything — SHAIL searches your memories<br />and the web to answer.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            {m.role === 'user' ? (
              <div style={{ maxWidth: '85%', background: '#fff', color: '#000', borderRadius: 10, padding: '8px 12px', fontSize: 12, lineHeight: 1.5 }}>
                {m.text}
              </div>
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
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* TRY A ROUTE (empty state only) */}
      {routes.length > 0 && messages.length === 0 && (
        <div style={{ padding: '10px 12px 0' }}>
          <div style={{ fontSize: 9, color: '#333', fontFamily: MONO, letterSpacing: '0.08em', marginBottom: 6 }}>TRY A ROUTE</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {routes.map(r => (
              <button
                key={r.label}
                onClick={() => { setInput(`Tell me about ${r.label}`); textareaRef.current?.focus(); }}
                style={{ textAlign: 'left', padding: '6px 10px', background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 6, fontSize: 11, color: '#888', cursor: 'pointer' }}
              >
                <span style={{ color: '#444', fontFamily: MONO, fontSize: 9, marginRight: 6 }}>{r.axis.toUpperCase()}</span>
                {r.label}
                <span style={{ float: 'right', fontSize: 9, color: '#333', fontFamily: MONO }}>{r.count}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input + clear history */}
      <div style={{ padding: '10px 12px 12px' }}>
        {messages.length > 0 && !streaming && (
          <button
            onClick={clearHistory}
            style={{ width: '100%', marginBottom: 6, padding: '4px 0', fontSize: 10, background: 'transparent', border: '1px solid #1a1a1a', borderRadius: 5, color: '#444', cursor: 'pointer' }}
          >
            Clear history
          </button>
        )}
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end' }}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Ask anything… (Enter to send)"
            rows={2}
            style={{ flex: 1, padding: '8px 10px', fontSize: 12, background: '#0d0d0d', border: '1px solid #222', borderRadius: 7, color: '#e5e5e5', outline: 'none', resize: 'none', fontFamily: 'inherit', lineHeight: 1.5 }}
          />
          <button
            onClick={() => streaming ? abortRef.current?.abort() : sendMessage(input)}
            disabled={!input.trim() && !streaming}
            style={{
              padding: '8px 12px', fontSize: 12, borderRadius: 7, border: 'none',
              background: streaming ? '#1a1a1a' : (input.trim() ? '#22c55e' : '#111'),
              color: streaming ? '#ef4444' : (input.trim() ? '#000' : '#333'),
              cursor: input.trim() || streaming ? 'pointer' : 'not-allowed',
              fontWeight: 700,
            }}
          >
            {streaming ? '■' : '↑'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main sidepanel ───────────────────────────────────────────────────────────

function Sidepanel() {
  const [tab, setTab] = useState<'browse' | 'ask'>('browse');
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => { getApiKey().then(k => setAuthed(!!k)); }, []);

  useEffect(() => {
    const handler = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area === 'sync' && 'shail_api_key' in changes) getApiKey().then(k => setAuthed(!!k));
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
          <button
            onClick={() => document.dispatchEvent(new CustomEvent('shail:refresh'))}
            title="Refresh memories"
            style={{ marginLeft: 'auto', padding: '3px 8px', fontSize: 13, background: 'transparent', border: '1px solid #222', borderRadius: 5, color: '#666', cursor: 'pointer', lineHeight: 1 }}
          >
            ↻
          </button>
          {!authed && (
            <button
              onClick={() => chrome.runtime.openOptionsPage()}
              style={{ padding: '3px 10px', fontSize: 10, background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)', borderRadius: 5, color: '#22c55e', cursor: 'pointer' }}
            >
              Sign in
            </button>
          )}
        </div>

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: 16 }}>
          {(['browse', 'ask'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                background: 'none', border: 'none', padding: '0 0 10px', cursor: 'pointer',
                fontSize: 12, fontWeight: 600,
                color: tab === t ? '#fff' : '#444',
                borderBottom: tab === t ? '2px solid #22c55e' : '2px solid transparent',
                display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              <span style={{ fontSize: 8, color: tab === t ? '#22c55e' : '#333' }}>{tab === t ? '●' : '○'}</span>
              {t === 'browse' ? 'Browse' : 'Ask'}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      {tab === 'browse' ? <BrowseTab /> : <AskTab />}

    </div>
  );
}

ReactDOM.createRoot(document.getElementById('app')!).render(
  <React.StrictMode><Sidepanel /></React.StrictMode>
);
