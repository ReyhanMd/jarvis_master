/**
 * quick-query.content.ts — Ctrl+Space floating memory search panel.
 *
 * Runs on every page in an isolated Shadow DOM so the host page's CSS
 * can never break it.
 *
 * Triggers:  Ctrl+Space  (ctrlKey + Space) — capture phase, prevents default
 * Closes:    Escape key  OR  clicking the backdrop
 */

import { api, cleanContentForDisplay, formatFullInject } from '../src/lib/api';
import { timeAgo } from '../src/lib/utils';
import type { MemoryRecord, EventType, SourceApp } from '../src/types/contracts';

// ─── Source metadata ──────────────────────────────────────────────────────────

const APP_META: Record<SourceApp, { label: string; color: string }> = {
  chatgpt:    { label: 'ChatGPT',    color: '#10a37f' },
  claude:     { label: 'Claude',     color: '#cc785c' },
  gemini:     { label: 'Gemini',     color: '#4285f4' },
  perplexity: { label: 'Perplexity', color: '#20b2aa' },
  web:        { label: 'Web',        color: '#6b7280' },
};

function appMeta(app: SourceApp) {
  return APP_META[app] ?? APP_META.web;
}

// ─── HTML escape (used in innerHTML to prevent XSS) ──────────────────────────

function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ─── Inject-into-element helper ───────────────────────────────────────────────

function injectIntoElement(el: Element | null, text: string): boolean {
  // Fall back to finding any visible composer on the page
  if (!el || !(el instanceof HTMLElement)) {
    el =
      document.querySelector<HTMLElement>('#prompt-textarea') ??
      document.querySelector<HTMLElement>('.ProseMirror[contenteditable="true"]') ??
      document.querySelector<HTMLElement>('[contenteditable="true"]') ??
      document.querySelector<HTMLElement>('textarea');
  }
  if (!el || !(el instanceof HTMLElement)) return false;

  el.focus();

  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    const proto = el.tagName === 'TEXTAREA'
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    const cur    = (el as HTMLTextAreaElement).value;
    const next   = cur ? `${cur}\n${text}` : text;
    setter ? setter.call(el, next) : ((el as HTMLTextAreaElement).value = next);
    el.dispatchEvent(new Event('input',  { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  } else if (el.isContentEditable) {
    const sel   = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel?.removeAllRanges();
    sel?.addRange(range);
    document.execCommand('insertText', false, el.textContent?.trim() ? `\n${text}` : text);
  } else {
    return false;
  }
  return true;
}

// ─── Shadow DOM CSS ───────────────────────────────────────────────────────────

const CSS = `
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

.backdrop{
  position:fixed;inset:0;background:rgba(0,0,0,0.58);
  backdrop-filter:blur(3px);z-index:2147483645;cursor:pointer;
}

.panel{
  position:fixed;top:50%;left:50%;
  transform:translate(-50%,-50%);
  width:520px;max-width:calc(100vw - 32px);max-height:600px;
  background:#0a0a0f;border:1px solid #1e1e2e;border-radius:16px;
  box-shadow:0 24px 80px rgba(0,0,0,.75),0 0 0 1px rgba(255,255,255,.05);
  z-index:2147483647;display:flex;flex-direction:column;overflow:hidden;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  transition:opacity .15s ease,transform .2s cubic-bezier(.34,1.56,.64,1);
  position:relative;
}
.panel.entering{opacity:0;transform:translate(-50%,-50%) scale(.95)}

/* Header */
.panel-header{
  display:flex;align-items:center;gap:8px;
  padding:14px 16px 0;flex-shrink:0;
}
.brand-dot{width:8px;height:8px;border-radius:50%;background:#3b82f6;flex-shrink:0}
.brand-name{font-size:12px;font-weight:700;color:rgba(255,255,255,.6);letter-spacing:.05em}
.close-btn{
  margin-left:auto;background:none;border:none;color:rgba(255,255,255,.25);
  font-size:18px;cursor:pointer;padding:0;line-height:1;flex-shrink:0;
}
.close-btn:hover{color:rgba(255,255,255,.65)}

/* Search bar */
.search-wrap{
  display:flex;align-items:center;gap:10px;
  margin:12px 16px 8px;padding:10px 14px;
  background:#13131a;border:1px solid #1e1e2e;border-radius:10px;flex-shrink:0;
}
.search-icon{font-size:13px;opacity:.35;flex-shrink:0}
.search-input{
  flex:1;background:none;border:none;outline:none;
  color:#fff;font-size:13px;font-family:inherit;
}
.search-input::placeholder{color:#374151}
.search-kb{
  font-size:9px;color:#374151;background:#1e1e2e;
  padding:2px 6px;border-radius:4px;font-family:monospace;flex-shrink:0;
}

/* Results scroll area */
.results{flex:1;overflow-y:auto;padding:0 10px 6px}
.results::-webkit-scrollbar{width:4px}
.results::-webkit-scrollbar-thumb{background:#1e1e2e;border-radius:4px}

/* Section label */
.sec-label{
  font-size:9px;font-weight:700;text-transform:uppercase;
  letter-spacing:.1em;color:#374151;padding:6px 6px 4px;
}

/* Empty state */
.empty{
  display:flex;flex-direction:column;align-items:center;
  padding:36px 20px;gap:8px;color:#374151;font-size:12px;text-align:center;
}
.empty-icon{font-size:28px;opacity:.25;margin-bottom:4px}
.empty-title{font-size:12px;font-weight:500;color:rgba(255,255,255,.35)}

/* Skeletons */
.skel{
  background:#13131a;border:1px solid #1e1e2e;border-radius:10px;
  padding:12px;margin-bottom:6px;
}
.skel-line{background:#1e1e2e;border-radius:4px;animation:pulse 1.5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* Memory card */
.card{
  background:#13131a;border:1px solid #1e1e2e;border-radius:10px;
  margin-bottom:6px;overflow:hidden;
  transition:border-color .18s,box-shadow .18s;
  cursor:pointer;
}
.card:hover{border-color:#2d2d3e;box-shadow:0 2px 12px rgba(0,0,0,.4)}
.card.expanded{
  border-color:rgba(59,130,246,.4);
  box-shadow:0 0 0 1px rgba(59,130,246,.12),0 4px 20px rgba(0,0,0,.4);
  cursor:default;
}

.card-top{padding:10px 12px 0;user-select:none}
.card-meta{display:flex;align-items:center;gap:6px;margin-bottom:5px}
.src-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.src-lbl{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.card-time{margin-left:auto;font-size:10px;color:#374151}

.card-title{
  font-size:12px;font-weight:600;color:#fff;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:5px;
}

/* Collapsed preview — hidden when expanded */
.card-preview{
  font-size:11px;color:#6b7280;line-height:1.5;margin-bottom:4px;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
}
.card.expanded .card-preview{display:none}

/* Expand hint */
.expand-hint{
  font-size:10px;color:#4b5563;padding:2px 12px 8px;
  display:flex;align-items:center;gap:4px;
  transition:color .12s;
}
.card:hover .expand-hint{color:#6b7280}
.expand-arrow{
  display:inline-block;transition:transform .2s cubic-bezier(.34,1.56,.64,1);font-size:9px;
}
.card.expanded .expand-arrow{transform:rotate(90deg)}
.card.expanded .expand-hint{color:rgba(59,130,246,.6);padding-bottom:6px}

/* Full content — animated reveal */
.card-full{
  max-height:0;overflow:hidden;
  transition:max-height .3s cubic-bezier(.4,0,.2,1),opacity .2s ease;
  opacity:0;padding:0 12px;
}
.card.expanded .card-full{
  max-height:500px;opacity:1;padding:0 12px 10px;
}

.full-loading{font-size:11px;color:#4b5563;padding:10px 0}

.full-sect{margin-bottom:12px}
.full-sect-label{
  font-size:9px;font-weight:700;text-transform:uppercase;
  letter-spacing:.08em;color:#4b5563;margin-bottom:5px;
  display:flex;align-items:center;gap:6px;
}
.full-sect-label::after{content:'';flex:1;height:1px;background:#1e1e2e}
.full-sect-text{
  font-size:11px;color:#9ca3af;line-height:1.65;
  max-height:200px;overflow-y:auto;white-space:pre-wrap;word-break:break-word;
  padding:8px;background:#0d0d14;border-radius:6px;border:1px solid #1a1a2a;
}
.full-sect-text::-webkit-scrollbar{width:3px}
.full-sect-text::-webkit-scrollbar-thumb{background:#2d2d3e;border-radius:2px}

/* Action buttons */
.card-actions{
  display:flex;gap:6px;padding:8px 12px;
  border-top:1px solid #1e1e2e;background:rgba(0,0,0,.2);
}
.act-btn{
  padding:5px 10px;border-radius:6px;font-size:11px;font-weight:600;
  cursor:pointer;border:1px solid #1e1e2e;
  background:rgba(255,255,255,.03);color:#6b7280;
  font-family:inherit;transition:all .12s;
}
.act-btn:hover{color:#fff;border-color:#374151}
.act-btn.pri{
  background:rgba(59,130,246,.12);color:#60a5fa;border-color:rgba(59,130,246,.25);
}
.act-btn.pri:hover{background:rgba(59,130,246,.2);color:#93c5fd}
.act-btn:disabled{opacity:.4;pointer-events:none}

/* Footer */
.panel-footer{
  display:flex;align-items:center;justify-content:center;
  padding:10px 16px;border-top:1px solid #1e1e2e;flex-shrink:0;
}
.open-btn{
  background:none;border:none;color:#374151;font-size:11px;
  cursor:pointer;font-family:inherit;display:flex;align-items:center;gap:4px;
  transition:color .15s;
}
.open-btn:hover{color:#9ca3af}

/* Toast (inside the panel) */
.toast{
  position:absolute;bottom:52px;left:50%;transform:translateX(-50%);
  padding:6px 14px;border-radius:8px;font-size:11px;white-space:nowrap;
  pointer-events:none;opacity:0;transition:opacity .2s;
  background:rgba(34,197,94,.15);border:1px solid rgba(34,197,94,.3);color:#86efac;
}
.toast.info{
  background:rgba(59,130,246,.12);border-color:rgba(59,130,246,.25);color:#93c5fd;
}
.toast.visible{opacity:1}
`;

// ─── Overlay factory ──────────────────────────────────────────────────────────

function buildOverlay(getLastFocused: () => Element | null) {
  let visible      = false;
  let records: MemoryRecord[] = [];
  let currentQuery = '';
  let searchTimer: ReturnType<typeof setTimeout> | null = null;
  let toastTimer:  ReturnType<typeof setTimeout> | null = null;

  // Per-card state (persists while overlay lives in the DOM)
  const expandedIds        = new Set<string>();
  const fullContentCache   = new Map<string, { content: string; eventType: EventType }>();

  // ── Shadow DOM setup ───────────────────────────────────────────────────────
  const host = document.createElement('div');
  host.setAttribute('data-shail-qq', '');
  document.body.appendChild(host);
  const shadow = host.attachShadow({ mode: 'closed' });

  const styleEl = document.createElement('style');
  styleEl.textContent = CSS;
  shadow.appendChild(styleEl);

  const backdrop = document.createElement('div');
  backdrop.className = 'backdrop';
  shadow.appendChild(backdrop);

  const panel = document.createElement('div');
  panel.className = 'panel entering';
  panel.innerHTML = `
    <div class="panel-header">
      <span class="brand-dot"></span>
      <span class="brand-name">SHAIL Memory</span>
      <button class="close-btn" title="Close (Esc)">×</button>
    </div>
    <div class="search-wrap">
      <span class="search-icon">🔍</span>
      <input class="search-input"
             placeholder="Search your memory…"
             autocomplete="off" spellcheck="false" />
      <span class="search-kb">⌃Space</span>
    </div>
    <div class="results"></div>
    <div class="panel-footer">
      <button class="open-btn">Open full panel →</button>
    </div>
    <div class="toast"></div>
  `;
  shadow.appendChild(panel);

  const searchInput = panel.querySelector<HTMLInputElement>('.search-input')!;
  const resultsEl   = panel.querySelector<HTMLDivElement>('.results')!;
  const toastEl     = panel.querySelector<HTMLDivElement>('.toast')!;

  // Hide until first trigger
  host.style.display = 'none';

  // ── Toast ──────────────────────────────────────────────────────────────────
  function showToast(msg: string, type: 'success' | 'info' = 'success') {
    if (toastTimer) clearTimeout(toastTimer);
    toastEl.textContent  = msg;
    toastEl.className    = `toast${type === 'info' ? ' info' : ''} visible`;
    toastTimer = setTimeout(() => toastEl.classList.remove('visible'), 2200);
  }

  // ── Render helpers ─────────────────────────────────────────────────────────
  function renderSkeletons() {
    resultsEl.innerHTML = `
      <div class="sec-label">${currentQuery ? 'Searching…' : 'Loading…'}</div>
      ${[0, 1, 2].map(() => `
        <div class="skel">
          <div class="skel-line" style="height:9px;width:38%;margin-bottom:8px"></div>
          <div class="skel-line" style="height:12px;width:80%;margin-bottom:6px"></div>
          <div class="skel-line" style="height:11px;width:60%"></div>
        </div>
      `).join('')}
    `;
  }

  function renderEmpty() {
    resultsEl.innerHTML = `
      <div class="empty">
        <div class="empty-icon">🧠</div>
        <div class="empty-title">
          ${currentQuery
            ? `No memories matching "${esc(currentQuery)}"`
            : 'No memories yet'}
        </div>
        <div>
          ${currentQuery
            ? 'Try a different term.'
            : 'Browse the web or chat with an AI — SHAIL captures automatically.'}
        </div>
      </div>
    `;
  }

  // Build the expanded full-content HTML from cached data
  function buildFullHtml(content: string, eventType: EventType): string {
    const nlnl = content.indexOf('\n\n');
    const body = nlnl > 0 ? content.slice(nlnl + 2) : content;

    if (eventType === 'ai_conversation') {
      const uMatch = body.match(/^User:\s*([\s\S]*?)(?=\n\nAssistant:|$)/);
      const aMatch = body.match(/\n\nAssistant:\s*([\s\S]*)$/);
      const q = uMatch?.[1]?.trim() ?? '';
      const a = (aMatch?.[1]?.trim() ?? body.trim()).slice(0, 3000);
      return `
        ${q ? `<div class="full-sect">
          <div class="full-sect-label">Question</div>
          <div class="full-sect-text">${esc(q)}</div>
        </div>` : ''}
        <div class="full-sect">
          <div class="full-sect-label">Answer</div>
          <div class="full-sect-text">${esc(a)}${(aMatch?.[1]?.trim() ?? '').length > 3000 ? '\n[… truncated]' : ''}</div>
        </div>`;
    } else {
      const text = body.trim().slice(0, 3000);
      return `<div class="full-sect">
        <div class="full-sect-label">Content</div>
        <div class="full-sect-text">${esc(text)}${body.trim().length > 3000 ? '\n[… truncated]' : ''}</div>
      </div>`;
    }
  }

  // Build a single card element
  function buildCard(r: MemoryRecord): HTMLElement {
    const m    = appMeta(r.sourceApp);
    const card = document.createElement('div');
    const isEx = expandedIds.has(r.id);

    card.className = `card${isEx ? ' expanded' : ''}`;
    card.dataset.id = r.id;

    card.innerHTML = `
      <div class="card-top">
        <div class="card-meta">
          <span class="src-dot"  style="background:${m.color}"></span>
          <span class="src-lbl"  style="color:${m.color}">${m.label}</span>
          <span class="card-time">${timeAgo(r.timestamp)}</span>
        </div>
        <div class="card-title">${esc(r.title || r.sourceUrl || 'Untitled')}</div>
        <div class="card-preview">${esc(cleanContentForDisplay(r.summary).slice(0, 180))}</div>
      </div>
      <div class="expand-hint">
        <span class="expand-arrow">▸</span>
        <span class="expand-label">${isEx ? 'Collapse' : 'Tap to expand full memory'}</span>
      </div>
      <div class="card-full">
        ${isEx && fullContentCache.has(r.id)
          ? buildFullHtml(fullContentCache.get(r.id)!.content, fullContentCache.get(r.id)!.eventType)
          : ''}
      </div>
      <div class="card-actions">
        <button class="act-btn pri inject-btn">↗ Inject</button>
        <button class="act-btn copy-btn">⎘ Copy</button>
      </div>
    `;

    // Tap anywhere on the card (except action buttons) to expand/collapse
    const toggleEl = (e: Event) => { e.stopPropagation(); toggleExpand(r, card); };
    card.querySelector('.card-top')!.addEventListener('click',    toggleEl);
    card.querySelector('.expand-hint')!.addEventListener('click', toggleEl);

    // Inject
    (card.querySelector('.inject-btn') as HTMLButtonElement).addEventListener('click', e => {
      e.stopPropagation();
      handleInject(r, card.querySelector('.inject-btn') as HTMLButtonElement);
    });

    // Copy
    card.querySelector('.copy-btn')!.addEventListener('click', e => {
      e.stopPropagation();
      handleCopy(r);
    });

    return card;
  }

  function renderCards() {
    if (records.length === 0) { renderEmpty(); return; }

    const label = currentQuery
      ? `${records.length} result${records.length !== 1 ? 's' : ''}`
      : 'Recent memories';

    resultsEl.innerHTML = `<div class="sec-label">${esc(label)}</div>`;
    records.slice(0, 8).forEach(r => resultsEl.appendChild(buildCard(r)));
  }

  // ── Expand / collapse ──────────────────────────────────────────────────────
  async function toggleExpand(r: MemoryRecord, card: HTMLElement) {
    const fullEl  = card.querySelector<HTMLElement>('.card-full')!;
    const labelEl = card.querySelector<HTMLElement>('.expand-label');

    if (expandedIds.has(r.id)) {
      expandedIds.delete(r.id);
      card.classList.remove('expanded');
      if (labelEl) labelEl.textContent = 'Tap to expand full memory';
      return;
    }

    expandedIds.add(r.id);
    card.classList.add('expanded');
    if (labelEl) labelEl.textContent = 'Collapse';

    // If already cached, render immediately (CSS transition handles the reveal)
    if (fullContentCache.has(r.id)) {
      const { content, eventType } = fullContentCache.get(r.id)!;
      fullEl.innerHTML = buildFullHtml(content, eventType);
      return;
    }

    // Show spinner while fetching
    fullEl.innerHTML = `
      <div class="full-loading">
        <span style="display:inline-block;animation:pulse 1s ease-in-out infinite">⏳</span>
        Loading full memory…
      </div>`;

    try {
      const { content, eventType } = await api.getFullContent(r.id);
      fullContentCache.set(r.id, { content, eventType });
      if (expandedIds.has(r.id)) {  // still expanded — render
        fullEl.innerHTML = buildFullHtml(content, eventType);
      }
    } catch {
      fullEl.innerHTML = '<div class="full-loading" style="color:#ef4444">⚠ Failed to load — check connection</div>';
    }
  }

  // ── Inject / Copy ──────────────────────────────────────────────────────────
  async function handleInject(r: MemoryRecord, btn: HTMLButtonElement) {
    btn.disabled    = true;
    btn.textContent = '…';

    let text: string;
    try {
      const cached = fullContentCache.get(r.id);
      const { content, eventType } = cached ?? await api.getFullContent(r.id);
      if (!cached) fullContentCache.set(r.id, { content, eventType });
      text = formatFullInject(content, eventType, appMeta(r.sourceApp).label);
    } catch {
      text = `--- Memory: ${r.title} ---\n${cleanContentForDisplay(r.summary)}\n`;
    }

    btn.disabled    = false;
    btn.textContent = '↗ Inject';

    const ok = injectIntoElement(getLastFocused(), text);
    if (ok) {
      hide();
    } else {
      try {
        await navigator.clipboard.writeText(text);
        showToast('Copied — paste into your chat', 'info');
      } catch {
        showToast('No chat input found — open a chat first', 'info');
      }
    }
  }

  async function handleCopy(r: MemoryRecord) {
    let text: string;
    try {
      const cached = fullContentCache.get(r.id);
      const { content, eventType } = cached ?? await api.getFullContent(r.id);
      if (!cached) fullContentCache.set(r.id, { content, eventType });
      text = formatFullInject(content, eventType, appMeta(r.sourceApp).label);
    } catch {
      text = cleanContentForDisplay(r.summary || r.title);
    }
    try {
      await navigator.clipboard.writeText(text);
      showToast('Copied to clipboard!');
    } catch {
      showToast('Copy failed', 'info');
    }
  }

  // ── Search ─────────────────────────────────────────────────────────────────
  async function doSearch(query: string) {
    renderSkeletons();
    try {
      const resp = await browser.runtime.sendMessage({
        type:    'SEARCH',
        payload: { query },
      }) as { ok: boolean; data?: { items: MemoryRecord[] }; error?: string };

      if (resp.ok && resp.data) {
        records = resp.data.items ?? [];
      } else {
        records = [];
      }
    } catch {
      records = [];
    }
    renderCards();
  }

  // ── Show / hide / toggle ───────────────────────────────────────────────────
  function show() {
    if (visible) return;
    visible = true;
    host.style.display = '';

    // Reset entrance animation
    panel.classList.add('entering');
    requestAnimationFrame(() => requestAnimationFrame(() => panel.classList.remove('entering')));

    // Reset search, focus input, load recent
    currentQuery     = '';
    searchInput.value = '';
    requestAnimationFrame(() => searchInput.focus());
    doSearch('');
  }

  function hide() {
    if (!visible) return;
    visible = false;
    host.style.display = 'none';
  }

  function toggle() { visible ? hide() : show(); }

  // ── Wire up static events ──────────────────────────────────────────────────
  backdrop.addEventListener('click', hide);
  panel.querySelector('.close-btn')!.addEventListener('click', hide);

  panel.querySelector('.open-btn')!.addEventListener('click', () => {
    hide();
    browser.runtime.sendMessage({ type: 'OPEN_SIDEPANEL' }).catch(() => {});
  });

  searchInput.addEventListener('input', () => {
    currentQuery = searchInput.value.trim();
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => doSearch(currentQuery), 300);
  });

  // Prevent panel clicks from reaching the backdrop
  panel.addEventListener('click', e => e.stopPropagation());

  return { show, hide, toggle, isVisible: () => visible };
}

// ─── Content script entry ─────────────────────────────────────────────────────

export default defineContentScript({
  matches:  ['<all_urls>'],
  runAt:    'document_idle',

  main() {
    let lastFocused: Element | null = null;

    // Track the last focused text input (used by inject helper)
    document.addEventListener('focusin', e => {
      const el = e.target as Element;
      if (
        el instanceof HTMLTextAreaElement ||
        el instanceof HTMLInputElement ||
        (el instanceof HTMLElement && el.isContentEditable)
      ) {
        lastFocused = el;
      }
    }, true);

    // Ctrl+Space — open the SHAIL memory side panel.
    // Page-level fallback: the manifest command fires first in Chrome's command
    // dispatcher (guaranteed to work on every tab including chrome:// pages and
    // PDFs). This listener catches the rare case where a page's JS grabs the
    // event before Chrome's command system — in practice both fire and the
    // second sendMessage is a fast no-op.
    window.addEventListener('keydown', e => {
      if (
        e.ctrlKey  &&
        e.code === 'Space' &&
        !e.altKey  &&
        !e.metaKey &&
        !e.shiftKey
      ) {
        e.preventDefault();
        e.stopImmediatePropagation();
        browser.runtime.sendMessage({ type: 'OPEN_SIDEPANEL' }).catch(() => {});
      }
    }, true);  // ← capture phase — runs before any page handler

    // Keep lastFocused accessible for inject (used by other scripts via overlay)
    void lastFocused;
  },
});
