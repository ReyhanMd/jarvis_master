import React, { useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom/client';
import {
  BrainCircuit, CheckCircle2, ToggleLeft, ToggleRight, AlertCircle,
  Play, Loader2, X, ShieldOff, Shield, Trash2, Plus, Globe, Server,
  User, LogOut, MonitorSmartphone, ExternalLink, LogIn, UserPlus,
} from 'lucide-react';
import type { SitePolicy } from '../../src/types/contracts';
import { api, setAuthCredentials, clearAuthCredentials, getApiKey, getUserId } from '../../src/lib/api';
import './style.css';

const KEY_CAPTURE    = 'shail_capture_enabled';
const KEY_LAST_ERROR = 'shail_last_capture_error';
const KEY_POLICIES   = 'shail_policies';

interface CaptureError { message: string; timestamp: string }

interface BackendInfo {
  status:        'checking' | 'online' | 'offline';
  memoriesCount?: number;
  vectorStore?:   string;
  embeddingModel?: string;
  responseMs?:    number;
}

function Options() {
  const [captureEnabled, setCaptureEnabled] = useState(true);
  const [lastError,      setLastError]      = useState<CaptureError | null>(null);
  const [backendInfo,    setBackendInfo]    = useState<BackendInfo>({ status: 'checking' });

  // ── Account state ──────────────────────────────────────────────────────────
  const [signedIn,       setSignedIn]       = useState<boolean | null>(null); // null = checking
  const [userEmail,      setUserEmail]      = useState('');
  const [userName,       setUserName]       = useState('');
  const [authMode,       setAuthMode]       = useState<'login' | 'register'>('login');
  const [authEmail,      setAuthEmail]      = useState('');
  const [authPassword,   setAuthPassword]   = useState('');
  const [authName,       setAuthName]       = useState('');
  const [authLoading,    setAuthLoading]    = useState(false);
  const [authError,      setAuthError]      = useState('');
  const [addingBrowser,  setAddingBrowser]  = useState(false);
  const [addBrowserMsg,  setAddBrowserMsg]  = useState('');

  // ── Site policies ──────────────────────────────────────────────────────────
  const [policies,     setPolicies]     = useState<SitePolicy[]>([]);
  const [domainInput,  setDomainInput]  = useState('');
  const [domainError,  setDomainError]  = useState('');
  const domainRef = useRef<HTMLInputElement>(null);

  // ── Load from storage ──────────────────────────────────────────────────────
  useEffect(() => {
    browser.storage.local.get([KEY_CAPTURE, KEY_LAST_ERROR, KEY_POLICIES]).then(result => {
      setCaptureEnabled((result[KEY_CAPTURE] as boolean) ?? true);
      setLastError((result[KEY_LAST_ERROR] as CaptureError) ?? null);
      setPolicies((result[KEY_POLICIES] as SitePolicy[]) ?? []);
    });

    // Check sign-in state
    Promise.all([getApiKey(), getUserId()]).then(async ([key, uid]) => {
      if (key && uid) {
        // Verify key is still valid
        try {
          const me = await api.authMe();
          setUserEmail(me.email);
          setUserName(me.name || me.email);
          setSignedIn(true);
        } catch {
          // Key invalid → clear it
          await clearAuthCredentials();
          setSignedIn(false);
        }
      } else {
        setSignedIn(false);
      }
    });

    // Poll for new errors every 3s (background writes them asynchronously)
    const interval = setInterval(() => {
      browser.storage.local.get(KEY_LAST_ERROR).then(r => {
        setLastError((r[KEY_LAST_ERROR] as CaptureError) ?? null);
      });
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  // ── Auth handlers ──────────────────────────────────────────────────────────
  async function handleAuth(e: React.FormEvent) {
    e.preventDefault();
    setAuthLoading(true);
    setAuthError('');
    try {
      let result;
      if (authMode === 'login') {
        result = await api.login(authEmail, authPassword);
      } else {
        result = await api.register(authEmail, authPassword, authName);
      }
      await setAuthCredentials(result.api_key, result.user_id);
      // Clear local cache so sidepanel re-fetches from user's namespace
      await browser.storage.local.remove('shail_doc_index');
      setUserEmail(result.email);
      setUserName(result.name || result.email);
      setSignedIn(true);
      setAuthEmail('');
      setAuthPassword('');
      setAuthName('');
    } catch (err) {
      setAuthError((err as Error).message ?? 'Authentication failed');
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleSignOut() {
    await clearAuthCredentials();
    setSignedIn(false);
    setUserEmail('');
    setUserName('');
  }

  async function handleAddBrowser() {
    setAddingBrowser(true);
    setAddBrowserMsg('');
    try {
      const label = navigator.userAgent.includes('Chrome')
        ? `Chrome — ${new Date().toLocaleDateString()}`
        : `Browser — ${new Date().toLocaleDateString()}`;
      const { key } = await api.addKey(label);
      await setAuthCredentials(key, (await getUserId()) ?? '');
      setAddBrowserMsg('✓ This browser is now linked to your account');
    } catch (err) {
      setAddBrowserMsg(`Failed: ${(err as Error).message}`);
    } finally {
      setAddingBrowser(false);
    }
  }

  // ── Backend health ─────────────────────────────────────────────────────────
  async function pingBackend() {
    setBackendInfo(prev => ({ ...prev, status: 'checking' }));
    const start = Date.now();
    try {
      const res  = await fetch('http://localhost:8000/browser/me', { signal: AbortSignal.timeout(3000) });
      const ms   = Date.now() - start;
      if (res.ok) {
        const data = await res.json();
        setBackendInfo({
          status:        'online',
          memoriesCount: data.memoriesCount,
          vectorStore:   data.vectorStore,
          embeddingModel: data.embeddingModel,
          responseMs:    ms,
        });
      } else {
        setBackendInfo({ status: 'offline' });
      }
    } catch {
      setBackendInfo({ status: 'offline' });
    }
  }

  useEffect(() => { pingBackend(); }, []); // eslint-disable-line

  // ── Capture toggle ─────────────────────────────────────────────────────────
  async function handleToggleCapture() {
    const next = !captureEnabled;
    setCaptureEnabled(next);
    await browser.storage.local.set({ [KEY_CAPTURE]: next });
  }

  async function clearError() {
    await browser.storage.local.remove(KEY_LAST_ERROR);
    setLastError(null);
  }

  // ── Policy helpers ─────────────────────────────────────────────────────────

  function normaliseDomain(raw: string): string {
    // Strip protocol + path, lowercase, remove leading www.
    return raw
      .replace(/^https?:\/\//i, '')
      .replace(/\/.*$/, '')
      .toLowerCase()
      .replace(/^www\./, '')
      .trim();
  }

  function validateDomain(d: string): string {
    if (!d) return 'Enter a domain name';
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(d))
      return 'Invalid domain — use format: example.com';
    if (policies.some(p => p.domain === d))
      return `${d} is already blocked`;
    return '';
  }

  async function addPolicy(domain: string) {
    const err = validateDomain(domain);
    if (err) { setDomainError(err); return; }

    const next: SitePolicy[] = [{ domain, policy: 'DENY' }, ...policies];
    setPolicies(next);
    setDomainInput('');
    setDomainError('');
    await browser.storage.local.set({ [KEY_POLICIES]: next });
    domainRef.current?.focus();
  }

  async function removePolicy(domain: string) {
    const next = policies.filter(p => p.domain !== domain);
    setPolicies(next);
    await browser.storage.local.set({ [KEY_POLICIES]: next });
  }

  async function blockCurrentSite() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const url = tab?.url ?? '';
      if (!url.startsWith('http')) {
        setDomainError('Current tab is not a web page');
        return;
      }
      const domain = normaliseDomain(url);
      setDomainInput(domain);
      setDomainError('');
      await addPolicy(domain);
    } catch {
      setDomainError('Could not read current tab URL');
    }
  }

  return (
    <div className="max-w-lg mx-auto px-6 py-10">

      {/* Header */}
      <div className="flex items-center gap-3 mb-8">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: 'rgba(59,130,246,0.15)' }}>
          <BrainCircuit size={16} className="text-blue-400" />
        </div>
        <div>
          <div className="text-base font-bold text-white">SHAIL Memory</div>
          <div className="text-xs" style={{ color: '#6b7280' }}>Settings</div>
        </div>
      </div>

      {/* ── Last capture error banner ── */}
      {lastError && (
        <div className="rounded-xl p-4 mb-4 flex gap-3"
          style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)' }}>
          <AlertCircle size={14} className="text-red-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="text-[11px] font-semibold text-red-400 mb-0.5">Last capture failed</div>
            <div className="text-[10px] font-mono break-all leading-relaxed" style={{ color: '#f87171' }}>
              {lastError.message}
            </div>
            <div className="text-[9px] mt-1" style={{ color: '#6b7280' }}>
              {new Date(lastError.timestamp).toLocaleTimeString()}
            </div>
          </div>
          <button onClick={clearError} className="flex-shrink-0 opacity-40 hover:opacity-80">
            <X size={12} style={{ color: '#9ca3af' }} />
          </button>
        </div>
      )}

      {/* ── Account ── */}
      <div className="rounded-xl p-5 mb-4" style={{ background: '#13131a', border: '1px solid #1e1e2e' }}>
        <div className="flex items-center gap-2 mb-3">
          <User size={14} style={{ color: '#60a5fa', flexShrink: 0 }} />
          <div className="text-sm font-semibold text-white">Account</div>
        </div>

        {signedIn === null && (
          <div className="flex items-center gap-2 text-[11px]" style={{ color: '#6b7280' }}>
            <Loader2 size={11} className="animate-spin" /> Checking…
          </div>
        )}

        {signedIn === false && (
          <form onSubmit={handleAuth} className="space-y-3">
            <div className="text-[11px] mb-1" style={{ color: '#6b7280' }}>
              Sign in to sync your memories across all your browsers automatically.
            </div>

            {authMode === 'register' && (
              <input
                type="text"
                value={authName}
                onChange={e => setAuthName(e.target.value)}
                placeholder="Your name (optional)"
                className="w-full px-3 py-2 rounded-lg text-sm outline-none font-mono"
                style={{ background: '#0a0a0f', border: '1px solid #1e1e2e', color: '#e5e7eb' }}
              />
            )}

            <input
              type="email"
              value={authEmail}
              onChange={e => setAuthEmail(e.target.value)}
              placeholder="Email"
              required
              className="w-full px-3 py-2 rounded-lg text-sm outline-none"
              style={{ background: '#0a0a0f', border: '1px solid #1e1e2e', color: '#e5e7eb' }}
            />
            <input
              type="password"
              value={authPassword}
              onChange={e => setAuthPassword(e.target.value)}
              placeholder="Password (min 6 chars)"
              required
              className="w-full px-3 py-2 rounded-lg text-sm outline-none"
              style={{ background: '#0a0a0f', border: '1px solid #1e1e2e', color: '#e5e7eb' }}
            />

            {authError && (
              <div className="flex items-center gap-1.5 text-[11px]" style={{ color: '#f87171' }}>
                <AlertCircle size={11} /> {authError}
              </div>
            )}

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={authLoading}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold transition-opacity hover:opacity-90 disabled:opacity-40"
                style={{ background: 'rgba(59,130,246,0.18)', border: '1px solid rgba(59,130,246,0.35)', color: '#60a5fa' }}
              >
                {authLoading ? <Loader2 size={11} className="animate-spin" /> : (authMode === 'login' ? <LogIn size={11} /> : <UserPlus size={11} />)}
                {authMode === 'login' ? 'Sign In' : 'Register'}
              </button>
              <button
                type="button"
                onClick={() => { setAuthMode(m => m === 'login' ? 'register' : 'login'); setAuthError(''); }}
                className="px-3 py-2 rounded-lg text-xs transition-opacity hover:opacity-80"
                style={{ background: '#1e1e2e', color: '#6b7280', border: '1px solid #2d2d3e' }}
              >
                {authMode === 'login' ? 'Create account' : 'Back to sign in'}
              </button>
            </div>
          </form>
        )}

        {signedIn === true && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
              <span className="text-[12px] font-medium text-white">{userEmail}</span>
              {userName && userName !== userEmail && (
                <span className="text-[11px]" style={{ color: '#6b7280' }}>({userName})</span>
              )}
            </div>
            <div className="text-[11px]" style={{ color: '#6b7280' }}>
              Memories sync across all your browsers automatically.
            </div>

            {addBrowserMsg && (
              <div
                className="text-[11px] px-2 py-1 rounded"
                style={{ color: addBrowserMsg.startsWith('✓') ? '#34d399' : '#f87171', background: addBrowserMsg.startsWith('✓') ? 'rgba(52,211,153,0.08)' : 'rgba(248,113,113,0.08)' }}
              >
                {addBrowserMsg}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleSignOut}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-opacity hover:opacity-80"
                style={{ background: '#1e1e2e', border: '1px solid #2d2d3e', color: '#9ca3af' }}
              >
                <LogOut size={11} /> Sign Out
              </button>
              <button
                onClick={handleAddBrowser}
                disabled={addingBrowser}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-opacity hover:opacity-80 disabled:opacity-40"
                style={{ background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.25)', color: '#60a5fa' }}
              >
                {addingBrowser ? <Loader2 size={11} className="animate-spin" /> : <MonitorSmartphone size={11} />}
                Add This Browser
              </button>
              <a
                href="http://localhost:8000/dashboard"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-opacity hover:opacity-80"
                style={{ background: '#1e1e2e', border: '1px solid #2d2d3e', color: '#9ca3af' }}
              >
                <ExternalLink size={11} /> Dashboard
              </a>
            </div>
          </div>
        )}
      </div>

      {/* ── SHAIL Backend Status ── */}
      <div className="rounded-xl p-5 mb-4" style={{ background: '#13131a', border: '1px solid #1e1e2e' }}>
        <div className="flex items-center gap-2 mb-3">
          <Server size={14} style={{ color: '#60a5fa', flexShrink: 0 }} />
          <div className="text-sm font-semibold text-white">SHAIL Backend</div>
          <div className="ml-auto flex items-center gap-1.5">
            {backendInfo.status === 'checking' && (
              <><Loader2 size={11} className="animate-spin text-amber-400" /><span className="text-[11px] text-amber-400">Connecting…</span></>
            )}
            {backendInfo.status === 'online' && (
              <><div className="w-1.5 h-1.5 rounded-full bg-green-500" /><span className="text-[11px] text-green-400 font-medium">Connected</span></>
            )}
            {backendInfo.status === 'offline' && (
              <><div className="w-1.5 h-1.5 rounded-full bg-red-500" /><span className="text-[11px] text-red-400 font-medium">Offline</span></>
            )}
          </div>
        </div>

        {backendInfo.status === 'online' && (
          <div className="space-y-2 mb-3">
            <div className="flex items-center justify-between text-[11px]">
              <span style={{ color: '#6b7280' }}>Endpoint</span>
              <span className="font-mono" style={{ color: '#9ca3af' }}>localhost:8000</span>
            </div>
            {backendInfo.memoriesCount !== undefined && (
              <div className="flex items-center justify-between text-[11px]">
                <span style={{ color: '#6b7280' }}>Memories stored</span>
                <span className="font-semibold text-white">{backendInfo.memoriesCount.toLocaleString()}</span>
              </div>
            )}
            {backendInfo.vectorStore && (
              <div className="flex items-center justify-between text-[11px]">
                <span style={{ color: '#6b7280' }}>Vector store</span>
                <span className="font-mono" style={{ color: '#9ca3af' }}>{backendInfo.vectorStore}</span>
              </div>
            )}
            {backendInfo.embeddingModel && (
              <div className="flex items-center justify-between text-[11px]">
                <span style={{ color: '#6b7280' }}>Embedding model</span>
                <span className="font-mono" style={{ color: '#9ca3af' }}>{backendInfo.embeddingModel}</span>
              </div>
            )}
            {backendInfo.responseMs !== undefined && (
              <div className="flex items-center justify-between text-[11px]">
                <span style={{ color: '#6b7280' }}>Response time</span>
                <span className="font-semibold" style={{ color: backendInfo.responseMs < 500 ? '#34d399' : '#f59e0b' }}>
                  {backendInfo.responseMs}ms
                </span>
              </div>
            )}
          </div>
        )}

        {backendInfo.status === 'offline' && (
          <div
            className="rounded-lg px-3 py-2.5 mb-3 text-[11px] leading-relaxed font-mono"
            style={{ background: '#0d0d14', border: '1px solid #1e1e2e', color: '#6b7280' }}
          >
            <div className="text-white text-[10px] font-sans font-medium mb-1">Start the backend:</div>
            cd ~/jarvis_master && python -m uvicorn apps.shail.main:app --port 8000
          </div>
        )}

        <button
          onClick={pingBackend}
          disabled={backendInfo.status === 'checking'}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-opacity hover:opacity-80 disabled:opacity-40"
          style={{ background: '#1e1e2e', color: '#9ca3af', border: '1px solid #2d2d3e' }}
        >
          {backendInfo.status === 'checking'
            ? <><Loader2 size={11} className="animate-spin" />Checking…</>
            : <><Play size={11} />Test Connection</>
          }
        </button>

        {backendInfo.status === 'online' && backendInfo.responseMs !== undefined && (
          <div className="flex items-center gap-1.5 mt-2 text-[10px]" style={{ color: '#374151' }}>
            <CheckCircle2 size={10} className="text-green-500" />
            Last checked just now
          </div>
        )}
      </div>

      {/* ── Capture toggle ── */}
      <div className="rounded-xl p-5"
        style={{ background: '#13131a', border: '1px solid #1e1e2e' }}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-white mb-0.5">Capture memories</div>
            <div className="text-[11px]" style={{ color: '#6b7280' }}>
              When off, the extension stops saving new memories from any site.
            </div>
          </div>
          <button onClick={handleToggleCapture} className="flex-shrink-0 ml-4 transition-opacity hover:opacity-80">
            {captureEnabled
              ? <ToggleRight size={28} className="text-blue-400" />
              : <ToggleLeft size={28} style={{ color: '#374151' }} />
            }
          </button>
        </div>
      </div>

      {/* ── Site Policies ── */}
      <div className="rounded-xl p-5 mt-4"
        style={{ background: '#13131a', border: '1px solid #1e1e2e' }}>

        {/* Header */}
        <div className="flex items-center gap-2 mb-1">
          <ShieldOff size={14} className="text-red-400 flex-shrink-0" />
          <div className="text-sm font-semibold text-white">Site Policies</div>
        </div>
        <div className="text-[11px] mb-4" style={{ color: '#6b7280' }}>
          Domains listed below will never be captured — no memories, no prompts.
        </div>

        {/* Blocked-domain list */}
        {policies.length === 0 ? (
          <div
            className="flex items-center gap-2 px-3 py-4 rounded-lg text-[11px] mb-4"
            style={{ background: '#0d0d14', border: '1px dashed #1e1e2e', color: '#374151' }}
          >
            <Shield size={13} style={{ flexShrink: 0 }} />
            No blocked domains yet — all sites are captured.
          </div>
        ) : (
          <div className="rounded-lg overflow-hidden mb-4" style={{ border: '1px solid #1e1e2e' }}>
            {policies.map((p, i) => (
              <div
                key={p.domain}
                className="flex items-center gap-3 px-3 py-2.5 group"
                style={{
                  background: i % 2 === 0 ? '#0d0d14' : '#13131a',
                  borderTop: i > 0 ? '1px solid #1e1e2e' : 'none',
                }}
              >
                {/* Domain */}
                <Globe size={11} style={{ color: '#4b5563', flexShrink: 0 }} />
                <span className="flex-1 text-[12px] font-mono text-white truncate">
                  {p.domain}
                </span>

                {/* Policy badge */}
                <span
                  className="flex-shrink-0 text-[9px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full"
                  style={{
                    background: 'rgba(239,68,68,0.12)',
                    color: '#f87171',
                    border: '1px solid rgba(239,68,68,0.2)',
                  }}
                >
                  {p.policy}
                </span>

                {/* Remove */}
                <button
                  onClick={() => removePolicy(p.domain)}
                  title={`Remove ${p.domain}`}
                  className="flex-shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-all opacity-0 group-hover:opacity-100"
                  style={{
                    background: 'rgba(239,68,68,0.08)',
                    border: '1px solid rgba(239,68,68,0.15)',
                    color: '#f87171',
                  }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLButtonElement).style.background = 'rgba(239,68,68,0.18)';
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLButtonElement).style.background = 'rgba(239,68,68,0.08)';
                  }}
                >
                  <Trash2 size={10} /> Remove
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Add domain row */}
        <div className="space-y-2">
          <div className="text-[11px] font-medium" style={{ color: '#9ca3af' }}>
            Block a domain:
          </div>
          <div className="flex gap-2">
            <div
              className="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg"
              style={{
                background: '#0a0a0f',
                border: `1px solid ${domainError ? 'rgba(239,68,68,0.4)' : '#1e1e2e'}`,
                transition: 'border-color 0.15s',
              }}
            >
              <Globe size={12} style={{ color: '#374151', flexShrink: 0 }} />
              <input
                ref={domainRef}
                type="text"
                value={domainInput}
                onChange={e => { setDomainInput(e.target.value); setDomainError(''); }}
                onKeyDown={e => {
                  if (e.key === 'Enter') addPolicy(normaliseDomain(domainInput));
                }}
                placeholder="example.com"
                className="flex-1 bg-transparent text-sm placeholder-gray-700 outline-none font-mono"
                style={{ color: '#e5e7eb' }}
                spellCheck={false}
              />
              {domainInput && (
                <button
                  onClick={() => { setDomainInput(''); setDomainError(''); }}
                  className="opacity-40 hover:opacity-80"
                >
                  <X size={11} style={{ color: '#9ca3af' }} />
                </button>
              )}
            </div>

            {/* + Block button */}
            <button
              onClick={() => addPolicy(normaliseDomain(domainInput))}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-opacity hover:opacity-90"
              style={{
                background: 'rgba(239,68,68,0.12)',
                border: '1px solid rgba(239,68,68,0.25)',
                color: '#f87171',
              }}
            >
              <Plus size={12} /> Block
            </button>
          </div>

          {/* Inline validation error */}
          {domainError && (
            <div className="flex items-center gap-1.5 text-[11px]" style={{ color: '#f87171' }}>
              <AlertCircle size={11} />
              {domainError}
            </div>
          )}

          {/* Block current site shortcut */}
          <button
            onClick={blockCurrentSite}
            className="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium transition-all hover:opacity-90"
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: '1px dashed #2d2d3e',
              color: '#6b7280',
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = '#4b5563';
              (e.currentTarget as HTMLButtonElement).style.color = '#9ca3af';
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = '#2d2d3e';
              (e.currentTarget as HTMLButtonElement).style.color = '#6b7280';
            }}
          >
            <ShieldOff size={12} />
            Block current site
          </button>
          <div className="text-[10px] text-center" style={{ color: '#374151' }}>
            Instantly blocks the domain of whichever tab you have open right now
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-6 text-[11px] text-center" style={{ color: '#374151' }}>
        All memories are stored locally on your device — nothing leaves your machine.
      </div>

    </div>
  );
}

ReactDOM.createRoot(document.getElementById('app')!).render(
  <React.StrictMode>
    <Options />
  </React.StrictMode>
);
