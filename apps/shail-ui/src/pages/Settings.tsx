import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, CaptureSettings, LLMSettings } from '../api';
import { clearAuth, getProfile } from '../auth';
import { AnonymousSyncModal } from '../components/AnonymousSyncModal';
import { flag } from '../lib/featureFlags';

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const CARD = { background: '#0d0d0d', border: '1px solid #161616', borderRadius: 9 } as const;

const SECTIONS = [
  { id: 'general',  label: 'General' },
  { id: 'memory',   label: 'Memory' },
  { id: 'capture',  label: 'Capture' },
  { id: 'ai',       label: 'AI Model' },
  { id: 'sources',  label: 'Sources' },
  { id: 'privacy',  label: 'Privacy' },
  { id: 'account',  label: 'Account' },
];

const FREE_TIER_MEMORY_CAP = 500;
const PROVIDER_DEFAULTS: Record<string, string> = {
  ollama: 'gemma3:4b-it-q4_K_M',
  openai: 'gpt-4o-mini',
  anthropic: 'claude-haiku-4-5-20251001',
};

function SyncAnonSection() {
  const [count, setCount]           = useState<number | null>(null);
  const [showModal, setShowModal]   = useState(false);

  useEffect(() => {
    api.anonymousCount().then(r => setCount(r.count)).catch(() => setCount(0));
  }, []);

  const handleDone = useCallback(() => {
    setShowModal(false);
    api.anonymousCount().then(r => setCount(r.count)).catch(() => setCount(0));
  }, []);

  if (count === null || count === 0) return null;

  return (
    <>
      <div style={{ background: '#0d0d0d', border: '1px solid #161616', borderRadius: 9, padding: 18 }}>
        <div style={{ fontSize: 13, color: '#fff', marginBottom: 4 }}>Sync pre-login memories</div>
        <div style={{ fontSize: 12, color: '#666', marginBottom: 14 }}>
          {count} {count === 1 ? 'memory was' : 'memories were'} captured before you signed in and are
          stored locally without an account tag. Sync them to your account anytime.
        </div>
        <button
          onClick={() => setShowModal(true)}
          style={{ padding: '7px 14px', fontSize: 12, background: 'transparent', border: '1px solid #1f1f1f', color: '#aaa', borderRadius: 6, cursor: 'pointer' }}
        >
          Review &amp; sync ({count})
        </button>
      </div>
      {showModal && <AnonymousSyncModal onDone={handleDone} />}
    </>
  );
}

function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        width: 38, height: 22, borderRadius: 12,
        background: checked ? '#fff' : '#1f1f1f', border: 'none',
        position: 'relative', cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'background 0.15s', opacity: disabled ? 0.4 : 1, flexShrink: 0,
      }}
    >
      <span style={{
        position: 'absolute', top: 2, left: checked ? 18 : 2,
        width: 18, height: 18, borderRadius: '50%',
        background: checked ? '#000' : '#666', transition: 'left 0.15s',
      }} />
    </button>
  );
}

function Row({ label, hint, control, dimmed }: { label: string; hint?: string; control: React.ReactNode; dimmed?: boolean }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
      padding: '14px 0', borderBottom: '1px solid #131313', gap: 20,
      opacity: dimmed ? 0.5 : 1,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: '#fff' }}>{label}</div>
        {hint && <div style={{ marginTop: 4, fontSize: 11, color: '#666', lineHeight: 1.45 }}>{hint}</div>}
      </div>
      <div style={{ flexShrink: 0 }}>{control}</div>
    </div>
  );
}

export function Settings() {
  const navigate = useNavigate();
  const { email, name } = getProfile();
  const [settings, setSettings] = useState<CaptureSettings | null>(null);
  const [stats, setStats] = useState<{ totalMemories: number } | null>(null);
  const [llm, setLLM] = useState<LLMSettings | null>(null);

  const [provider, setProvider] = useState<'ollama' | 'openai' | 'anthropic'>('ollama');
  const [model, setModel] = useState('');
  const [openaiKey, setOpenaiKey] = useState('');
  const [anthropicKey, setAnthropicKey] = useState('');
  const [showOpenAI, setShowOpenAI] = useState(false);
  const [showAnthropic, setShowAnthropic] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ provider: string; ok: boolean; info: string } | null>(null);

  const [domainInput, setDomainInput] = useState('');
  const [showManageDomains, setShowManageDomains] = useState(false);
  const [showClearModal, setShowClearModal] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [endpointMs, setEndpointMs] = useState<number | null>(null);

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => setSettings(null));
    api.stats().then(setStats).catch(() => setStats(null));
    api.llmSettings().then(s => {
      setLLM(s);
      setProvider(s.active_provider);
      setModel(s.active_model || PROVIDER_DEFAULTS[s.active_provider] || '');
    }).catch(() => setLLM(null));
    pingBackend();
  }, []);

  const pingBackend = async () => {
    const t0 = performance.now();
    try {
      const r = await fetch('http://localhost:8000/health');
      if (r.ok) setEndpointMs(Math.round(performance.now() - t0));
    } catch { setEndpointMs(null); }
  };

  const setSettingsField = async <K extends keyof CaptureSettings>(key: K, value: CaptureSettings[K]) => {
    if (!settings) return;
    const next = { ...settings, [key]: value };
    setSettings(next);
    try { await api.putSettings({ [key]: value }); } catch { /* */ }
  };

  const addDomain = async () => {
    if (!settings || !domainInput.trim()) return;
    const next = [...settings.blocked_domains, domainInput.trim().toLowerCase()];
    await setSettingsField('blocked_domains', Array.from(new Set(next)));
    setDomainInput('');
  };

  const removeDomain = async (d: string) => {
    if (!settings) return;
    await setSettingsField('blocked_domains', settings.blocked_domains.filter(x => x !== d));
  };

  const saveLLM = async () => {
    const body: Partial<{ active_provider: string; active_model: string; openai_api_key: string; anthropic_api_key: string }> = {
      active_provider: provider, active_model: model,
    };
    if (openaiKey)    body.openai_api_key = openaiKey;
    if (anthropicKey) body.anthropic_api_key = anthropicKey;
    try {
      const updated = await api.putLLMSettings(body);
      setLLM(updated);
      setOpenaiKey(''); setAnthropicKey('');
    } catch { /* */ }
  };

  const testProvider = async (p: 'ollama' | 'openai' | 'anthropic') => {
    setTesting(p);
    setTestResult(null);
    try {
      const apiKey = p === 'openai' ? openaiKey : p === 'anthropic' ? anthropicKey : '';
      const r = await api.testLLM({ provider: p, api_key: apiKey, model: PROVIDER_DEFAULTS[p] });
      setTestResult({ provider: p, ok: r.ok, info: r.info });
    } catch (e) {
      setTestResult({ provider: p, ok: false, info: (e as Error).message });
    }
    setTesting(null);
  };

  const handleClearAll = async () => {
    if (!stats) return;
    setClearing(true);
    try {
      const all = await api.search({ query: '', k: 500 });
      await Promise.allSettled(all.items.map(m => api.deleteMemory(m.id)));
      api.stats().then(setStats);
    } catch { /* */ }
    setClearing(false);
    setShowClearModal(false);
  };

  const handleSignOut = () => { clearAuth(); navigate('/'); };

  const totalMem = stats?.totalMemories ?? 0;
  const memPct = Math.min(100, (totalMem / FREE_TIER_MEMORY_CAP) * 100);

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
      <aside style={{ width: 180, padding: '32px 12px 32px 32px', borderRight: '1px solid #111', flexShrink: 0 }}>
        {SECTIONS.map(s => (
          <a key={s.id} href={`#${s.id}`} style={{
            display: 'block', padding: '8px 12px', fontSize: 12, color: '#666',
            textDecoration: 'none', borderRadius: 5,
          }}>
            {s.label}
          </a>
        ))}
        <div style={{ marginTop: 24, fontSize: 10, color: '#3a3a3a', fontFamily: MONO, padding: '0 12px' }}>
          v 0.2.0<br />build 2026.05
        </div>
      </aside>

      <div style={{ flex: 1, overflowY: 'auto', padding: '32px 40px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 36 }}>
          <div style={{
            width: 44, height: 44, background: '#1a1a1a', borderRadius: 8,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 18, fontWeight: 600, color: '#fff', flexShrink: 0,
          }}>
            {(name || email || 'U')[0].toUpperCase()}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, color: '#fff', fontWeight: 500 }}>{name || email.split('@')[0] || 'User'}</div>
            <div style={{ marginTop: 3, fontSize: 12, color: '#666' }}>
              {email || 'no email'} {llm ? <>· <span style={{ color: '#888' }}>{llm.active_provider} active</span></> : ''}
            </div>
          </div>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            padding: '4px 10px', background: '#0d0d0d', border: '1px solid #1a1a1a',
            borderRadius: 12, fontSize: 10, color: '#22c55e', fontFamily: MONO, letterSpacing: '0.06em',
          }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#22c55e' }} />
            SYNCED
          </span>
        </div>

        <section id="general" style={{ marginBottom: 40 }}>
          <h2 style={{ margin: '0 0 14px', fontSize: 11, fontWeight: 600, color: '#3a3a3a', letterSpacing: '0.12em', fontFamily: MONO }}>GENERAL</h2>
          <p style={{ margin: '0 0 14px', fontSize: 12, color: '#666' }}>Behavior, appearance, and basics.</p>
          <div style={{ ...CARD, padding: '0 18px' }}>
            <Row label="Launch at login" hint="macOS app only — install ShailUI.app to enable" control={<Toggle checked={false} onChange={() => {}} disabled />} dimmed />
            <Row label="Menu bar" hint="macOS app only — show the SHAIL mountain in the menu bar" control={<Toggle checked={false} onChange={() => {}} disabled />} dimmed />
            <Row
              label="Capture memories"
              hint="When off, SHAIL stops indexing new pages and conversations."
              control={<Toggle checked={!!settings?.capture_enabled} onChange={v => setSettingsField('capture_enabled', v)} />}
            />
            <Row
              label="Backend endpoint"
              hint={`Where SHAIL talks to its memory engine.${endpointMs !== null ? `  ·  ${endpointMs}ms response` : ''}`}
              control={
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <code style={{ padding: '5px 10px', background: '#1a1a1a', borderRadius: 5, fontSize: 11, color: '#aaa', fontFamily: MONO }}>localhost:8000</code>
                  <button onClick={pingBackend} style={{ padding: '5px 10px', fontSize: 11, background: 'transparent', border: '1px solid #1f1f1f', borderRadius: 5, color: '#888', cursor: 'pointer' }}>Test</button>
                </div>
              }
            />
            {!flag('ui_v2') && (
              <Row
                label="Site policies"
                hint="Domains in this list are never captured. No memories, no prompts."
                control={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {(settings?.blocked_domains || []).slice(0, 2).map(d => (
                      <code key={d} style={{ padding: '4px 8px', background: '#1a1a1a', borderRadius: 4, fontSize: 10, color: '#aaa', fontFamily: MONO }}>{d}</code>
                    ))}
                    {(settings?.blocked_domains.length ?? 0) > 2 && (
                      <code style={{ padding: '4px 8px', background: '#1a1a1a', borderRadius: 4, fontSize: 10, color: '#aaa', fontFamily: MONO }}>+ {(settings!.blocked_domains.length) - 2} more</code>
                    )}
                    <button onClick={() => setShowManageDomains(true)} style={{ padding: '5px 10px', fontSize: 11, background: 'transparent', border: '1px solid #1f1f1f', borderRadius: 5, color: '#aaa', cursor: 'pointer' }}>Manage</button>
                  </div>
                }
              />
            )}
          </div>
        </section>

        <section id="memory" style={{ marginBottom: 40 }}>
          <h2 style={{ margin: '0 0 14px', fontSize: 11, fontWeight: 600, color: '#3a3a3a', letterSpacing: '0.12em', fontFamily: MONO }}>MEMORY</h2>
          <div style={{ ...CARD, padding: 18 }}>
            <div style={{ fontSize: 13, color: '#fff', marginBottom: 6 }}>Free-tier memory cap</div>
            <div style={{ fontSize: 11, color: '#666', marginBottom: 14 }}>
              Up to {FREE_TIER_MEMORY_CAP} memories on the free tier. Older memories will be auto-pruned past the cap.
            </div>
            <div style={{ height: 6, background: '#161616', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${memPct}%`, height: '100%', background: memPct > 90 ? '#ef4444' : '#fff', transition: 'width 0.3s' }} />
            </div>
            <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#666', fontFamily: MONO }}>
              <span>{totalMem} / {FREE_TIER_MEMORY_CAP}</span>
              <span>{Math.round(memPct)}%</span>
            </div>
          </div>
        </section>

        <section id="capture" style={{ marginBottom: 40 }}>
          <h2 style={{ margin: '0 0 14px', fontSize: 11, fontWeight: 600, color: '#3a3a3a', letterSpacing: '0.12em', fontFamily: MONO }}>CAPTURE</h2>
          <div style={{ ...CARD, padding: '0 18px' }}>
            <Row
              label="Auto-capture AI conversations"
              hint="ChatGPT, Claude, Gemini, Perplexity. Per-source toggles arrive in v2."
              control={<Toggle checked={!!settings?.capture_enabled} onChange={v => setSettingsField('capture_enabled', v)} />}
            />
            <Row
              label="Auto-capture web pages"
              hint="Articles and reader-mode-extractable pages."
              control={<Toggle checked={!!settings?.capture_enabled} onChange={v => setSettingsField('capture_enabled', v)} />}
            />
          </div>
        </section>

        <section id="ai" style={{ marginBottom: 40 }}>
          <h2 style={{ margin: '0 0 14px', fontSize: 11, fontWeight: 600, color: '#3a3a3a', letterSpacing: '0.12em', fontFamily: MONO }}>AI MODEL</h2>
          <p style={{ margin: '0 0 14px', fontSize: 12, color: '#666' }}>
            Choose which model SHAIL uses for chat and ascent plan generation. Local Ollama runs free with no key. Add an OpenAI or Anthropic key to use paid providers — SHAIL falls back to Ollama if a paid call fails.
          </p>
          <div style={{ ...CARD, padding: 18 }}>
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, color: '#666', marginBottom: 6, fontFamily: MONO, letterSpacing: '0.05em' }}>PROVIDER</div>
              <select
                value={provider}
                onChange={e => {
                  const p = e.target.value as 'ollama' | 'openai' | 'anthropic';
                  setProvider(p);
                  setModel(PROVIDER_DEFAULTS[p]);
                }}
                style={{
                  width: '100%', padding: '8px 12px', fontSize: 13,
                  background: '#0a0a0a', border: '1px solid #1f1f1f', borderRadius: 6,
                  color: '#fff', outline: 'none',
                }}
              >
                <option value="ollama">Ollama (local — Gemma 3, free)</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </div>

            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, color: '#666', marginBottom: 6, fontFamily: MONO, letterSpacing: '0.05em' }}>MODEL</div>
              <input
                value={model}
                onChange={e => setModel(e.target.value)}
                placeholder={PROVIDER_DEFAULTS[provider]}
                style={{
                  width: '100%', padding: '8px 12px', fontSize: 13,
                  background: '#0a0a0a', border: '1px solid #1f1f1f', borderRadius: 6,
                  color: '#fff', outline: 'none', fontFamily: MONO,
                }}
              />
            </div>

            {provider === 'openai' && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 11, color: '#666', marginBottom: 6, fontFamily: MONO, letterSpacing: '0.05em' }}>
                  OPENAI API KEY {llm?.openai_configured && <span style={{ color: '#22c55e' }}>· stored</span>}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    type={showOpenAI ? 'text' : 'password'}
                    value={openaiKey}
                    onChange={e => setOpenaiKey(e.target.value)}
                    placeholder={llm?.openai_configured ? '(key on file — leave blank to keep)' : 'sk-...'}
                    style={{
                      flex: 1, padding: '8px 12px', fontSize: 13,
                      background: '#0a0a0a', border: '1px solid #1f1f1f', borderRadius: 6,
                      color: '#fff', outline: 'none', fontFamily: MONO,
                    }}
                  />
                  <button onClick={() => setShowOpenAI(s => !s)} style={{ padding: '0 12px', fontSize: 11, background: 'transparent', border: '1px solid #1f1f1f', borderRadius: 6, color: '#666', cursor: 'pointer' }}>{showOpenAI ? 'Hide' : 'Show'}</button>
                  <button onClick={() => testProvider('openai')} disabled={!openaiKey || testing === 'openai'} style={{
                    padding: '0 14px', fontSize: 11, background: 'transparent',
                    border: '1px solid #1f1f1f', borderRadius: 6,
                    color: !openaiKey ? '#3a3a3a' : '#aaa',
                    cursor: !openaiKey || testing === 'openai' ? 'not-allowed' : 'pointer',
                  }}>{testing === 'openai' ? '…' : 'Test'}</button>
                </div>
              </div>
            )}

            {provider === 'anthropic' && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 11, color: '#666', marginBottom: 6, fontFamily: MONO, letterSpacing: '0.05em' }}>
                  ANTHROPIC API KEY {llm?.anthropic_configured && <span style={{ color: '#22c55e' }}>· stored</span>}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    type={showAnthropic ? 'text' : 'password'}
                    value={anthropicKey}
                    onChange={e => setAnthropicKey(e.target.value)}
                    placeholder={llm?.anthropic_configured ? '(key on file — leave blank to keep)' : 'sk-ant-...'}
                    style={{
                      flex: 1, padding: '8px 12px', fontSize: 13,
                      background: '#0a0a0a', border: '1px solid #1f1f1f', borderRadius: 6,
                      color: '#fff', outline: 'none', fontFamily: MONO,
                    }}
                  />
                  <button onClick={() => setShowAnthropic(s => !s)} style={{ padding: '0 12px', fontSize: 11, background: 'transparent', border: '1px solid #1f1f1f', borderRadius: 6, color: '#666', cursor: 'pointer' }}>{showAnthropic ? 'Hide' : 'Show'}</button>
                  <button onClick={() => testProvider('anthropic')} disabled={!anthropicKey || testing === 'anthropic'} style={{
                    padding: '0 14px', fontSize: 11, background: 'transparent',
                    border: '1px solid #1f1f1f', borderRadius: 6,
                    color: !anthropicKey ? '#3a3a3a' : '#aaa',
                    cursor: !anthropicKey || testing === 'anthropic' ? 'not-allowed' : 'pointer',
                  }}>{testing === 'anthropic' ? '…' : 'Test'}</button>
                </div>
              </div>
            )}

            {provider === 'ollama' && (
              <div style={{ padding: '10px 12px', background: '#0a0a0a', border: '1px solid #1a1a1a', borderRadius: 6, marginBottom: 14, fontSize: 11, color: '#888' }}>
                No key needed. Ensure Ollama is running and the model is pulled (<code style={{ fontFamily: MONO }}>ollama pull {model || PROVIDER_DEFAULTS.ollama}</code>).
                <button onClick={() => testProvider('ollama')} disabled={testing === 'ollama'} style={{
                  marginLeft: 12, padding: '4px 10px', fontSize: 10,
                  background: 'transparent', border: '1px solid #1f1f1f', borderRadius: 5,
                  color: '#aaa', cursor: 'pointer', fontFamily: MONO,
                }}>{testing === 'ollama' ? '…' : 'Test'}</button>
              </div>
            )}

            {testResult && (
              <div style={{
                padding: '8px 12px', borderRadius: 6, marginBottom: 14, fontSize: 11,
                background: testResult.ok ? '#0a1a0d' : '#1a0808',
                border: `1px solid ${testResult.ok ? '#1c5e2d' : '#3a1010'}`,
                color: testResult.ok ? '#86efac' : '#ef9a9a',
                fontFamily: MONO,
              }}>
                {testResult.provider.toUpperCase()}: {testResult.ok ? '✓ ' : '✗ '}{testResult.info}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontSize: 11, color: '#666' }}>
                {llm && (
                  <>Active: <span style={{ color: '#aaa', fontFamily: MONO }}>{llm.active_provider}</span> · {llm.active_model || '(default)'}</>
                )}
              </div>
              <button onClick={saveLLM} style={{
                padding: '7px 16px', fontSize: 12, background: '#fff', color: '#000',
                border: 'none', borderRadius: 6, fontWeight: 500, cursor: 'pointer',
              }}>Save model settings</button>
            </div>
          </div>
        </section>

        <section id="sources" style={{ marginBottom: 40 }}>
          <h2 style={{ margin: '0 0 14px', fontSize: 11, fontWeight: 600, color: '#3a3a3a', letterSpacing: '0.12em', fontFamily: MONO }}>SOURCES</h2>
          <div style={{ ...CARD, padding: 18 }}>
            <div style={{ fontSize: 13, color: '#fff', marginBottom: 4 }}>External sources</div>
            <div style={{ fontSize: 12, color: '#666', marginBottom: 14 }}>
              Connect external services like Google Drive, Notion, GitHub.
            </div>
            <button onClick={() => navigate('/connections')} style={{
              padding: '6px 14px', fontSize: 12, background: 'transparent',
              border: '1px solid #1f1f1f', color: '#aaa', borderRadius: 6, cursor: 'pointer',
            }}>Open Connections →</button>
          </div>
        </section>

        <section id="privacy" style={{ marginBottom: 40 }}>
          <h2 style={{ margin: '0 0 14px', fontSize: 11, fontWeight: 600, color: '#3a3a3a', letterSpacing: '0.12em', fontFamily: MONO }}>PRIVACY</h2>
          {flag('ui_v2') && (
            <div style={{ ...CARD, padding: '0 18px', marginBottom: 10 }}>
              <Row
                label="Pause all capture"
                hint="Temporarily stop indexing new conversations and pages. Existing memories are unaffected."
                control={<Toggle checked={!settings?.capture_enabled} onChange={v => setSettingsField('capture_enabled', !v)} />}
              />
              <Row
                label="Local-only mode"
                hint="Memories stay on your device. No data sent to the cloud sync layer. Disables cross-device search."
                control={
                  <Toggle
                    checked={localStorage.getItem('shail_local_only') === '1'}
                    onChange={v => {
                      if (v) localStorage.setItem('shail_local_only', '1');
                      else localStorage.removeItem('shail_local_only');
                    }}
                  />
                }
              />
              <Row
                label="Blocked sites"
                hint="Domains on this list are never captured. Takes effect immediately."
                control={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {(settings?.blocked_domains || []).slice(0, 2).map(d => (
                      <code key={d} style={{ padding: '4px 8px', background: '#1a1a1a', borderRadius: 4, fontSize: 10, color: '#aaa', fontFamily: MONO }}>{d}</code>
                    ))}
                    {(settings?.blocked_domains.length ?? 0) > 2 && (
                      <code style={{ padding: '4px 8px', background: '#1a1a1a', borderRadius: 4, fontSize: 10, color: '#aaa', fontFamily: MONO }}>
                        +{settings!.blocked_domains.length - 2} more
                      </code>
                    )}
                    <button onClick={() => setShowManageDomains(true)} style={{ padding: '5px 10px', fontSize: 11, background: 'transparent', border: '1px solid #1f1f1f', borderRadius: 5, color: '#aaa', cursor: 'pointer' }}>Manage</button>
                  </div>
                }
              />
            </div>
          )}
          <div style={{ ...CARD, padding: 18, marginBottom: 10 }}>
            <div style={{ fontSize: 13, color: '#fff', marginBottom: 4 }}>Clear all memories</div>
            <div style={{ fontSize: 12, color: '#666', marginBottom: 14 }}>
              Permanently delete every memory in your account. This cannot be undone.
            </div>
            <button onClick={() => setShowClearModal(true)} style={{
              padding: '7px 14px', fontSize: 12, background: 'transparent',
              border: '1px solid #3a1010', color: '#ef4444', borderRadius: 6, cursor: 'pointer',
            }}>
              Clear all data
            </button>
          </div>
          <SyncAnonSection />
        </section>

        <section id="account" style={{ marginBottom: 60 }}>
          <h2 style={{ margin: '0 0 14px', fontSize: 11, fontWeight: 600, color: '#3a3a3a', letterSpacing: '0.12em', fontFamily: MONO }}>ACCOUNT</h2>
          <div style={{ ...CARD, padding: 18 }}>
            <Row
              label="Sign out"
              hint="Clears the API key from this browser. Memories stay on the backend."
              control={<button onClick={handleSignOut} style={{
                padding: '6px 14px', fontSize: 12, background: 'transparent',
                border: '1px solid #1f1f1f', color: '#aaa', borderRadius: 6, cursor: 'pointer',
              }}>Sign out</button>}
            />
          </div>
        </section>
      </div>

      {showManageDomains && settings && (
        <div onClick={() => setShowManageDomains(false)} style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)', zIndex: 100,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div onClick={e => e.stopPropagation()} style={{
            width: 480, maxWidth: '92%', background: '#0d0d0d',
            border: '1px solid #1f1f1f', borderRadius: 12, padding: '28px 32px',
          }}>
            <h3 style={{ margin: '0 0 14px', fontSize: 16, fontWeight: 500, color: '#fff' }}>
              Blocked domains
            </h3>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
              <input
                value={domainInput} onChange={e => setDomainInput(e.target.value)}
                placeholder="banking.com"
                onKeyDown={e => e.key === 'Enter' && addDomain()}
                style={{
                  flex: 1, padding: '8px 12px', fontSize: 12,
                  background: '#0a0a0a', border: '1px solid #1f1f1f', borderRadius: 6,
                  color: '#fff', outline: 'none', fontFamily: MONO,
                }}
              />
              <button onClick={addDomain} disabled={!domainInput.trim()} style={{
                padding: '8px 14px', fontSize: 12,
                background: domainInput.trim() ? '#fff' : '#1a1a1a',
                color: domainInput.trim() ? '#000' : '#555',
                border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 500,
              }}>Add</button>
            </div>
            <div style={{ maxHeight: 220, overflowY: 'auto' }}>
              {settings.blocked_domains.length === 0 && (
                <div style={{ color: '#3a3a3a', fontSize: 12 }}>No domains blocked.</div>
              )}
              {settings.blocked_domains.map(d => (
                <div key={d} style={{
                  display: 'flex', justifyContent: 'space-between', padding: '8px 0',
                  borderBottom: '1px solid #131313',
                }}>
                  <code style={{ fontSize: 12, color: '#aaa', fontFamily: MONO }}>{d}</code>
                  <button onClick={() => removeDomain(d)} style={{
                    background: 'none', border: 'none', color: '#666', cursor: 'pointer', fontSize: 12,
                  }}>Remove</button>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 16, textAlign: 'right' }}>
              <button onClick={() => setShowManageDomains(false)} style={{
                padding: '7px 16px', fontSize: 12, background: '#1a1a1a',
                border: '1px solid #1f1f1f', color: '#fff', borderRadius: 6, cursor: 'pointer',
              }}>Done</button>
            </div>
          </div>
        </div>
      )}

      {showClearModal && (
        <div onClick={() => setShowClearModal(false)} style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)', zIndex: 100,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div onClick={e => e.stopPropagation()} style={{
            width: 420, background: '#0d0d0d', border: '1px solid #1f1f1f',
            borderRadius: 12, padding: '32px 36px',
          }}>
            <h3 style={{ margin: '0 0 12px', fontSize: 16, color: '#fff', fontWeight: 500 }}>Delete all memories?</h3>
            <p style={{ margin: '0 0 24px', fontSize: 13, color: '#888', lineHeight: 1.55 }}>
              This will permanently delete all {totalMem} memories. This cannot be undone.
            </p>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setShowClearModal(false)} style={{
                flex: 1, padding: '9px 0', fontSize: 13, background: 'transparent',
                border: '1px solid #1e1e1e', color: '#666', borderRadius: 6, cursor: 'pointer',
              }}>Cancel</button>
              <button onClick={handleClearAll} disabled={clearing} style={{
                flex: 1, padding: '9px 0', fontSize: 13, fontWeight: 600,
                background: '#ef4444', border: 'none', color: '#fff', borderRadius: 6, cursor: 'pointer',
              }}>{clearing ? 'Deleting…' : 'Delete all'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
