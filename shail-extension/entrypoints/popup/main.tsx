import React, { useEffect, useState, useCallback } from 'react';
import ReactDOM from 'react-dom/client';
import { api, getApiKey, AscentSummary } from '../../src/lib/api';
import { getSourceMeta, isDomainDenied } from '../../src/lib/utils';
import type { CaptureSurfaceState, SourceApp, StatsResult, SitePolicy } from '../../src/types/contracts';
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

type SaveState = 'idle' | 'saving' | 'saved' | 'queued' | 'blocked' | 'error';
type ActiveCaptureCache = {
  state: string;
  platform?: string;
  title?: string;
  turnCount: number;
  progressValue?: number;
  memoryId?: string;
  captureSource?: 'api' | 'dom_scroll';
  retroactiveStatus?: string;
  backendState?: CaptureSurfaceState;
  errorText?: string;
};

function captureStageLabel(surface: CaptureSurfaceState | null): string {
  if (!surface) return 'captured';
  if (surface.blueprint.present) return 'blueprint_ready';
  if (surface.blueprint.job_state === 'running') return 'blueprint_extracting';
  if (surface.blueprint.job_state === 'pending') return 'blueprint_queued';
  if (surface.blueprint.job_state === 'failed') return 'failed';
  const stage = surface.pipeline.current_stage || '';
  if (stage === 'embedded' || stage === 'segmented' || stage === 'captured') return stage;
  return stage || 'captured';
}

function detectAiPlatformFromUrl(url?: string): SourceApp | null {
  if (!url) return null;
  try {
    const host = new URL(url).hostname;
    if (host.includes('chat.openai.com') || host.includes('chatgpt.com')) return 'chatgpt';
    if (host.includes('claude.ai')) return 'claude';
    if (host.includes('gemini.google.com') || host.includes('bard.google.com')) return 'gemini';
    if (host.includes('perplexity.ai')) return 'perplexity';
    if (host.includes('grok.com') || host.includes('x.ai')) return 'grok';
  } catch {
    return null;
  }
  return null;
}

function normalizeSourceApp(value?: string): SourceApp | null {
  if (
    value === 'chatgpt' ||
    value === 'claude' ||
    value === 'gemini' ||
    value === 'perplexity' ||
    value === 'grok' ||
    value === 'web'
  ) {
    return value;
  }
  return null;
}

function activeStateLabel(captureEnabled: boolean, activeCapture: ActiveCaptureCache | null, surface: CaptureSurfaceState | null): string {
  if (!captureEnabled) return 'paused';
  if (!activeCapture) return 'ready';
  if (activeCapture.state === 'CAPTURING') return 'capturing';
  if (activeCapture.state === 'SCROLL_PUMP') return activeCapture.retroactiveStatus || 'retroactive_capture';
  if (activeCapture.state === 'ERROR') return 'failed';
  if (activeCapture.retroactiveStatus) return activeCapture.retroactiveStatus;
  return captureStageLabel(surface);
}

function Popup() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [captureEnabled, setCaptureEnabled] = useState<boolean>(true);
  const [pausedConvos, setPausedConvos] = useState<string[]>([]);
  const [stats, setStats] = useState<StatsResult | null>(null);
  const [pageInfo, setPageInfo] = useState<PageInfo | null>(null);
  const [pageStatus, setPageStatus] = useState<'loading' | 'ready' | 'already_saved' | 'denied' | 'unavailable'>('loading');
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [activeAscents, setActiveAscents] = useState<AscentSummary[]>([]);
  const [pinnedAscentId, setPinnedAscentId] = useState<string | null>(null);
  const [bulkStatus, setBulkStatus] = useState<{ isCycling: boolean; completedCount: number; totalInQueue: number; currentUrl: string } | null>(null);
  const [activeCapture, setActiveCapture] = useState<ActiveCaptureCache | null>(null);
  const [captureSurface, setCaptureSurface] = useState<CaptureSurfaceState | null>(null);
  const [activeTabPlatform, setActiveTabPlatform] = useState<SourceApp | null>(null);
  const [retroError, setRetroError] = useState('');

  const refreshActiveTabCaptureState = useCallback(async () => {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const platform = detectAiPlatformFromUrl(tab?.url);
      setActiveTabPlatform(platform);
      if (!tab?.id || !platform) return;
      const response = await chrome.tabs.sendMessage(tab.id, { type: 'GET_ACTIVE_CAPTURE_STATE' });
      if (response?.platform) {
        const capture = response as ActiveCaptureCache;
        setActiveCapture(capture);
        if (capture.backendState) setCaptureSurface(capture.backendState);
        if (capture.errorText) setRetroError(capture.errorText);
      }
    } catch {
      // Content script may not be injected yet; storage cache remains fallback.
    }
  }, []);

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
      setActiveAscents(r.items.filter(a => a.status === 'active'));
    }).catch(() => {});

    // Pinned ascent from storage
    chrome.storage.local.get('shail_pinned_ascent').then(r => {
      setPinnedAscentId((r['shail_pinned_ascent'] as string) ?? null);
    });

    const refreshSurface = async (capture: ActiveCaptureCache | null) => {
      const cached = capture?.backendState ?? null;
      if (cached) setCaptureSurface(cached);
      if (!capture?.memoryId) return;
      try {
        const surface = await api.captureState({ memoryId: capture.memoryId });
        setCaptureSurface(surface);
        const stored = await chrome.storage.local.get('shail_capture_state_cache');
        const cache = (stored['shail_capture_state_cache'] as Record<string, unknown>) ?? {};
        cache[capture.memoryId] = surface;
        await chrome.storage.local.set({ shail_capture_state_cache: cache });
      } catch {
        // Backend might still be writing the raw transcript.
      }
    };

    // Capture state
    chrome.storage.local.get([KEY_CAPTURE, KEY_PAUSED_CONVOS, 'shail_bulk_status', 'shail_active_capture']).then(r => {
      setCaptureEnabled((r[KEY_CAPTURE] as boolean) ?? true);
      setPausedConvos((r[KEY_PAUSED_CONVOS] as string[]) ?? []);
      setBulkStatus((r['shail_bulk_status'] as typeof bulkStatus) ?? null);
      const capture = (r['shail_active_capture'] as ActiveCaptureCache | undefined) ?? null;
      setActiveCapture(capture);
      refreshSurface(capture);
    });

    // Page scrape
    chrome.tabs.query({ active: true, currentWindow: true }).then(async tabs => {
      const tab = tabs[0];
      setActiveTabPlatform(detectAiPlatformFromUrl(tab?.url));
      refreshActiveTabCaptureState();
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

    const onVisibility = () => {
      if (document.visibilityState === 'visible') refreshActiveTabCaptureState();
    };
    document.addEventListener('visibilitychange', onVisibility);

    // Storage updates listener
    const storageListener = (changes: Record<string, chrome.storage.StorageChange>, namespace: string) => {
      if (namespace === 'local') {
        if (changes['shail_doc_index'] || changes['shail_recent_saves']) {
          api.stats().then(setStats).catch(() => {});
        }
        if (changes['shail_bulk_status']) {
          setBulkStatus((changes['shail_bulk_status'].newValue as typeof bulkStatus) ?? null);
        }
        if (changes['shail_active_capture']) {
          const capture = (changes['shail_active_capture'].newValue as ActiveCaptureCache | undefined) ?? null;
          setActiveCapture(capture);
          refreshSurface(capture);
        }
      }
    };
    chrome.storage.onChanged.addListener(storageListener);
    return () => {
      chrome.storage.onChanged.removeListener(storageListener);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [refreshActiveTabCaptureState]);

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
        payload: {
          customId,
          eventType: 'page_visit',
          sourceApp: 'web',
          sourceUrl: pageInfo.url,
          timestamp: ts,
          title: pageInfo.title,
          pageContent: pageInfo.text || pageInfo.preview,
          captureMode: 'active',
          captureInitiator: 'manual',
        },
      });
      const result = resp?.data as { status?: string; memoryId?: string; reason?: string } | undefined;
      if (resp?.ok && result?.memoryId && !['denied', 'duplicate', 'offline_queued', 'error'].includes(result.status ?? '')) {
        setSaveState('saved');
        setPageStatus('already_saved');
      } else if (result?.status === 'duplicate') {
        setSaveState('saved');
        setPageStatus('already_saved');
      } else if (result?.status === 'offline_queued') {
        setSaveState('queued');
      } else if (result?.status === 'denied') {
        setSaveState('blocked');
      } else {
        setSaveState('error');
      }
    } catch { setSaveState('error'); }
  }, [pageInfo]);

  const handleCaptureFullSession = useCallback(async () => {
    setRetroError('');
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tab?.id) {
        const response = await chrome.tabs.sendMessage(tab.id, { type: 'TRIGGER_SCROLL_PUMP' });
        if (response?.state) {
          setActiveCapture(response as ActiveCaptureCache);
        }
        if (response?.retroactiveStatus) {
          setRetroError('');
        }
        if (response?.status && !['started', 'completed'].includes(response.status)) {
          setRetroError(response.reason || 'Retroactive capture could not start');
        }
      }
    } catch {
      setRetroError('Retroactive capture is not available on this tab');
    }
  }, []);

  const handlePinAscent = useCallback(async (id: string | null) => {
    setPinnedAscentId(id);
    if (id) await chrome.storage.local.set({ shail_pinned_ascent: id });
    else await chrome.storage.local.remove('shail_pinned_ascent');
  }, []);

  const openPanel = useCallback(() => {
    chrome.storage.local.set({ shail_focus_search: true });
    chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
      const tab = tabs[0];
      const openWindowPanel = () => {
        if (!tab?.windowId) {
          openSettings();
          window.close();
          return;
        }
        chrome.sidePanel.open({ windowId: tab.windowId })
          .then(() => window.close())
          .catch(() => {
            openSettings();
            window.close();
          });
      };

      if (tab?.id) {
        chrome.sidePanel.open({ tabId: tab.id })
          .then(() => window.close())
          .catch(openWindowPanel);
        return;
      }
      openWindowPanel();
    });
  }, []);

  const openBasecamp = () => { chrome.tabs.create({ url: 'http://localhost:8000/dashboard' }); window.close(); };
  const aiPlatform = activeTabPlatform;
  const tabActiveCapture = aiPlatform && normalizeSourceApp(activeCapture?.platform) === aiPlatform ? activeCapture : null;
  const aiMeta = aiPlatform ? getSourceMeta(aiPlatform) : null;
  const liveLabel = activeStateLabel(captureEnabled, tabActiveCapture, tabActiveCapture ? captureSurface : null);
  const isRetroactiveRunning = tabActiveCapture?.state === 'SCROLL_PUMP';
  const hasAiMemory = !!(tabActiveCapture?.memoryId || captureSurface?.memory_id);
  const retroButtonLabel = isRetroactiveRunning
    ? 'Capturing...'
    : hasAiMemory
      ? 'Update this memory'
      : 'Save to this memory';
  const pageTitle = pageInfo?.title || (pageStatus === 'loading' ? 'Inspecting current page...' : 'Current page');
  const pageHost = pageInfo?.url ? pageInfo.url.replace(/^https?:\/\//, '').split('/')[0] : 'No capturable page detected yet';
  const saveButtonLabel =
    pageStatus === 'loading' ? 'Checking page...' :
    pageStatus === 'unavailable' ? 'Not capturable' :
    pageStatus === 'denied' ? 'Site blocked' :
    pageStatus === 'already_saved' || saveState === 'saved' ? 'Saved to memory' :
    saveState === 'queued' ? 'Queued offline' :
    saveState === 'blocked' ? 'Blocked' :
    saveState === 'error' ? 'Failed - retry' :
    saveState === 'saving' ? 'Saving...' :
    'Save to memory';
  const saveDisabled = pageStatus === 'loading' || pageStatus === 'unavailable' || pageStatus === 'denied' || saveState === 'saving' || pageStatus === 'already_saved' || saveState === 'saved' || saveState === 'queued' || saveState === 'blocked';

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
        <div style={{ margin: '10px 12px 0', padding: '8px 12px', background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 6, fontSize: 11, color: '#fca5a5', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Backend offline — run <code style={{ fontFamily: MONO }}>./shailctl start</code></span>
          <button
            onClick={() => {
              chrome.runtime.sendNativeMessage('com.shail.native_host', { action: 'start_backend' }, (res) => {
                if (chrome.runtime.lastError) {
                  alert('Failed to start backend: ' + chrome.runtime.lastError.message + '\n\nDid you run install.sh in native-host?');
                } else {
                  alert('Backend start initiated: ' + (res?.message || 'Success'));
                  setTimeout(() => window.location.reload(), 2000);
                }
              });
            }}
            style={{
              padding: '4px 8px', background: 'rgba(239,68,68,0.2)', border: 'none', borderRadius: 4,
              color: '#fca5a5', cursor: 'pointer', fontSize: 10, fontWeight: 500
            }}
          >
            Reboot
          </button>
        </div>
      )}

      <div style={{ padding: '12px 12px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>

        {/* ── PRIMARY ACTIONS ── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <button
            onClick={openPanel}
            style={{ padding: '9px 0', fontSize: 12, fontWeight: 700, background: 'rgba(34,197,94,0.14)', border: '1px solid rgba(34,197,94,0.35)', borderRadius: 7, color: '#22c55e', cursor: 'pointer' }}
          >
            Side Panel
          </button>
        </div>

        {/* ── CURRENT PAGE ── */}
        {!aiPlatform && (
        <div>
          <div style={{ fontSize: 9, color: '#22c55e', letterSpacing: '0.1em', fontFamily: MONO, marginBottom: 6 }}>CURRENT PAGE</div>
          <div style={{ background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 8, overflow: 'hidden' }}>
            <div style={{ padding: '10px 12px' }}>
              <div style={{ fontSize: 12, color: '#fff', fontWeight: 500, marginBottom: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {pageTitle}
              </div>
              <div style={{ fontSize: 10, color: '#555', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {pageHost}
              </div>
            </div>
            <div style={{ borderTop: '1px solid #1a1a1a', padding: '8px 12px', display: 'flex', gap: 6 }}>
              <button
                onClick={handleSave}
                disabled={saveDisabled}
                style={{
                  flex: 1,
                  padding: '6px 0',
                  fontSize: 11,
                  background:
                    pageStatus === 'already_saved' || saveState === 'saved' ? 'rgba(34,197,94,0.12)' :
                    saveState === 'queued' ? 'rgba(59,130,246,0.12)' :
                    saveState === 'blocked' ? 'rgba(245,158,11,0.12)' :
                    saveState === 'error' ? 'rgba(239,68,68,0.1)' :
                    saveDisabled ? '#111' : '#fff',
                  border:
                    saveState === 'error' ? '1px solid rgba(239,68,68,0.3)' :
                    saveState === 'queued' ? '1px solid rgba(59,130,246,0.3)' :
                    saveState === 'blocked' ? '1px solid rgba(245,158,11,0.35)' :
                    'none',
                  borderRadius: 5,
                  color:
                    pageStatus === 'already_saved' || saveState === 'saved' ? '#22c55e' :
                    saveState === 'queued' ? '#60a5fa' :
                    saveState === 'blocked' ? '#f59e0b' :
                    saveState === 'error' ? '#fca5a5' :
                    saveDisabled ? '#555' : '#000',
                  fontWeight: 600,
                  cursor: saveDisabled && saveState !== 'error' ? 'default' : 'pointer',
                }}
              >
                {saveButtonLabel}
              </button>
            </div>
          </div>
        </div>
        )}

        {/* ── AI CHAT CAPTURE ── */}
        {aiPlatform && aiMeta && (
          <div>
            <div style={{ fontSize: 9, color: aiMeta.color, letterSpacing: '0.1em', fontFamily: MONO, marginBottom: 6 }}>AI CHAT</div>
            <div style={{ background: '#0d0d0d', border: '1px solid rgba(245, 158, 11, 0.2)', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: captureEnabled ? aiMeta.color : '#f59e0b', animation: captureEnabled ? 'pulse 1.5s infinite' : 'none' }} />
                <div style={{ fontSize: 11, color: '#fff', fontWeight: 500 }}>{liveLabel} · {aiMeta.label.toUpperCase()}</div>
              </div>
              <div style={{ fontSize: 11, color: '#ccc', marginBottom: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {tabActiveCapture?.title || pageInfo?.title || `${aiMeta.label} conversation`}
              </div>
              {isRetroactiveRunning ? (
                <>
                  <div style={{ height: 4, background: '#1a1a1a', borderRadius: 2, overflow: 'hidden', marginBottom: 6 }}>
                    <div style={{
                      width: `${Math.round((tabActiveCapture?.progressValue ?? 0) * 100)}%`,
                      height: '100%',
                      background: 'linear-gradient(90deg, #3b82f6, #22c55e)'
                    }} />
                  </div>
                  <div style={{ fontSize: 10, color: '#888', fontFamily: MONO }}>
                    {tabActiveCapture?.retroactiveStatus || `${tabActiveCapture?.turnCount ?? 0} messages extracted`}
                  </div>
                </>
              ) : (
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <button
                    onClick={handleCaptureFullSession}
                    disabled={isRetroactiveRunning}
                    style={{ flex: 1, padding: '6px 0', fontSize: 11, background: '#3b82f6', border: 'none', borderRadius: 5, color: '#fff', fontWeight: 600, cursor: 'pointer' }}
                  >
                    {retroButtonLabel}
                  </button>
                  <span style={{ fontSize: 10, color: '#888', fontFamily: MONO, whiteSpace: 'nowrap' }}>
                    {tabActiveCapture?.captureSource === 'api' ? 'API capture' :
                     tabActiveCapture?.captureSource === 'dom_scroll' ? 'DOM fallback' :
                     `${tabActiveCapture?.turnCount ?? 0} turns`}
                  </span>
                </div>
              )}
              {tabActiveCapture?.retroactiveStatus && !isRetroactiveRunning && (
                <div style={{ marginTop: 6, fontSize: 10, color: '#93c5fd', lineHeight: 1.4 }}>
                  {tabActiveCapture.retroactiveStatus}
                </div>
              )}
              {retroError && (
                <div style={{ marginTop: 6, fontSize: 10, color: '#fca5a5', lineHeight: 1.4 }}>
                  {retroError}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── BULK HISTORY — PHASE 3 ── */}
        <div>
          <div style={{ fontSize: 9, color: '#3b82f6', letterSpacing: '0.1em', fontFamily: MONO, marginBottom: 6 }}>BULK HISTORY</div>
          <div style={{ background: '#0d0d0d', border: '1px solid rgba(59, 130, 246, 0.16)', borderRadius: 8, padding: '10px 12px' }}>
            {bulkStatus?.isCycling ? (
              <>
                <div style={{ fontSize: 11, color: '#fff', fontWeight: 500, marginBottom: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  Capturing historical sessions...
                </div>
                <div style={{ height: 4, background: '#1a1a1a', borderRadius: 2, overflow: 'hidden', marginBottom: 6 }}>
                  <div style={{
                    width: `${bulkStatus.totalInQueue > 0 ? Math.round((bulkStatus.completedCount / bulkStatus.totalInQueue) * 100) : 0}%`,
                    height: '100%',
                    background: 'linear-gradient(90deg, #3b82f6, #22c55e)'
                  }} />
                </div>
                <div style={{ fontSize: 10, color: '#888', fontFamily: MONO }}>
                  {bulkStatus.completedCount} / {bulkStatus.totalInQueue} captured
                </div>
              </>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11, color: '#ccc', fontWeight: 500 }}>Capture all history</div>
                  <div style={{ fontSize: 10, color: '#555', marginTop: 2 }}>Phase 3 - disabled during active-capture hardening</div>
                </div>
                <button
                  disabled
                  style={{ padding: '5px 10px', fontSize: 10, background: '#111', border: '1px solid #222', borderRadius: 5, color: '#444', cursor: 'not-allowed', flexShrink: 0 }}
                >
                  Later
                </button>
              </div>
            )}
          </div>
        </div>

        {/* ── STATS ROW ── */}
        {stats && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
            {[
              { label: 'LOCAL', value: stats.totalLocalMemories },
              { label: 'THIS WEEK', value: stats.memoriesThisWeek },
              { label: 'TOP SOURCE', value: stats.topSource ? getSourceMeta(stats.topSource as SourceApp).label : '—' },
            ].map(c => (
              <div key={c.label} style={{ background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 6, padding: '8px 10px' }}>
                <div style={{ fontSize: 8, color: '#444', letterSpacing: '0.08em', fontFamily: MONO, marginBottom: 4 }}>{c.label}</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{c.value}</div>
              </div>
            ))}
          </div>
        )}

        {/* ── ACTIVE ASCENTS ── */}
        {activeAscents.length > 0 && (
          <div>
            <div style={{ fontSize: 9, color: '#22c55e', letterSpacing: '0.1em', fontFamily: MONO, marginBottom: 6 }}>
              ACTIVE ASCENT{activeAscents.length > 1 ? 'S' : ''}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {activeAscents.slice(0, 3).map(activeAscent => (
            <div key={activeAscent.id} style={{ background: '#0d0d0d', border: '1px solid #1a1a1a', borderRadius: 8, padding: '10px 12px' }}>
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
            ))}
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
