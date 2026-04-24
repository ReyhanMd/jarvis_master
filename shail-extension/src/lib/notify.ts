/**
 * notify.ts — Shadow DOM notification widget for borderline captures.
 *
 * Runs inside content scripts (no React, no Tailwind).
 * Uses Shadow DOM so the host page's CSS can't touch it.
 *
 * Shows a small card top-right:
 *   "Worth saving? [Save] [Skip]"
 * Auto-dismisses after autoDismissMs (default 8000ms).
 */

import type { SourceApp } from '../types/contracts';

export interface NotifyOptions {
  title:          string;        // conversation title or page title
  sourceApp:      SourceApp;
  onSave:         () => void;
  onSkip:         () => void;
  autoDismissMs?: number;        // default 8000
}

// One widget at a time — if a new one arrives while one is showing,
// dismiss the current one first.
let activeCleanup: (() => void) | null = null;

// ─── Source app display ───────────────────────────────────────────────────────

function getAppLabel(app: SourceApp): string {
  const map: Record<SourceApp, string> = {
    chatgpt:    'ChatGPT',
    claude:     'Claude',
    gemini:     'Gemini',
    perplexity: 'Perplexity',
    web:        'Web Page',
  };
  return map[app] ?? 'AI';
}

function getAppColor(app: SourceApp): string {
  const map: Record<SourceApp, string> = {
    chatgpt:    '#10a37f',
    claude:     '#d97706',
    gemini:     '#4285f4',
    perplexity: '#7c3aed',
    web:        '#6b7280',
  };
  return map[app] ?? '#6b7280';
}

// ─── Widget styles ────────────────────────────────────────────────────────────

const WIDGET_CSS = `
  *,*::before,*::after { box-sizing: border-box; margin: 0; padding: 0; }

  .shail-card {
    position: fixed;
    top: 16px;
    right: 16px;
    z-index: 2147483647;
    width: 288px;
    background: #0d0d14;
    border: 1px solid rgba(59,130,246,0.35);
    border-radius: 14px;
    padding: 14px 14px 10px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    box-shadow: 0 8px 40px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.04);
    transform: translateX(0);
    opacity: 1;
    transition: transform 0.35s cubic-bezier(.22,.68,0,1.2), opacity 0.35s ease;
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
    gap: 7px;
    margin-bottom: 9px;
  }

  .shail-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .shail-app-label {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .shail-brand {
    margin-left: auto;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.08em;
    color: rgba(255,255,255,0.2);
    text-transform: uppercase;
  }

  .shail-close {
    background: none;
    border: none;
    cursor: pointer;
    color: rgba(255,255,255,0.25);
    font-size: 16px;
    line-height: 1;
    padding: 0 0 0 6px;
    transition: color 0.15s;
  }
  .shail-close:hover { color: rgba(255,255,255,0.6); }

  .shail-question {
    font-size: 11px;
    font-weight: 600;
    color: rgba(255,255,255,0.55);
    margin-bottom: 5px;
  }

  .shail-preview {
    font-size: 12px;
    color: rgba(255,255,255,0.85);
    font-weight: 500;
    line-height: 1.45;
    margin-bottom: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .shail-actions {
    display: flex;
    gap: 7px;
    margin-bottom: 10px;
  }

  .shail-btn {
    flex: 1;
    padding: 7px 0;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    transition: opacity 0.15s, transform 0.1s;
  }
  .shail-btn:active { transform: scale(0.97); }

  .shail-btn-save {
    background: linear-gradient(135deg, #3b82f6, #2563eb);
    color: #fff;
    border-color: rgba(59,130,246,0.4);
  }
  .shail-btn-save:hover { opacity: 0.88; }

  .shail-btn-skip {
    background: rgba(255,255,255,0.05);
    color: rgba(255,255,255,0.45);
    border-color: rgba(255,255,255,0.09);
  }
  .shail-btn-skip:hover { color: rgba(255,255,255,0.7); }

  .shail-progress-track {
    height: 2px;
    background: rgba(255,255,255,0.07);
    border-radius: 2px;
    overflow: hidden;
  }

  .shail-progress-fill {
    height: 100%;
    background: rgba(59,130,246,0.5);
    border-radius: 2px;
    transform-origin: left;
    transition: width linear;
  }
`;

// ─── Widget factory ───────────────────────────────────────────────────────────

export function showCapturePrompt(opts: NotifyOptions): void {
  // Dismiss any currently-showing widget first
  if (activeCleanup) {
    activeCleanup();
    activeCleanup = null;
  }

  const dismissMs = opts.autoDismissMs ?? 8000;
  const appColor  = getAppColor(opts.sourceApp);
  const appLabel  = getAppLabel(opts.sourceApp);
  const preview   = opts.title.trim().slice(0, 64) || 'AI response';

  // ── DOM structure ──────────────────────────────────────────────────────────
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
      <button class="shail-btn shail-btn-skip">Skip</button>
    </div>
    <div class="shail-progress-track">
      <div class="shail-progress-fill" style="width:100%"></div>
    </div>
  `;
  shadow.appendChild(card);

  // ── Animation: slide in ────────────────────────────────────────────────────
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      card.classList.remove('entering');
    });
  });

  // ── Progress bar ───────────────────────────────────────────────────────────
  const fill = card.querySelector<HTMLElement>('.shail-progress-fill')!;
  fill.style.transition = `width ${dismissMs}ms linear`;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      fill.style.width = '0%';
    });
  });

  // ── Cleanup ────────────────────────────────────────────────────────────────
  let dismissed = false;

  function dismiss(action: 'save' | 'skip' | 'timeout') {
    if (dismissed) return;
    dismissed = true;
    activeCleanup = null;

    clearTimeout(timer);

    card.classList.add('leaving');
    setTimeout(() => host.remove(), 400);

    if (action === 'save') opts.onSave();
    else if (action === 'skip') opts.onSkip();
    // timeout → no callback, just dismiss
  }

  // ── Auto-dismiss timer ─────────────────────────────────────────────────────
  const timer = setTimeout(() => dismiss('timeout'), dismissMs);

  // ── Button handlers ────────────────────────────────────────────────────────
  card.querySelector('.shail-btn-save')!.addEventListener('click', () => dismiss('save'));
  card.querySelector('.shail-btn-skip')!.addEventListener('click', () => dismiss('skip'));
  card.querySelector('.shail-close')!.addEventListener('click',   () => dismiss('skip'));

  // ── Register for external dismissal ───────────────────────────────────────
  activeCleanup = () => dismiss('skip');
}
