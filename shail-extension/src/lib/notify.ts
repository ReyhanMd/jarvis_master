/**
 * notify.ts — Shadow DOM capture-prompt toast.
 * Runs inside content scripts (no React, no Tailwind).
 * Uses Shadow DOM so the host page's CSS cannot touch it.
 *
 * Layout:
 *   ● CHATGPT        SHAIL  ×
 *   Worth saving this memory?
 *   --- Saved article: title…
 *   [💾 Save]  [Capture session ▶]  [Skip]
 *   ▬▬▬▬▬▬ auto-dismiss progress bar
 */

import type { SourceApp } from '../types/contracts';

export interface NotifyOptions {
  title:           string;
  sourceApp:       SourceApp;
  onSave:          () => void;
  onSkip:          () => void;
  conversationId?: string;   // if set, shows "Pause this chat" button
  autoDismissMs?:  number;
}

let activeCleanup: (() => void) | null = null;

function getAppLabel(app: SourceApp): string {
  const map: Record<SourceApp, string> = {
    chatgpt: 'ChatGPT', claude: 'Claude', gemini: 'Gemini',
    perplexity: 'Perplexity', web: 'Web Page',
  };
  return map[app] ?? 'AI';
}

function getAppColor(app: SourceApp): string {
  const map: Record<SourceApp, string> = {
    chatgpt: '#10a37f', claude: '#d97706', gemini: '#4285f4',
    perplexity: '#7c3aed', web: '#22c55e',
  };
  return map[app] ?? '#22c55e';
}

const WIDGET_CSS = `
  *,*::before,*::after { box-sizing: border-box; margin: 0; padding: 0; }

  .shail-card {
    position: fixed;
    top: 16px;
    right: 16px;
    z-index: 2147483647;
    width: 300px;
    background: #000;
    border: 1px solid #222;
    border-radius: 12px;
    padding: 14px 14px 10px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    box-shadow: 0 8px 40px rgba(0,0,0,0.8), 0 0 0 1px rgba(255,255,255,0.04);
    transform: translateX(0);
    opacity: 1;
    transition: transform 0.3s cubic-bezier(.22,.68,0,1.2), opacity 0.3s ease;
  }

  .shail-card.entering {
    transform: translateX(110%);
    opacity: 0;
  }

  .shail-card.leaving {
    transform: translateX(110%);
    opacity: 0;
  }

  .shail-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
  }

  .shail-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .shail-app-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .shail-brand {
    margin-left: auto;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.1em;
    color: #22c55e;
    text-transform: uppercase;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  }

  .shail-close {
    background: none;
    border: none;
    cursor: pointer;
    color: #444;
    font-size: 16px;
    line-height: 1;
    padding: 0 0 0 8px;
    transition: color 0.15s;
  }
  .shail-close:hover { color: #888; }

  .shail-question {
    font-size: 11px;
    font-weight: 500;
    color: #666;
    margin-bottom: 4px;
  }

  .shail-preview {
    font-size: 12px;
    color: #e5e5e5;
    font-weight: 500;
    line-height: 1.4;
    margin-bottom: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .shail-actions {
    display: flex;
    gap: 6px;
    margin-bottom: 10px;
  }

  .shail-btn {
    padding: 7px 10px;
    border-radius: 7px;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    transition: opacity 0.15s;
    white-space: nowrap;
  }
  .shail-btn:active { opacity: 0.75; }

  .shail-btn-save {
    flex: 1;
    background: #fff;
    color: #000;
    border-color: #fff;
  }
  .shail-btn-save:hover { opacity: 0.88; }

  .shail-btn-session {
    background: rgba(34,197,94,0.1);
    color: #22c55e;
    border-color: rgba(34,197,94,0.3);
    font-size: 10px;
  }
  .shail-btn-session:hover { background: rgba(34,197,94,0.18); }

  .shail-btn-skip {
    background: transparent;
    color: #555;
    border-color: #222;
    font-size: 10px;
  }
  .shail-btn-skip:hover { color: #888; }

  .shail-btn-pause {
    background: rgba(245,158,11,0.1);
    color: #f59e0b;
    border-color: rgba(245,158,11,0.3);
    font-size: 10px;
  }
  .shail-btn-pause:hover { background: rgba(245,158,11,0.18); }

  .shail-progress-track {
    height: 2px;
    background: #1a1a1a;
    border-radius: 2px;
    overflow: hidden;
  }

  .shail-progress-fill {
    height: 100%;
    background: #22c55e;
    border-radius: 2px;
    transform-origin: left;
    transition: width linear;
  }
`;

const KEY_PAUSED_CONVOS = 'shail_paused_conversations';

export function showCapturePrompt(opts: NotifyOptions): void {
  if (activeCleanup) { activeCleanup(); activeCleanup = null; }

  const dismissMs = opts.autoDismissMs ?? 8000;
  const appColor  = getAppColor(opts.sourceApp);
  const appLabel  = getAppLabel(opts.sourceApp);
  const preview   = opts.title.trim().slice(0, 68) || 'Memory worth saving?';
  const hasPause  = !!opts.conversationId;

  const host = document.createElement('div');
  host.setAttribute('data-shail-notify', '');
  document.body.appendChild(host);

  const shadow = host.attachShadow({ mode: 'closed' });

  const style = document.createElement('style');
  style.textContent = WIDGET_CSS;
  shadow.appendChild(style);

  const card = document.createElement('div');
  card.className = 'shail-card entering';
  card.innerHTML = `
    <div class="shail-header">
      <span class="shail-dot" style="background:${appColor}"></span>
      <span class="shail-app-label" style="color:${appColor}">${appLabel}</span>
      <span class="shail-brand">SHAIL</span>
      <button class="shail-close" title="Dismiss">×</button>
    </div>
    <div class="shail-question">Worth saving this memory?</div>
    <div class="shail-preview" title="${preview}">${preview}</div>
    <div class="shail-actions">
      <button class="shail-btn shail-btn-save">💾 Save</button>
      ${hasPause ? '<button class="shail-btn shail-btn-pause" title="Stop capturing this conversation">⏸ Pause chat</button>' : ''}
      <button class="shail-btn shail-btn-skip">Skip</button>
    </div>
    <div class="shail-progress-track">
      <div class="shail-progress-fill" style="width:100%"></div>
    </div>
  `;
  shadow.appendChild(card);

  requestAnimationFrame(() => requestAnimationFrame(() => { card.classList.remove('entering'); }));

  const fill = card.querySelector<HTMLElement>('.shail-progress-fill')!;
  fill.style.transition = `width ${dismissMs}ms linear`;
  requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = '0%'; }));

  let dismissed = false;

  function dismiss(action: 'save' | 'skip' | 'pause' | 'timeout') {
    if (dismissed) return;
    dismissed = true;
    activeCleanup = null;
    clearTimeout(timer);
    card.classList.add('leaving');
    setTimeout(() => host.remove(), 350);
    if (action === 'save') opts.onSave();
    else if (action === 'skip') opts.onSkip();
    else if (action === 'pause') opts.onSkip(); // don't save; pause handled below
  }

  const timer = setTimeout(() => dismiss('timeout'), dismissMs);

  card.querySelector('.shail-btn-save')!.addEventListener('click', () => dismiss('save'));
  card.querySelector('.shail-btn-skip')!.addEventListener('click', () => dismiss('skip'));
  card.querySelector('.shail-close')!.addEventListener('click', () => dismiss('skip'));

  if (hasPause) {
    card.querySelector('.shail-btn-pause')!.addEventListener('click', async () => {
      const convId = opts.conversationId!;
      try {
        const stored = await browser.storage.local.get(KEY_PAUSED_CONVOS);
        const paused: string[] = (stored[KEY_PAUSED_CONVOS] as string[]) ?? [];
        if (!paused.includes(convId)) paused.push(convId);
        await browser.storage.local.set({ [KEY_PAUSED_CONVOS]: paused });
      } catch { /* best-effort */ }
      dismiss('pause');
    });
  }

  activeCleanup = () => dismiss('skip');
}
