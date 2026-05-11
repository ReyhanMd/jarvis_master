import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  api,
  ChatMemoryCitation, ChatPastChatCitation, ChatWebSource,
  ChatSessionSummary, StoredCitation, StoredChatMessage,
} from '../api';

// One MCP citation as it arrives over SSE — provider-tagged.
interface ChatMcpCitation {
  provider: string;
  id: string;
  title: string;
  snippet: string;
  url: string | null;
}
import { ChatRenderer } from '../components/ChatRenderer';
import { useUIStore } from '../stores/ui';
import { flag } from '../lib/featureFlags';

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const CARD = { background: '#0d0d0d', border: '1px solid #161616', borderRadius: 9 } as const;

interface ChatTurn {
  id?: string;            // server message id (after persistence)
  role: 'user' | 'assistant';
  content: string;
  citations: StoredCitation[];
  provider?: string;
  model?: string;
  fellback?: boolean;
  fallbackReason?: string;
}

function citationsFromSseSets(
  memories?: ChatMemoryCitation[],
  pastChats?: ChatPastChatCitation[],
  web?: ChatWebSource[],
  mcp?: ChatMcpCitation[],
): StoredCitation[] {
  const out: StoredCitation[] = [];
  for (const m of memories ?? []) out.push({ type: 'memory', id: m.id, title: m.title, score: m.score });
  for (const c of pastChats ?? []) out.push({
    type: 'chat', id: c.message_id, session_id: c.session_id,
    title: c.session_title, snippet: c.snippet, score: c.score,
  });
  (web ?? []).forEach((w, i) => out.push({
    type: 'web', id: String(i + 1), title: w.title, url: w.url, snippet: w.snippet,
  }));
  for (const c of mcp ?? []) out.push({
    type: 'mcp', id: c.id, provider: c.provider,
    title: c.title, snippet: c.snippet, url: c.url ?? undefined,
  });
  return out;
}

function turnsFromStored(messages: StoredChatMessage[]): ChatTurn[] {
  return messages.map(m => ({
    id: m.id,
    role: m.role,
    content: m.content,
    citations: m.citations || [],
    provider: m.provider ?? undefined,
    model: m.model ?? undefined,
  }));
}

export function Chat() {
  const navigate = useNavigate();
  const { sessionId: routeSessionId } = useParams<{ sessionId: string }>();
  const [params] = useSearchParams();
  const initialQ = params.get('q') ?? '';

  const [sessions, setSessions]   = useState<ChatSessionSummary[]>([]);
  const [activeId, setActiveId]   = useState<string | undefined>(routeSessionId);
  const [turns, setTurns]         = useState<ChatTurn[]>([]);
  const [input, setInput]         = useState(initialQ);
  const [streaming, setStreaming] = useState(false);
  const [loadingThread, setLoadingThread] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inflight  = useRef<AbortController | null>(null);

  const reloadSessions = useCallback(async () => {
    try {
      const r = await api.listChatSessions();
      setSessions(r.items);
    } catch { /* ignore — empty list ok */ }
  }, []);

  useEffect(() => { reloadSessions(); }, [reloadSessions]);

  // Load thread when route changes
  useEffect(() => {
    setActiveId(routeSessionId);
    if (!routeSessionId) {
      setTurns([]);
      return;
    }
    setLoadingThread(true);
    api.getChatSession(routeSessionId)
      .then(s => setTurns(turnsFromStored(s.messages)))
      .catch(() => setTurns([]))
      .finally(() => setLoadingThread(false));
  }, [routeSessionId]);

  const scrollToEnd = () => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  };
  useEffect(() => { scrollToEnd(); }, [turns]);

  // ?q= autosubmit (only on fresh / no-session route)
  const sentInitial = useRef(false);
  useEffect(() => {
    if (initialQ && !sentInitial.current && !routeSessionId) {
      sentInitial.current = true;
      submit(initialQ);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQ, routeSessionId]);

  async function submit(msg?: string) {
    const text = (msg ?? input).trim();
    if (!text || streaming) return;
    setInput('');

    const userTurn:      ChatTurn = { role: 'user', content: text, citations: [] };
    const assistantTurn: ChatTurn = { role: 'assistant', content: '', citations: [] };
    setTurns(prev => [...prev, userTurn, assistantTurn]);
    setStreaming(true);

    inflight.current?.abort();
    const ctrl = new AbortController();
    inflight.current = ctrl;
    const key = localStorage.getItem('shail_api_key') || '';

    try {
      const res = await fetch(api.chatUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` },
        body: JSON.stringify({ message: text, session_id: activeId, stream: true }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      // Trackers for the in-flight assistant turn — used to assemble the
      // final citation list when the stream finishes.
      let memories:  ChatMemoryCitation[]  = [];
      let pastChats: ChatPastChatCitation[] = [];
      let webHits:   ChatWebSource[]        = [];
      let mcpHits:   ChatMcpCitation[]      = [];
      let resolvedSessionId: string | undefined = activeId;

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop() || '';
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith('data:')) continue;
          let evt: Record<string, unknown>;
          try { evt = JSON.parse(line.slice(5).trim()); } catch { continue; }
          const t = evt.type as string;

          if (t === 'meta') {
            if (evt.session_id && !resolvedSessionId) {
              resolvedSessionId = evt.session_id as string;
              setActiveId(resolvedSessionId);
              navigate(`/chat/${resolvedSessionId}`, { replace: true });
            }
          } else if (t === 'memories') {
            memories = evt.items as ChatMemoryCitation[];
          } else if (t === 'past_chats') {
            pastChats = evt.items as ChatPastChatCitation[];
          } else if (t === 'web') {
            webHits = evt.items as ChatWebSource[];
          } else if (t === 'mcp') {
            mcpHits = evt.items as ChatMcpCitation[];
          }

          setTurns(prev => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (!last || last.role !== 'assistant') return prev;
            if (t === 'meta') {
              last.provider = evt.provider as string;
              last.model = evt.model as string;
              last.fellback = !!evt.fellback;
              if (evt.fellback) last.fallbackReason = (evt.reason as string) ?? '';
            } else if (t === 'delta') {
              last.content = (last.content || '') + ((evt.text as string) || '');
            } else if (t === 'memories' || t === 'past_chats' || t === 'web' || t === 'mcp') {
              last.citations = citationsFromSseSets(memories, pastChats, webHits, mcpHits);
            } else if (t === 'done') {
              last.id = evt.message_id as string;
              last.citations = citationsFromSseSets(memories, pastChats, webHits, mcpHits);
              if (flag('ui_v2')) {
                const ui = useUIStore.getState();
                ui.setLastAnswerCitations(last.citations);
                if (last.citations.length > 0) ui.setEvidenceRailOpen(true);
              }
            }
            return next;
          });
        }
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      setTurns(prev => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === 'assistant') last.content = `[error: ${(e as Error).message}]`;
        return next;
      });
    } finally {
      setStreaming(false);
      inflight.current = null;
      reloadSessions();   // refresh sidebar (new title may have landed via autotitle)
    }
  }

  const stop = () => inflight.current?.abort();

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const startNew = () => {
    setTurns([]);
    setActiveId(undefined);
    navigate('/chat');
  };

  const togglePin = async (sid: string, current: boolean) => {
    try {
      await api.patchChatSession(sid, { pinned: !current });
      reloadSessions();
    } catch { /* ignore */ }
  };

  const removeSession = async (sid: string) => {
    if (!confirm('Delete this conversation? Cannot be undone.')) return;
    try {
      await api.deleteChatSession(sid);
      if (sid === activeId) startNew();
      reloadSessions();
    } catch { /* ignore */ }
  };

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      {/* Sidebar */}
      <aside style={{
        width: 260, borderRight: '1px solid #111',
        display: 'flex', flexDirection: 'column', flexShrink: 0,
        background: '#080808',
      }}>
        <div style={{ padding: '20px 18px 12px' }}>
          <button onClick={startNew} style={{
            width: '100%', padding: '8px 12px', fontSize: 12, fontWeight: 500,
            background: '#fff', color: '#000', border: 'none', borderRadius: 6,
            cursor: 'pointer',
          }}>
            + New chat
          </button>
        </div>
        <div style={{ padding: '0 12px 4px', fontSize: 10, color: '#3a3a3a', fontFamily: MONO, letterSpacing: '0.1em' }}>
          HISTORY
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '4px 8px 16px' }}>
          {sessions.length === 0 && (
            <div style={{ padding: 14, color: '#2a2a2a', fontSize: 11, lineHeight: 1.5 }}>
              No chats yet. Start one to build your conversation memory.
            </div>
          )}
          {sessions.map(s => {
            const isActive = s.id === activeId;
            return (
              <div
                key={s.id}
                onClick={() => navigate(`/chat/${s.id}`)}
                style={{
                  padding: '8px 10px', marginBottom: 2, borderRadius: 6,
                  cursor: 'pointer',
                  background: isActive ? '#161616' : 'transparent',
                  border: `1px solid ${isActive ? '#262626' : 'transparent'}`,
                  display: 'flex', alignItems: 'flex-start', gap: 6,
                }}
                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = '#0d0d0d'; }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 12, color: isActive ? '#fff' : '#aaa',
                    fontWeight: isActive ? 500 : 400,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {s.pinned && <span style={{ color: '#f59e0b', marginRight: 4 }}>★</span>}
                    {s.title}
                  </div>
                  {s.preview && (
                    <div style={{
                      marginTop: 2, fontSize: 10, color: '#3a3a3a',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {s.preview}
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 4, opacity: isActive ? 1 : 0.4 }}>
                  <button
                    onClick={e => { e.stopPropagation(); togglePin(s.id, s.pinned); }}
                    title={s.pinned ? 'Unpin' : 'Pin'}
                    style={{ background: 'none', border: 'none', color: s.pinned ? '#f59e0b' : '#444', cursor: 'pointer', fontSize: 12, padding: 0 }}
                  >
                    {s.pinned ? '★' : '☆'}
                  </button>
                  <button
                    onClick={e => { e.stopPropagation(); removeSession(s.id); }}
                    title="Delete"
                    style={{ background: 'none', border: 'none', color: '#444', cursor: 'pointer', fontSize: 13, padding: 0 }}
                    onMouseEnter={e => (e.currentTarget.style.color = '#ef4444')}
                    onMouseLeave={e => (e.currentTarget.style.color = '#444')}
                  >
                    ×
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      {/* Main pane */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '24px 40px 12px', borderBottom: '1px solid #111' }}>
          <div style={{ fontSize: 11, color: '#666', letterSpacing: '0.1em', fontFamily: MONO }}>CHAT</div>
          <h1 style={{ margin: '6px 0 0', fontSize: 22, fontWeight: 500, color: '#fff' }}>
            {activeId
              ? sessions.find(s => s.id === activeId)?.title || 'Conversation'
              : 'Ask SHAIL anything'}
          </h1>
          <p style={{ margin: '6px 0 0', fontSize: 12, color: '#666' }}>
            Pulls from your memories, past chats, connected sources, and the live web.
          </p>
        </div>

        <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '20px 40px' }}>
          {loadingThread ? (
            <div style={{ marginTop: 40, color: '#3a3a3a', fontSize: 12 }}>Loading thread…</div>
          ) : turns.length === 0 ? (
            <div style={{ marginTop: 60, textAlign: 'center', color: '#3a3a3a', fontSize: 13 }}>
              {activeId ? 'Empty conversation. Send a message to begin.' : 'Type a question below to get started.'}
            </div>
          ) : turns.map((t, i) => (
            <div key={t.id ?? i} style={{ marginBottom: 24 }}>
              {t.role === 'user' ? (
                <div style={{
                  display: 'inline-block', padding: '10px 14px',
                  background: '#1a1a1a', borderRadius: 9, fontSize: 13, color: '#fff',
                  maxWidth: '78%', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                }}>
                  {t.content}
                </div>
              ) : (
                <div>
                  {t.provider && (
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
                      fontSize: 10, color: '#666', fontFamily: MONO, letterSpacing: '0.06em',
                    }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                        <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#22c55e' }} />
                        {t.provider.toUpperCase()} · {t.model}
                      </span>
                      {t.fellback && (
                        <span style={{ color: '#fbbf24' }}>
                          ⚠ FELLBACK ({t.fallbackReason?.slice(0, 60) || 'paid provider error'})
                        </span>
                      )}
                    </div>
                  )}
                  {t.content
                    ? <ChatRenderer content={t.content} citations={t.citations} fontSize={14} />
                    : (streaming && i === turns.length - 1
                        ? <span style={{ color: '#555', fontSize: 13 }}>…</span>
                        : null)}

                </div>
              )}
            </div>
          ))}
        </div>

        <div style={{ padding: '14px 40px 20px', borderTop: '1px solid #111' }}>
          <div style={{ ...CARD, padding: 10, display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKey}
              placeholder="Ask anything — Enter to send, Shift+Enter for newline"
              rows={2}
              style={{
                flex: 1, resize: 'none', background: 'transparent', border: 'none',
                color: '#fff', fontSize: 13, fontFamily: 'inherit', outline: 'none',
                padding: '4px 8px', lineHeight: 1.55,
              }}
            />
            {streaming ? (
              <button onClick={stop} style={{
                padding: '8px 14px', fontSize: 11, fontFamily: MONO,
                background: '#ef4444', border: 'none', color: '#fff',
                borderRadius: 6, cursor: 'pointer',
              }}>
                ■ Stop
              </button>
            ) : (
              <button onClick={() => submit()} disabled={!input.trim()} style={{
                padding: '8px 16px', fontSize: 12,
                background: input.trim() ? '#fff' : '#1a1a1a',
                color: input.trim() ? '#000' : '#555',
                border: 'none', borderRadius: 6,
                cursor: input.trim() ? 'pointer' : 'not-allowed', fontWeight: 500,
              }}>
                Send →
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
