import React, { useEffect, useState, useCallback } from 'react';
import ReactDOM from 'react-dom/client';
import { api, getApiKey, AscentSummary } from '../../src/lib/api';
import { timeAgo, getSourceMeta, isDomainDenied } from '../../src/lib/utils';
import type { MemoryRecord, SourceApp, StatsResult, SitePolicy } from '../../src/types/contracts';
import './style.css';

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

function openSettings() { chrome.runtime.openOptionsPage(); }

// ─── Page info ────────────────────────────────────────────────────────────────

interface PageInfo {
  title: string;
  url: string;
  text: string;
  preview: string;
  contentType: 'article' | 'video' | 'document' | 'code' | 'image' | 'audio' | 'social' | 'other';
  wordCount: number;
  canSave: boolean;
}

function extractPageContent(): PageInfo {
  const title = document.title || '';
  const url = location.href;
  type CT = PageInfo['contentType'];
  let contentType: CT = 'article';
  if (/youtube\.com\/watch|youtu\.be\//.test(url)) contentType = 'video';
  else if (/vimeo\.com\/\d/.test(url)) contentType = 'video';
  else if (/drive\.google\.com|docs\.google\.com/.test(url)) contentType = 'document';
  else if (/github\.com\/[^/]+\/[^/]/.test(url)) contentType = 'code';
  else if (/twitter\.com|x\.com|reddit\.com/.test(url)) contentType = 'social';
  else if (/\.(pdf)(\?.*)?$/i.test(url)) contentType = 'document';
  if (!url.startsWith('http')) return { title, url, text: '', preview: '', contentType: 'other', wordCount: 0, canSave: false };
  let text = '';
  if (contentType === 'video' && url.includes('youtube.com')) {
    const parts: string[] = [];
    const t = document.querySelector('h1.ytd-video-primary-info-renderer yt-formatted-string, h1 .yt-core-attributed-string');
    if (t) parts.push((t as HTMLElement).innerText?.trim() ?? title);
    const desc = document.querySelector('#description-inline-expander, ytd-text-inline-expander');
    if (desc) parts.push(((desc as HTMLElement).innerText?.trim() ?? '').slice(0, 600));
    text = parts.filter(Boolean).join('\n\n');
  }
  if (!text) {
    const SELECTORS = ['main', 'article', '[role="main"]', '.post-content', '.article-content', '.prose', '#content'];
    let el: Element | null = null;
    for (const s of SELECTORS) { el = document.querySelector(s); if (el) break; }
    if (el) text = (el as HTMLElement).innerText?.trim()?.slice(0, 3000) ?? '';
    else {
      const clone = document.body.cloneNode(true) as HTMLElement;
      for (const tag of ['script', 'style', 'nav', 'header', 'footer']) clone.querySelectorAll(tag).forEach(n => n.remove());
      text = clone.innerText?.trim()?.slice(0, 3000) ?? '';
    }
  }
  text = text.replace(/[\t ]{2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  const wordCount = text ? text.split(/\s+/).filter(Boolean).length : 0;
  const ogDesc = document.querySelector('meta[property="og:description"], meta[name="description"]')?.getAttribute('content') ?? '';
  const preview = (ogDesc || text).slice(0, 160).trim();
  return { title, url, text, preview, contentType, wordCount, canSave: text.length >= 80 || preview.length >= 40 };
}

// ─── Popup ────────────────────────────────────────────────────────────────────

const KEY_CAPTURE       = 'shail_capture_enabled';
const KEY_PAUSED_CONVOS = 'shail_paused_conversations';

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

function Popup() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [captureEnabled, setCaptureEnabled] = useState<boolean>(true);
  const [pausedConvos, setPausedConvos] = useState<string[]>([]);
  const [stats, setStats] = useState<StatsResult | null>(null);
  const [pageInfo, setPageInfo] = useState<PageInfo | null>(null);
  const [pageStatus, setPageStatus] = useState<'loading' | 'ready' | 'already_saved' | 'denied' | 'unavailable'>('loading');
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [activeAscent, setActiveAscent] = useState<AscentSummary | null>(null);
  const [pinnedAscentId, setPinnedAscentId] = useState<string | null>(null);

  useEffect(() => {
    // Auth check
    getApiKey().then(k => setAuthed(!!k));

    // Stats from local index — instant
    api.stats().then(setStats).catch(() => {});

    // Backend ping
    fetch('http://localhost:8000/health', { signal: AbortSignal.timeout(2000) })
      .then(r => setBackendOk(r.ok))
      .catch(() => setBackendOk(false));

    // Active ascent (best-effort)
    api.listAscents().then(r => {
      const active = r.items.find(a => a.status === 'active') ?? null;
      setActiveAscent(active);
    }).catch(() => {});

    // Pinned ascent from storage
    chrome.storage.local.get('shail_pinned_ascent').then(r => {
      setPinnedAscentId((r['shail_pinned_ascent'] as string) ?? null);
    });

    // Capture state
    chrome.storage.local.get([KEY_CAPTURE, KEY_PAUSED_CONVOS]).then(r => {
      setCaptureEnabled((r[KEY_CAPTURE] as boolean) ?? true);
      setPausedConvos((r[KEY_PAUSED_CONVOS] as string[]) ?? []);
    });

    // Page scrape
    chrome.tabs.query({ active: true, currentWindow: true }).then(async tabs => {
      const tab = tabs[0];
      if (!tab?.id) { setPageStatus('unavailable'); return; }
      try {
        const results = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: extractPageContent });
        const info = results?.[0]?.result as PageInfo | undefined;
        if (!info?.canSave) { setPageStatus('unavailable'); return; }

        const policyStored = await chrome.storage.local.get('shail_policies');
        const policies = (policyStored['shail_policies'] as SitePolicy[]) ?? [];
        if (isDomainDenied(info.url, policies)) { setPageInfo(info); setPageStatus('denied'); return; }

        const stored = await chrome.storage.local.get(['shail_recent_saves', 'shail_doc_index']);
        const recentSaves = (stored['shail_recent_saves'] as Array<{ url: string; timestamp: string }>) ?? [];
        const index = (stored['shail_doc_index'] as Array<{ sourceUrl?: string; eventType?: string }>) ?? [];
        const alreadySaved = recentSaves.some(e => e.url === info.url) ||
          index.some(e => e.sourceUrl === info.url && (e.eventType === 'page_visit' || e.eventType === 'ai_conversation'));
        setPageInfo(info);
        setPageStatus(alreadySaved ? 'already_saved' : 'ready');
      } catch { setPageStatus('unavailable'); }
    });
  }, []);

  const handleToggleCapture = useCallback(async () => {
    const next = !captureEnabled;
    setCaptureEnabled(next);
    await chrome.storage.local.set({ [KEY_CAPTURE]: next });
    // Sync badge state via background
    chrome.runtime.sendMessage({ type: 'SYNC_PAUSE_BADGE', enabled: next }).catch(() => {});
  }, [captureEnabled]);

  const handleUnpauseConvo = useCallback(async (convId: string) => {
    const next = pausedConvos.filter(id => id !== convId);
    setPausedConvos(next);
    await chrome.storage.local.set({ [KEY_PAUSED_CONVOS]: next });
  }, [pausedConvos]);

  const handleSave = useCallback(async () => {
    if (!pageInfo) return;
    setSaveState('saving');
    try {
      const ts = new Date().toISOString();
      const raw = pageInfo.url + ts;
      const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
      const customId = Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
      const resp = await chrome.runtime.sendMessage({
        type: 'CAPTURE',
        payload: { customId, eventType: 'page_visit', sourceApp: 'web', sourceUrl: pageInfo.url, timestamp: ts, title: pageInfo.title, pageContent: pageInfo.text || pageInfo.preview },
      });
      if (resp?.ok) {
        setSaveState('saved');
        setPageStatus('already_saved');
        const existing = await chrome.storage.local.get('shail_recent_saves');
        const saves = (existing['shail_recent_saves'] as Array<{ url: string; timestamp: string }>) ?? [];
        saves.unshift({ url: pageInfo.url, timestamp: ts });
        await chrome.storage.local.set({ shail_recent_saves: saves.slice(0, 200) });
      } else {
        setSaveState('error');
      }
    } catch { setSaveState('error'); }
  }, [pageInfo]);

  const handlePinAscent = useCallback(async (id: string | null) => {
    setPinnedAscentId(id);
    if (id) await chrome.storage.local.set({ shail_pinned_ascent: id });
    else await chrome.storage.local.remove('shail_pinned_ascent');
  }, []);

  const openPanel = useCallback(async () => {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tab?.id) { await chrome.sidePanel.open({ tabId: tab.id }); window.close(); return; }
      if (tab?.windowId) { await chrome.sidePanel.open({ windowId: tab.windowId }); window.close(); return; }
    } catch { /* ignore */ }
    openSettings();
    window.close();
  }, []);

  const openBasecamp = () => { chrome.tabs.create({ url: 'http://localhost:8000/dashboard' }); window.close(); };

  return (
    <div style={{ width: 320, background: '#000', color: '#fff', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', display: 'flex', flexDirection: 'column' }}>

      {/* ── HEADER ── */}
      <div style={{ padding: '14px 16px 12px', borderBottom: '1px solid #1a1a1a', display: 'flex', alignItems: 'center', gap: 10 }}>
        <img
          src="/icons/icon128.png"
          alt="SHAIL"
          style={{ width: 28, height: 28, borderRadius: 6 }}
          onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
        />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#fff', lineHeight: 1.2 }}>SHAIL</div>
          <div style={{ fontSize: 9, color: '#22c55e', letterSpacing: '0.1em', fontFamily: MONO }}>MEMORY · FOR THE WEB</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {/* Pause / resume toggle */}
          <button
            onClick={handleToggleCapture}
            title={captureEnabled ? 'Pause capture (Ctrl+Shift+P)' : 'Resume capture (Ctrl+Shift+P)'}
            style={{
              padding: '3px 7px', fontSize: 10, borderRadius: 4, cursor: 'pointer', border: '1px solid',
              fontFamily: MONO, letterSpacing: '0.05em',
              background: captureEnabled ? 'transparent' : 'rgba(245,158,11,0.12)',
              color: captureEnabled ? '#555' : '#f59e0b',
              borderColor: captureEnabled ? '#333' : 'rgba(245,158,11,0.4)',
            }}
          >
            {captureEnabled ? '⏸' : '▶'}
          </button>
          {/* Status dot */}
          {backendOk === null
            ? <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#333' }} />
            : !captureEnabled
              ? <><div style={{ width: 6, height: 6, borderRadius: '50%', background: '#f59e0b' }} /><span style={{ fontSize: 9, color: '#f59e0b', fontFamily: MONO }}>PAUSED</span></>
              : backendOk
                ? <><div style={{ width: 6, height: 6, borderRadius: '50%', background: '#22c55e' }} /><span style={{ fontSize: 9, color: '#22c55e', fontFamily: MONO }}>ACTIVE</span></>
                : <><div style={{ width: 6, height: 6, borderRadius: '50%', background: '#ef4444' }} /><span style={{ fontSize: 9, color: '#ef4444', fontFamily: MONO }}>OFFLINE</span></>
          }
        </div>
      </div>

      {/* ── OFFLINE BANNER ── */}
      {backendOk === false && (
        <div style={{ margin: '10px 12px 0', padding: '8px 12px', background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 6, fontSize: 11, color: '#fca5a5' }}>
          Backend offline — run <code style={{ fontFamily: MONO }}>./shailctl start</code>
        </div>
      )}

      <div style={{ padding: '12px 12px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>

        {/* ── CURRENT PAGE ── */}
        {pageInfo && pageStatus !== 'unavailable' && (
          <div>
            <div style={{ fontSize: 9, color: '#22c55e', letterSpacing: '0.1em', fontFamily: MONO, marginBottom: 6 }}>CURRENT PAGE</div>
            <div style={{ background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 8, overflow: 'hidden' }}>
              <div style={{ padding: '10px 12px' }}>
                <div style={{ fontSize: 12, color: '#fff', fontWeight: 500, marginBottom: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {pageInfo.title || 'Untitled'}
                </div>
                <div style={{ fontSize: 10, color: '#555', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {pageInfo.url.replace(/^https?:\/\//, '').split('/')[0]}
                </div>
              </div>
              <div style={{ borderTop: '1px solid #1a1a1a', padding: '8px 12px', display: 'flex', gap: 6 }}>
                {pageStatus === 'denied' ? (
                  <div style={{ fontSize: 10, color: '#ef4444' }}>Site blocked</div>
                ) : pageStatus === 'already_saved' || saveState === 'saved' ? (
                  <div style={{ fontSize: 10, color: '#22c55e' }}>✓ In memory</div>
                ) : saveState === 'error' ? (
                  <button onClick={handleSave} style={{ flex: 1, padding: '5px 0', fontSize: 11, background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 5, color: '#fca5a5', cursor: 'pointer' }}>
                    Failed — retry
                  </button>
                ) : (
                  <button
                    onClick={handleSave}
                    disabled={saveState === 'saving'}
                    style={{ flex: 1, padding: '5px 0', fontSize: 11, background: saveState === 'saving' ? '#111' : '#fff', border: 'none', borderRadius: 5, color: saveState === 'saving' ? '#555' : '#000', fontWeight: 500, cursor: saveState === 'saving' ? 'wait' : 'pointer' }}
                  >
                    {saveState === 'saving' ? 'Saving…' : 'Save to memory'}
                  </button>
                )}
                <button
                  onClick={openPanel}
                  style={{ padding: '5px 10px', fontSize: 11, background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)', borderRadius: 5, color: '#22c55e', cursor: 'pointer' }}
                >
                  Side Panel
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── STATS ROW ── */}
        {stats && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
            {[
              { label: 'THIS WEEK', value: stats.memoriesThisWeek },
              { label: 'TOP SOURCE', value: stats.topSource ? getSourceMeta(stats.topSource as SourceApp).label : '—' },
              { label: 'LAST SAVED', value: stats.lastCaptured ? timeAgo(stats.lastCaptured.timestamp) : '—' },
            ].map(c => (
              <div key={c.label} style={{ background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 6, padding: '8px 10px' }}>
                <div style={{ fontSize: 8, color: '#444', letterSpacing: '0.08em', fontFamily: MONO, marginBottom: 4 }}>{c.label}</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{c.value}</div>
              </div>
            ))}
          </div>
        )}

        {/* ── ACTIVE ASCENT ── */}
        {activeAscent && (
          <div>
            <div style={{ fontSize: 9, color: '#22c55e', letterSpacing: '0.1em', fontFamily: MONO, marginBottom: 6 }}>ACTIVE ASCENT</div>
            <div style={{ background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <div style={{ fontSize: 12, color: '#fff', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, marginRight: 8 }}>
                  {activeAscent.name}
                </div>
                <button
                  onClick={() => handlePinAscent(pinnedAscentId === activeAscent.id ? null : activeAscent.id)}
                  title={pinnedAscentId === activeAscent.id ? 'Unpin widget' : 'Pin widget on page'}
                  style={{
                    padding: '3px 8px', fontSize: 9, background: pinnedAscentId === activeAscent.id ? '#fff' : 'transparent',
                    border: '1px solid #1e1e1e', borderRadius: 4, color: pinnedAscentId === activeAscent.id ? '#000' : '#555',
                    cursor: 'pointer', fontFamily: MONO, letterSpacing: '0.05em',
                  }}
                >
                  {pinnedAscentId === activeAscent.id ? 'PINNED' : 'PIN'}
                </button>
              </div>
              <div style={{ height: 2, background: '#1a1a1a', borderRadius: 1, overflow: 'hidden', marginBottom: 6 }}>
                <div style={{ width: `${Math.round(activeAscent.progress * 100)}%`, height: '100%', background: '#22c55e' }} />
              </div>
              <div style={{ fontSize: 10, color: '#555', fontFamily: MONO }}>
                {activeAscent.todos_completed}/{activeAscent.todo_count} TODOS · {Math.round(activeAscent.progress * 100)}%
              </div>
            </div>
          </div>
        )}

        {/* ── RECENT ── */}
        {stats?.recentCaptures && stats.recentCaptures.length > 0 && (
          <div>
            <div style={{ fontSize: 9, color: '#22c55e', letterSpacing: '0.1em', fontFamily: MONO, marginBottom: 6 }}>RECENT</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {stats.recentCaptures.slice(0, 3).map(r => {
                const meta = getSourceMeta(r.sourceApp as SourceApp);
                return (
                  <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 6 }}>
                    <div style={{ width: 16, height: 16, borderRadius: 3, background: meta.bg, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <span style={{ fontSize: 8, color: meta.color, fontWeight: 700 }}>{meta.label[0]}</span>
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 11, color: '#ccc', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {r.title || r.summary || r.sourceUrl}
                      </div>
                    </div>
                    <div style={{ fontSize: 9, color: '#444', fontFamily: MONO, flexShrink: 0 }}>{timeAgo(r.timestamp)}</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── PAUSED CHATS ── */}
        {pausedConvos.length > 0 && (
          <div>
            <div style={{ fontSize: 9, color: '#f59e0b', letterSpacing: '0.1em', fontFamily: MONO, marginBottom: 6 }}>
              PAUSED CHATS ({pausedConvos.length})
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {pausedConvos.map(convId => (
                <div key={convId} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', background: '#0d0d0d', border: '1px solid rgba(245,158,11,0.2)', borderRadius: 6 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 10, color: '#888', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: MONO }}>
                      {convId.slice(0, 20)}…
                    </div>
                  </div>
                  <button
                    onClick={() => handleUnpauseConvo(convId)}
                    title="Resume capturing this chat"
                    style={{ padding: '2px 7px', fontSize: 9, background: 'transparent', border: '1px solid #333', borderRadius: 4, color: '#555', cursor: 'pointer', fontFamily: MONO, flexShrink: 0 }}
                  >
                    ▶ resume
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>

      {/* ── FOOTER ── */}
      <div style={{ padding: '12px', marginTop: 4 }}>
        <button
          onClick={openBasecamp}
          style={{ width: '100%', padding: '10px 0', fontSize: 12, fontWeight: 600, background: '#fff', color: '#000', border: 'none', borderRadius: 7, cursor: 'pointer' }}
        >
          Open Basecamp →
        </button>
        <div style={{ textAlign: 'center', marginTop: 8, fontSize: 9, color: '#333', fontFamily: MONO }}>
          ^ Space anywhere to search
        </div>
      </div>

    </div>
  );
}

ReactDOM.createRoot(document.getElementById('app')!).render(
  <React.StrictMode><Popup /></React.StrictMode>
);
