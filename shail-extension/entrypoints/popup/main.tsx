import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import {
  BrainCircuit, Globe, Loader2, Sparkles, Star, Search, ExternalLink,
  ChevronRight, BookOpen, Video, Code2, FileText, Image, Music,
  CheckCircle2, X, Save, SkipForward, AlertCircle, Link2, Copy,
} from 'lucide-react';
import { api, getApiKey } from '../../src/lib/api';
import { timeAgo, getSourceMeta } from '../../src/lib/utils';
import type { MemoryRecord, SourceApp, StatsResult } from '../../src/types/contracts';
import './style.css';

function openSettings() { chrome.runtime.openOptionsPage(); }

// ─── Page info extracted from active tab ────────────────────────────────────

interface PageInfo {
  title:       string;
  url:         string;
  text:        string;        // full extractable text
  preview:     string;        // ~150 char display snippet
  contentType: 'article' | 'video' | 'document' | 'code' | 'image' | 'audio' | 'social' | 'other';
  wordCount:   number;
  canSave:     boolean;
}

// ── Self-contained extraction fn — injected into the active tab via executeScript
// No imports allowed here. Uses only DOM APIs.
function extractPageContent(): PageInfo {
  const title = document.title || '';
  const url   = location.href;

  // ── Content-type detection ────────────────────────────────────────────────
  type CT = PageInfo['contentType'];
  let contentType: CT = 'article';

  if (/youtube\.com\/watch|youtu\.be\//.test(url))             contentType = 'video';
  else if (/vimeo\.com\/\d/.test(url))                         contentType = 'video';
  else if (/drive\.google\.com|docs\.google\.com/.test(url))   contentType = 'document';
  else if (/office\.com|sharepoint\.com/.test(url))            contentType = 'document';
  else if (/github\.com\/[^/]+\/[^/]/.test(url))              contentType = 'code';
  else if (/codepen\.io|codesandbox\.io|replit\.com/.test(url)) contentType = 'code';
  else if (/twitter\.com|x\.com|reddit\.com|linkedin\.com/.test(url)) contentType = 'social';
  else if (/soundcloud\.com|spotify\.com/.test(url))           contentType = 'audio';
  else if (/\.(jpg|jpeg|png|gif|svg|webp)(\?.*)?$/i.test(url)) contentType = 'image';
  else if (/\.(pdf)(\?.*)?$/i.test(url))                       contentType = 'document';

  // ── Blocked pages ─────────────────────────────────────────────────────────
  if (!url.startsWith('http')) {
    return { title, url, text: '', preview: '', contentType: 'other', wordCount: 0, canSave: false };
  }

  let text = '';

  // ── YouTube ───────────────────────────────────────────────────────────────
  if (contentType === 'video' && url.includes('youtube.com')) {
    const parts: string[] = [];
    const t = document.querySelector('h1.ytd-video-primary-info-renderer yt-formatted-string, h1 .yt-core-attributed-string');
    if (t) parts.push((t as HTMLElement).innerText?.trim() ?? title);
    const ch = document.querySelector('#channel-name yt-formatted-string, #owner-name a');
    if (ch) parts.push('Channel: ' + ((ch as HTMLElement).innerText?.trim() ?? ''));
    const desc = document.querySelector('#description-inline-expander, ytd-text-inline-expander, #description-text');
    if (desc) parts.push(((desc as HTMLElement).innerText?.trim() ?? '').slice(0, 800));
    text = parts.filter(Boolean).join('\n\n');
  }

  // ── GitHub ────────────────────────────────────────────────────────────────
  if (!text && contentType === 'code') {
    const readme = document.querySelector('.markdown-body, article.markdown-body');
    const repoDesc = document.querySelector('.repository-content p, .f4.my-3');
    const code = document.querySelector('.blob-code-content, .highlight pre');
    text = [
      (readme   as HTMLElement | null)?.innerText?.trim()?.slice(0, 1500) ?? '',
      (repoDesc as HTMLElement | null)?.innerText?.trim() ?? '',
      (code     as HTMLElement | null)?.innerText?.trim()?.slice(0, 500) ?? '',
    ].filter(Boolean).join('\n\n');
  }

  // ── Generic extraction ────────────────────────────────────────────────────
  if (!text) {
    const SELECTORS = [
      'main', 'article', '[role="main"]',
      '.post-content', '.article-content', '.entry-content',
      '.content-area', '#content', '.prose',
    ];
    let el: Element | null = null;
    for (const s of SELECTORS) {
      el = document.querySelector(s);
      if (el) break;
    }

    if (el) {
      text = (el as HTMLElement).innerText?.trim()?.slice(0, 3000) ?? '';
    } else {
      // Strip nav/header/footer noise then grab body text
      const clone = document.body.cloneNode(true) as HTMLElement;
      for (const tag of ['script', 'style', 'nav', 'header', 'footer', '[role="navigation"]', '[role="banner"]']) {
        clone.querySelectorAll(tag).forEach(n => n.remove());
      }
      text = clone.innerText?.trim()?.slice(0, 3000) ?? '';
    }
  }

  // Clean
  text = text.replace(/[\t ]{2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  const wordCount = text ? text.split(/\s+/).filter(Boolean).length : 0;

  // Preview — prefer og:description, then first meaningful text
  const ogDesc  = document.querySelector('meta[property="og:description"], meta[name="description"]')?.getAttribute('content') ?? '';
  const preview = (ogDesc || text).slice(0, 160).trim();

  const canSave = text.length >= 80 || preview.length >= 40;

  return { title, url, text, preview, contentType, wordCount, canSave };
}

// ─── Source icon ─────────────────────────────────────────────────────────────

function SourceIcon({ app, size = 16 }: { app: SourceApp; size?: number }) {
  const props = { size, strokeWidth: 1.8 };
  switch (app) {
    case 'chatgpt':    return <BrainCircuit {...props} />;
    case 'claude':     return <Sparkles {...props} />;
    case 'gemini':     return <Star {...props} />;
    case 'perplexity': return <Search {...props} />;
    default:           return <Globe {...props} />;
  }
}

// ─── Content-type icon + label ────────────────────────────────────────────────

function ContentTypeIcon({ type, size = 12 }: { type: PageInfo['contentType']; size?: number }) {
  const p = { size, strokeWidth: 1.8 };
  switch (type) {
    case 'video':    return <Video    {...p} />;
    case 'document': return <FileText {...p} />;
    case 'code':     return <Code2    {...p} />;
    case 'image':    return <Image    {...p} />;
    case 'audio':    return <Music    {...p} />;
    case 'social':   return <Link2    {...p} />;
    default:         return <BookOpen {...p} />;
  }
}

const CT_LABEL: Record<PageInfo['contentType'], string> = {
  article:  'Article',
  video:    'Video',
  document: 'Document',
  code:     'Code',
  image:    'Image',
  audio:    'Audio',
  social:   'Social',
  other:    'Page',
};

const CT_COLOR: Record<PageInfo['contentType'], string> = {
  article:  '#60a5fa',
  video:    '#f87171',
  document: '#34d399',
  code:     '#a78bfa',
  image:    '#fb923c',
  audio:    '#f472b6',
  social:   '#facc15',
  other:    '#6b7280',
};

// ─── Stat card ────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="flex-1 rounded-lg p-2.5" style={{ background: '#13131a', border: '1px solid #1e1e2e' }}>
      <div className="text-[9px] text-gray-500 uppercase tracking-wider mb-1">{label}</div>
      <div className="text-xs font-semibold text-white leading-tight">{value}</div>
      {sub && <div className="text-[9px] text-gray-600 mt-0.5 truncate">{sub}</div>}
    </div>
  );
}

// ─── Recent memory card (expandable click-through) ────────────────────────────

function RecentCard({ record }: { record: MemoryRecord }) {
  const meta = getSourceMeta(record.sourceApp);
  const [expanded,  setExpanded]  = useState(false);
  const [fullText,  setFullText]  = useState<string | null>(null);
  const [loading,   setLoading]   = useState(false);
  const [copied,    setCopied]    = useState(false);

  async function handleExpand(e: React.MouseEvent) {
    e.stopPropagation();
    if (!expanded && !fullText) {
      setLoading(true);
      try {
        const { content } = await api.getFullContent(record.id);
        // Strip the "[sourceApp] Title\n\n" header then clean up
        const bodyStart = content.indexOf('\n\n');
        const body = bodyStart > 0 ? content.slice(bodyStart + 2) : content;
        setFullText(body.replace(/\n{3,}/g, '\n\n').trim().slice(0, 1500));
      } catch {
        setFullText(record.summary);
      } finally {
        setLoading(false);
      }
    }
    setExpanded(v => !v);
  }

  function handleCopy(e: React.MouseEvent) {
    e.stopPropagation();
    navigator.clipboard.writeText(fullText || record.summary);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        background: '#13131a', border: `1px solid ${expanded ? 'rgba(59,130,246,0.3)' : '#1e1e2e'}`,
        transition: 'border-color 0.15s',
      }}
    >
      {/* Header row — always visible, click to expand */}
      <div
        className="flex items-start gap-2 px-2.5 py-2 cursor-pointer"
        onClick={handleExpand}
      >
        <div
          className="flex-shrink-0 w-5 h-5 rounded flex items-center justify-center mt-0.5"
          style={{ background: meta.bg, color: meta.color }}
        >
          <SourceIcon app={record.sourceApp} size={10} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] text-gray-300 leading-snug line-clamp-1">
            {record.title || record.summary}
          </div>
          <div className="flex items-center gap-1 mt-0.5">
            <span className="text-[8px] font-medium px-1 py-0.5 rounded" style={{ background: meta.bg, color: meta.color }}>
              {meta.label}
            </span>
            <span className="text-[9px] text-gray-600">{timeAgo(record.timestamp)}</span>
          </div>
        </div>
        <div className="flex-shrink-0 ml-1 mt-0.5 opacity-30 hover:opacity-60">
          <ChevronRight
            size={11}
            className="text-gray-400 transition-transform"
            style={{ transform: expanded ? 'rotate(90deg)' : 'none' }}
          />
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div style={{ borderTop: '1px solid #1e1e2e' }}>
          {loading ? (
            <div className="flex items-center justify-center gap-1.5 py-3">
              <Loader2 size={11} className="animate-spin text-gray-600" />
              <span className="text-[10px]" style={{ color: '#374151' }}>Loading…</span>
            </div>
          ) : (
            <>
              <div
                className="px-2.5 py-2 text-[10px] leading-relaxed"
                style={{
                  color: '#9ca3af', maxHeight: 180, overflowY: 'auto',
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                }}
              >
                {fullText || record.summary}
              </div>
              <div
                className="flex items-center gap-1.5 px-2.5 py-1.5"
                style={{ borderTop: '1px solid #1e1e2e' }}
              >
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded transition-opacity hover:opacity-80"
                  style={{ background: '#1e1e2e', color: '#9ca3af', border: '1px solid #2d2d3e' }}
                >
                  <Copy size={9} />{copied ? 'Copied!' : 'Copy'}
                </button>
                <a
                  href={record.sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={e => e.stopPropagation()}
                  className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded transition-opacity hover:opacity-80"
                  style={{ background: '#1e1e2e', color: '#6b7280', border: '1px solid #2d2d3e', textDecoration: 'none' }}
                >
                  <ExternalLink size={9} />Open URL
                </a>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`rounded animate-pulse ${className}`} style={{ background: '#1e1e2e' }} />;
}

// ─── Page scrape card ─────────────────────────────────────────────────────────

type SaveState = 'idle' | 'saving' | 'saved' | 'skipped' | 'error';

function PageScrapeCard({ info, onSave, onSkip, saveState }: {
  info: PageInfo;
  onSave: () => void;
  onSkip: () => void;
  saveState: SaveState;
}) {
  const color = CT_COLOR[info.contentType];

  if (saveState === 'skipped') return null;

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        background: '#0d0d14',
        border: `1px solid ${saveState === 'saved' ? 'rgba(34,197,94,0.35)' : '#1e1e2e'}`,
        transition: 'border-color 0.2s',
      }}
    >
      {/* Label row */}
      <div
        className="flex items-center gap-2 px-3 py-2"
        style={{ borderBottom: '1px solid #1e1e2e', background: '#13131a' }}
      >
        <div
          className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-widest"
          style={{ color }}
        >
          <ContentTypeIcon type={info.contentType} size={10} />
          {CT_LABEL[info.contentType]}
        </div>
        <span className="text-[9px] ml-auto" style={{ color: '#374151' }}>
          {info.wordCount > 0 ? `~${info.wordCount} words` : 'Current page'}
        </span>
      </div>

      {/* Title + preview */}
      <div className="px-3 pt-2.5 pb-2">
        <div className="text-[11px] font-semibold text-white leading-snug line-clamp-1 mb-1">
          {info.title || 'Untitled page'}
        </div>
        <div className="text-[10px] leading-relaxed line-clamp-3" style={{ color: '#6b7280' }}>
          {info.preview || 'No preview available'}
        </div>
      </div>

      {/* Actions */}
      <div
        className="flex items-center gap-2 px-3 py-2"
        style={{ borderTop: '1px solid #1e1e2e' }}
      >
        {saveState === 'saved' ? (
          <div className="flex items-center gap-1.5 text-xs font-medium w-full justify-center" style={{ color: '#86efac' }}>
            <CheckCircle2 size={13} />
            Saved to memory!
          </div>
        ) : saveState === 'error' ? (
          <div className="flex items-center gap-1.5 text-xs font-medium" style={{ color: '#fca5a5' }}>
            <AlertCircle size={13} />
            Save failed — retry?
          </div>
        ) : (
          <>
            <button
              onClick={onSave}
              disabled={saveState === 'saving'}
              className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-[11px] font-semibold transition-all disabled:opacity-60"
              style={{
                background: 'rgba(59,130,246,0.12)',
                border: '1px solid rgba(59,130,246,0.25)',
                color: '#60a5fa',
              }}
            >
              {saveState === 'saving'
                ? <><Loader2 size={11} className="animate-spin" /> Saving…</>
                : <><Save size={11} /> Save to Memory</>
              }
            </button>
            <button
              onClick={onSkip}
              disabled={saveState === 'saving'}
              className="flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all"
              style={{
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid #1e1e2e',
                color: '#4b5563',
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLButtonElement).style.color = '#9ca3af';
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLButtonElement).style.color = '#4b5563';
              }}
            >
              <SkipForward size={11} /> Skip
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Main popup ───────────────────────────────────────────────────────────────

type BackendStatus = 'checking' | 'online' | 'offline';

function Popup() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('checking');
  const [stats,         setStats]         = useState<StatsResult | null>(null);
  const [pageInfo,      setPageInfo]      = useState<PageInfo | null>(null);
  const [pageLoad,      setPageLoad]      = useState<'loading' | 'ready' | 'already_saved' | 'failed'>('loading');
  const [saveState,     setSaveState]     = useState<SaveState>('idle');
  const [isSignedIn,    setIsSignedIn]    = useState<boolean | null>(null);

  // ── Load stats (instant, local only) + non-blocking health ping ───────────
  useEffect(() => {
    // Stats from localStorage — near-instant, no network
    api.stats()
      .then(data => setStats(data))
      .catch(() => { /* localStorage always succeeds */ });

    // Check auth state
    getApiKey().then(key => setIsSignedIn(!!key));

    // Non-blocking health ping — just updates the status dot
    fetch('http://localhost:8000/browser/me', { signal: AbortSignal.timeout(2000) })
      .then(r => setBackendStatus(r.ok ? 'online' : 'offline'))
      .catch(() => setBackendStatus('offline'));

    // Page scrape
    chrome.tabs.query({ active: true, currentWindow: true }).then(async tabs => {
      const tab = tabs[0];
      if (!tab?.id) { setPageLoad('failed'); return; }

      try {
        const results = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func:   extractPageContent,
        });
        const info = results?.[0]?.result as PageInfo | undefined;
        if (!info || !info.canSave) {
          setPageLoad('failed'); // chrome:// page, new tab, etc.
          return;
        }

        // ── Dedup check: is this URL already in memory? ──────────────────────
        // If yes, show "Already saved" — don't prompt the user at all.
        const stored  = await chrome.storage.local.get('shail_doc_index');
        const index   = (stored['shail_doc_index'] as Array<{
          sourceUrl?: string; eventType?: string;
        }>) ?? [];
        const alreadySaved = index.some(
          e => e.sourceUrl === info.url && e.eventType === 'page_visit'
        );

        setPageInfo(info);
        setPageLoad(alreadySaved ? 'already_saved' : 'ready');
      } catch {
        setPageLoad('failed'); // scripting permission denied
      }
    });
  }, []);

  // ── Save the current page ─────────────────────────────────────────────────
  async function handleSave() {
    if (!pageInfo) return;
    setSaveState('saving');

    try {
      const ts = new Date().toISOString();
      // Simple unique ID: base on URL + timestamp
      const raw = pageInfo.url + ts;
      const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
      const customId = Array.from(new Uint8Array(buf))
        .map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16);

      const resp = await chrome.runtime.sendMessage({
        type: 'CAPTURE',
        payload: {
          customId,
          eventType: 'page_visit',
          sourceApp: 'web',
          sourceUrl: pageInfo.url,
          timestamp: ts,
          title: pageInfo.title,
          pageContent: pageInfo.text || pageInfo.preview,
        },
      });

      if (resp?.ok) {
        setSaveState('saved');
      } else {
        setSaveState('error');
      }
    } catch {
      setSaveState('error');
    }
  }

  // ── Open side panel ───────────────────────────────────────────────────────
  async function openPanel() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tab?.id) {
        try {
          await chrome.sidePanel.open({ tabId: tab.id });
          window.close(); return;
        } catch { /* fall through */ }
      }
      if (tab?.windowId) {
        await chrome.sidePanel.open({ windowId: tab.windowId });
        window.close(); return;
      }
    } catch { /* ignore */ }
    openSettings();
    window.close();
  }

  return (
    <div className="w-80 flex flex-col" style={{ background: '#0a0a0f', minHeight: 120 }}>

      {/* ── Header ── */}
      <div
        className="flex items-center justify-between px-3 py-2.5"
        style={{ borderBottom: '1px solid #1e1e2e' }}
      >
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded flex items-center justify-center" style={{ background: 'rgba(59,130,246,0.15)' }}>
            <BrainCircuit size={12} className="text-blue-400" />
          </div>
          <span className="text-xs font-semibold text-white tracking-wide">SHAIL Memory</span>
        </div>
        <div className="flex items-center gap-3">
          {backendStatus === 'checking'
            ? <Loader2 size={10} className="text-amber-500 animate-spin" />
            : backendStatus === 'online'
              ? <><div className="w-1.5 h-1.5 rounded-full bg-green-500" /><span className="text-[10px] text-green-500 font-medium">Active</span></>
              : <><div className="w-1.5 h-1.5 rounded-full bg-red-500" /><span className="text-[10px] text-red-500 font-medium">Offline</span></>
          }
          <button onClick={openSettings} className="opacity-30 hover:opacity-70 transition-opacity">
            <ExternalLink size={11} className="text-gray-400" />
          </button>
        </div>
      </div>

      {/* ── Offline banner ── (doesn't replace content, just a slim warning) */}
      {backendStatus === 'offline' && (
        <div
          className="mx-3 mt-2.5 flex items-center gap-2 px-2.5 py-2 rounded-lg text-[10px]"
          style={{
            background: 'rgba(239,68,68,0.06)',
            border: '1px solid rgba(239,68,68,0.15)',
            color: '#fca5a5',
          }}
        >
          <AlertCircle size={11} style={{ flexShrink: 0 }} />
          <span>Backend offline — start SHAIL to save new memories</span>
        </div>
      )}

      {/* ── Sign-in CTA (when not authenticated) ── */}
      {isSignedIn === false && (
        <div
          className="mx-3 mt-2.5 flex items-center gap-2 px-2.5 py-2.5 rounded-lg text-[10px]"
          style={{
            background: 'rgba(59,130,246,0.06)',
            border: '1px solid rgba(59,130,246,0.18)',
            color: '#93c5fd',
          }}
        >
          <BrainCircuit size={11} style={{ flexShrink: 0 }} />
          <div className="flex-1 leading-snug">Sign in to sync memories across all your browsers.</div>
          <button
            onClick={openSettings}
            className="flex items-center gap-1 text-[10px] font-medium text-blue-400 hover:text-blue-300 whitespace-nowrap"
          >
            Sign in →
          </button>
        </div>
      )}

      {/* ── Body ── */}
      <div className="flex flex-col gap-2.5 p-3">

          {/* ── Current page scrape ── */}
          {pageInfo && pageLoad !== 'failed' && saveState !== 'skipped' && (
            <>
              <div className="text-[9px] uppercase tracking-widest flex items-center gap-1.5" style={{ color: '#374151' }}>
                <Globe size={8} /> Current page
              </div>

              {/* Already saved — just a quiet badge, no prompt */}
              {pageLoad === 'already_saved' ? (
                <div
                  className="flex items-center gap-2 px-3 py-2.5 rounded-xl text-[11px]"
                  style={{
                    background: 'rgba(34,197,94,0.06)',
                    border: '1px solid rgba(34,197,94,0.2)',
                    color: '#86efac',
                  }}
                >
                  <CheckCircle2 size={13} style={{ flexShrink: 0 }} />
                  <div className="min-w-0">
                    <div className="font-medium leading-snug">Already in memory</div>
                    <div className="text-[10px] opacity-60 truncate" style={{ color: '#86efac' }}>
                      {pageInfo.title || pageInfo.url}
                    </div>
                  </div>
                </div>
              ) : (
                /* Not yet saved — show Save/Skip card */
                <PageScrapeCard
                  info={pageInfo}
                  onSave={handleSave}
                  onSkip={() => setSaveState('skipped')}
                  saveState={saveState}
                />
              )}

              <div className="h-px" style={{ background: '#1e1e2e' }} />
            </>
          )}

          {/* ── Stats ── */}
          {stats && (
            <>
              <div className="flex gap-1.5">
                <StatCard label="This week"  value={stats.memoriesThisWeek} sub="memories" />
                <StatCard label="Top source" value={stats.topSource ? getSourceMeta(stats.topSource).label : '—'} />
                <StatCard label="Last saved" value={stats.lastCaptured ? timeAgo(stats.lastCaptured.timestamp) : '—'} />
              </div>

              {/* ── Recent captures ── */}
              {stats.recentCaptures.length > 0 && (
                <div>
                  <div className="text-[9px] uppercase tracking-widest mb-1.5 px-0.5" style={{ color: '#374151' }}>
                    Recent
                  </div>
                  <div className="flex flex-col gap-1">
                    {stats.recentCaptures.slice(0, 3).map(r => (
                      <RecentCard key={r.id} record={r} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

      {/* ── Open panel CTA ── */}
      <div className="px-3 pb-3 pt-1 space-y-1.5">
          <button
            onClick={openPanel}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-xs font-semibold text-white transition-opacity hover:opacity-90 active:opacity-75"
            style={{ background: 'linear-gradient(135deg, #3b82f6, #2563eb)' }}
          >
            Open Memory Panel
            <ChevronRight size={13} />
          </button>
          <div className="text-center text-[9px]" style={{ color: '#1e1e2e' }}>
            or press <span style={{ color: '#374151' }}>⌃Space</span> anywhere
          </div>
        </div>

    </div>
  );
}

// ─── Mount ────────────────────────────────────────────────────────────────────

ReactDOM.createRoot(document.getElementById('app')!).render(
  <React.StrictMode>
    <Popup />
  </React.StrictMode>
);
