import {
  getCapturePolicy,
  setConversationExcluded,
  setConversationPaused,
  KEY_ACTIVE_CAPTURE,
} from '../src/lib/active-capture-orchestrator';
import { api, userFacingError } from '../src/lib/api';
import { getApiSessionCapture } from '../src/lib/api-capture-cache';
import { buildBulkCapture, sendCapture } from '../src/lib/capture';
import { resolveConversationIdentity } from '../src/lib/conversation-id';
import { scrollPumpCapture } from '../src/lib/conversation-extractor';
import { clearConversation, getTurns } from '../src/lib/scroll-pump-store';
import { detectPlatformAdapter } from '../src/lib/platform-adapters';
import { sha256 } from '../src/lib/crypto';
import type { CaptureSurfaceState, SourceApp } from '../src/types/contracts';

type BarState = 'IDLE' | 'LISTENING' | 'CAPTURING' | 'SCROLL_PUMP' | 'PAUSED' | 'EXCLUDED' | 'ERROR';

interface ScrollConfig {
  sourceApp: SourceApp;
  scrollContainer: string;
  userSelectors: string[];
  assistantSelectors: string[];
  conversationIdTemporary?: boolean;
  previousConversationId?: string;
}

const SCROLL_CONFIGS: Partial<Record<SourceApp, ScrollConfig>> = {
  chatgpt: {
    sourceApp: 'chatgpt',
    userSelectors: ["[data-message-author-role='user']"],
    assistantSelectors: ["[data-message-author-role='assistant']"],
    scrollContainer: 'main, div[class*="react-scroll-to-bottom"], div.overflow-y-auto, div.overflow-y-scroll',
  },
  claude: {
    sourceApp: 'claude',
    userSelectors: ['[data-testid="user-message"]', '.human-turn p', '[class*="HumanMessage"]'],
    assistantSelectors: ['.font-claude-message', '[data-testid="assistant-message"]', '[class*="AssistantMessage"]'],
    scrollContainer: 'div.overflow-y-scroll, div.overflow-y-auto, main',
  },
  gemini: {
    sourceApp: 'gemini',
    userSelectors: ['.query-text', '.user-query-bubble-with-background', 'query-text'],
    assistantSelectors: ['model-response .markdown', 'model-response', '.model-response-text'],
    scrollContainer: '.bottom-bar-scroller, div.overflow-y-auto, main',
  },
  perplexity: {
    sourceApp: 'perplexity',
    userSelectors: ['[class*="QueryText"]', '.query-display', 'h1.line-clamp-2'],
    assistantSelectors: ['[class*="prose"]', '.answer-content', '[data-testid="answer"]'],
    scrollContainer: 'main, div.overflow-y-auto, div.overflow-y-scroll',
  },
  grok: {
    sourceApp: 'grok',
    userSelectors: ['[data-testid="user-message"]', '.message-bubble.user', '[class*="UserMessage"]'],
    assistantSelectors: ['[data-testid="message-content"]', '.message-bubble.ai', '[class*="AssistantMessage"]'],
    scrollContainer: 'main, div.overflow-y-auto, #chat-scroll-container',
  },
};

function pipelineLabel(surface: CaptureSurfaceState | null): string {
  if (!surface) return 'captured';
  if (surface.blueprint.present) return 'blueprint_ready';
  if (surface.blueprint.job_state === 'running') return 'blueprint_extracting';
  if (surface.blueprint.job_state === 'pending') return 'blueprint_queued';
  if (surface.blueprint.job_state === 'failed') return 'failed';
  const stage = surface.pipeline.current_stage || '';
  if (stage === 'embedded' || stage === 'segmented' || stage === 'captured') return stage;
  return stage || 'captured';
}

export default defineContentScript({
  matches: [
    'https://chat.openai.com/*',
    'https://chatgpt.com/*',
    'https://claude.ai/*',
    'https://gemini.google.com/*',
    'https://www.perplexity.ai/*',
    'https://perplexity.ai/*',
    'https://grok.com/*',
    'https://x.ai/*',
  ],
  runAt: 'document_idle',

  main() {
    const adapter = detectPlatformAdapter()!;
    if (!adapter) return;
    const scrollConfig = SCROLL_CONFIGS[adapter.sourceApp];

    let state: BarState = 'IDLE';
    let turnCount = 0;
    let progressValue = 0;
    let memoryId: string | undefined;
    let backendState: CaptureSurfaceState | null = null;
    let errorText = '';
    let captureSource: 'api' | 'dom_scroll' | undefined;
    let retroactiveStatus = '';
    let hostEl: HTMLDivElement | null = null;
    let shadow: ShadowRoot | null = null;
    let collapsed = false;
    let barPosition: { left?: number; top?: number; right?: number; bottom?: number } = { right: 16, bottom: 16 };
    const logoUrl = browser.runtime.getURL('icon/shail-official.png' as any);

    function escapeHtml(value: string): string {
      return value.replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }[ch] || ch));
    }

    function positionCss(): string {
      if (barPosition.left !== undefined && barPosition.top !== undefined) {
        return `left:${Math.max(8, barPosition.left)}px; top:${Math.max(8, barPosition.top)}px;`;
      }
      return `right:${barPosition.right ?? 16}px; bottom:${barPosition.bottom ?? 16}px;`;
    }

    async function persistBarPrefs() {
      await chrome.storage.local.set({ shail_floating_bar_prefs: { collapsed, position: barPosition } });
    }

    async function loadBarPrefs() {
      try {
        const stored = await chrome.storage.local.get('shail_floating_bar_prefs');
        const prefs = stored['shail_floating_bar_prefs'] as { collapsed?: boolean; position?: typeof barPosition } | undefined;
        collapsed = !!prefs?.collapsed;
        if (prefs?.position) barPosition = prefs.position;
      } catch {
        // defaults are fine
      }
    }

    function syncState() {
      chrome.storage.local.set({
        [KEY_ACTIVE_CAPTURE]: {
          state,
          platform: adapter.sourceApp,
          title: adapter.detectChatTitle(),
          turnCount,
          progressValue,
          conversationId: adapter.getChatID(),
          memoryId,
          captureSource,
          retroactiveStatus,
          sourceUrl: location.href,
          backendState,
          updatedAt: new Date().toISOString(),
        },
      });
    }

    function updateTurnCountFromDom() {
      try {
        const messages = adapter.extractMessages(document);
        const userTurns = messages.filter(m => m.role === 'user' && m.text.trim()).length;
        const assistantTurns = messages.filter(m => m.role === 'assistant' && m.text.trim()).length;
        const next = Math.max(userTurns, assistantTurns);
        if (next !== turnCount) {
          turnCount = next;
          renderBar();
          syncState();
        }
      } catch {
        // Selector drift should not break the page.
      }
    }

    function setState(next: BarState) {
      state = next;
      renderBar();
      syncState();
    }

    async function refreshPolicy() {
      const policy = await getCapturePolicy(adapter);
      if (policy === 'excluded') setState('EXCLUDED');
      else if (policy === 'paused') setState('PAUSED');
      else if (state === 'IDLE' || state === 'PAUSED' || state === 'EXCLUDED') setState('LISTENING');
      else renderBar();
    }

    async function refreshBackendState() {
      try {
        const stored = await chrome.storage.local.get(KEY_ACTIVE_CAPTURE);
        const cached = stored[KEY_ACTIVE_CAPTURE] as { memoryId?: string } | undefined;
        memoryId = memoryId || cached?.memoryId;
        const surface = memoryId
          ? await api.captureState({ memoryId })
          : await api.captureState({ conversationId: adapter.getChatID(), sourceUrl: location.href });
        backendState = surface;
        memoryId = surface.memory_id || memoryId;
        if (memoryId) await showBar();
        errorText = '';
        renderBar();
        syncState();
      } catch {
        // No backend state yet for this tab, or backend is offline.
      }
    }

    async function ensureMemoryId(): Promise<string | null> {
      if (memoryId) return memoryId;
      await refreshBackendState();
      return memoryId || null;
    }

    async function createBar() {
      if (hostEl) return;
      hostEl = document.createElement('div');
      hostEl.id = 'shail-bar-host';
      shadow = hostEl.attachShadow({ mode: 'closed' });
      document.body.appendChild(hostEl);
      await loadBarPrefs();
      renderBar();
    }

    async function showBar() {
      await createBar();
      renderBar();
    }

    function renderBar() {
      if (!shadow) return;
      const title = adapter.detectChatTitle();
      const dotColor = {
        IDLE: '#6b7280',
        LISTENING: '#22c55e',
        CAPTURING: '#f59e0b',
        SCROLL_PUMP: '#3b82f6',
        PAUSED: '#f59e0b',
        EXCLUDED: '#6b7280',
        ERROR: '#ef4444',
      }[state];
      const pulsing = state === 'LISTENING' || state === 'CAPTURING';
      const statusText =
        state === 'EXCLUDED' ? 'Not capturing - excluded' :
        state === 'PAUSED' ? 'Paused' :
        state === 'SCROLL_PUMP' ? (retroactiveStatus || 'Retroactive capture') :
        state === 'ERROR' ? (errorText || 'Error') :
        state === 'LISTENING' ? (backendState ? `Capturing - ${pipelineLabel(backendState)}` : 'Capturing') :
        retroactiveStatus || pipelineLabel(backendState);
      const turnLabel = `${turnCount} ${turnCount === 1 ? 'turn' : 'turns'}`;

      if (collapsed) {
        shadow.innerHTML = `
          <style>
            :host { all: initial; }
            .bubble {
              position: fixed; ${positionCss()}
              z-index: 2147483647;
              width: 42px; height: 42px;
              display: flex; align-items: center; justify-content: center;
              background: rgba(12,12,14,0.96);
              border: 1px solid rgba(255,255,255,0.14);
              border-radius: 12px;
              box-shadow: 0 8px 28px rgba(0,0,0,0.42);
              cursor: pointer;
              user-select: none;
            }
            .bubble img { width: 28px; height: 28px; border-radius: 7px; display:block; }
            .dot {
              position: absolute; right: 5px; bottom: 5px;
              width: 8px; height: 8px; border-radius: 50%;
              background: ${dotColor};
              border: 1px solid #050505;
              ${pulsing ? 'animation: pulse 1.5s ease-in-out infinite;' : ''}
            }
            @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.55;transform:scale(1.25)} }
          </style>
          <button class="bubble" id="expand-btn" title="Open SHAIL capture bar">
            <img src="${logoUrl}" alt="SHAIL" />
            <span class="dot"></span>
          </button>
        `;
        shadow.getElementById('expand-btn')?.addEventListener('click', async () => {
          collapsed = false;
          await persistBarPrefs();
          renderBar();
        });
        return;
      }

      shadow.innerHTML = `
        <style>
          :host { all: initial; }
          .bar {
            position: fixed;
            ${positionCss()}
            z-index: 2147483647;
            display: flex;
            align-items: center;
            gap: 8px;
            max-width: min(760px, calc(100vw - 32px));
            padding: 8px 12px;
            background: rgba(15, 15, 20, 0.94);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 12px;
            color: #e5e5e5;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
            user-select: none;
            touch-action: none;
          }
          .drag {
            width: 18px;
            height: 28px;
            display:flex;
            align-items:center;
            justify-content:center;
            color:#666;
            cursor: grab;
            flex-shrink:0;
          }
          .drag:active { cursor: grabbing; }
          .logo {
            width: 22px;
            height: 22px;
            border-radius: 6px;
            flex-shrink: 0;
            display:block;
          }
          .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: ${dotColor};
            flex-shrink: 0;
            ${pulsing ? 'animation: pulse 1.5s ease-in-out infinite;' : ''}
          }
          @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.3); }
          }
          .title {
            color: #cfcfcf;
            min-width: 80px;
            max-width: 220px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
          .status, .turns {
            color: #a3a3a3;
            font-size: 11px;
            white-space: nowrap;
          }
          .btn {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #e5e5e5;
            padding: 4px 9px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 11px;
            font-family: inherit;
          }
          .btn:hover { background: rgba(255, 255, 255, 0.16); }
          .icon-btn {
            width: 24px;
            height: 24px;
            padding: 0;
            display:flex;
            align-items:center;
            justify-content:center;
          }
          .btn-red {
            background: rgba(239,68,68,0.12);
            border-color: rgba(239,68,68,0.3);
            color: #fca5a5;
          }
          .progress-track {
            width: 80px;
            height: 4px;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 2px;
            overflow: hidden;
          }
          .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #3b82f6, #22c55e);
            width: ${Math.round(progressValue * 100)}%;
          }
          a { color: #60a5fa; font-size: 10px; text-decoration: none; }
          label { display: flex; align-items: center; gap: 4px; color: #a3a3a3; font-size: 10px; cursor: pointer; white-space: nowrap; }
          input { margin: 0; accent-color: #6b7280; }
        </style>
        <div class="bar" id="shail-floating-bar">
          <span class="drag" id="drag-handle" title="Drag">⋮⋮</span>
          <img class="logo" src="${logoUrl}" alt="SHAIL" />
          <span class="dot"></span>
          <span class="title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
          <span class="status">${escapeHtml(statusText)}</span>
          <span class="turns">${turnLabel}</span>
          ${state === 'SCROLL_PUMP' ? `<span class="progress-track"><span class="progress-fill"></span></span>` : ''}
          ${state !== 'PAUSED' && state !== 'EXCLUDED' ? `<button class="btn" id="pause-btn">Pause</button>` : ''}
          ${state === 'PAUSED' ? `<button class="btn" id="resume-btn">Resume</button>` : ''}
          ${state !== 'EXCLUDED' ? `<button class="btn btn-red" id="end-btn">End</button>` : ''}
          <label><input type="checkbox" id="stop-toggle" ${state === 'EXCLUDED' ? 'checked' : ''}/> ${state === 'EXCLUDED' ? 'Start scanning' : 'Stop capturing'}</label>
          <a href="#" id="view-link">View Transcript</a>
          <button class="btn icon-btn" id="collapse-btn" title="Collapse">‹</button>
        </div>
      `;

      const dragHandle = shadow.getElementById('drag-handle');
      const bar = shadow.getElementById('shail-floating-bar') as HTMLElement | null;
      dragHandle?.addEventListener('pointerdown', (e) => {
        if (!bar) return;
        e.preventDefault();
        const startX = e.clientX;
        const startY = e.clientY;
        const rect = bar.getBoundingClientRect();
        const offsetX = startX - rect.left;
        const offsetY = startY - rect.top;
        const onMove = (move: PointerEvent) => {
          barPosition = {
            left: Math.min(Math.max(8, move.clientX - offsetX), window.innerWidth - rect.width - 8),
            top: Math.min(Math.max(8, move.clientY - offsetY), window.innerHeight - rect.height - 8),
          };
          renderBar();
        };
        const onUp = async () => {
          window.removeEventListener('pointermove', onMove);
          window.removeEventListener('pointerup', onUp);
          await persistBarPrefs();
        };
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
      });

      shadow.getElementById('pause-btn')?.addEventListener('click', async () => {
        await setConversationPaused(adapter, true);
        setState('PAUSED');
      });
      shadow.getElementById('resume-btn')?.addEventListener('click', async () => {
        await setConversationPaused(adapter, false);
        await refreshPolicy();
      });
      shadow.getElementById('end-btn')?.addEventListener('click', showEndCaptureModal);
      shadow.getElementById('stop-toggle')?.addEventListener('change', async (e) => {
        const checked = (e.target as HTMLInputElement).checked;
        await setConversationExcluded(adapter, checked);
        retroactiveStatus = '';
        errorText = '';
        if (checked) {
          setState('EXCLUDED');
        } else {
          await refreshPolicy();
        }
      });
      shadow.getElementById('view-link')?.addEventListener('click', (e) => {
        e.preventDefault();
        showTranscriptModal();
      });
      shadow.getElementById('collapse-btn')?.addEventListener('click', async () => {
        collapsed = true;
        barPosition = { right: 16, bottom: 16 };
        await persistBarPrefs();
        renderBar();
      });
    }

    async function handleCaptureFullSession(conversationId: string, config: ScrollConfig) {
      await showBar();
      setState('SCROLL_PUMP');
      try {
        const apiCandidate = await getApiSessionCapture(config.sourceApp, conversationId);
        if (apiCandidate?.turnCount && apiCandidate.turnCount > 0) {
          captureSource = 'api';
          retroactiveStatus = 'API capture';
          renderBar();
          syncState();
          const result = await sendCapture({
            ...apiCandidate,
            captureSource: 'api',
            conversationIdTemporary: config.conversationIdTemporary,
            previousConversationId: config.previousConversationId,
          });
          memoryId = result?.memoryId || memoryId;
          turnCount = Math.max(turnCount, apiCandidate.turnCount || 0);
          await refreshBackendState();
          retroactiveStatus = 'Updated via API';
          syncState();
          setState('LISTENING');
          return {
            status: 'updated',
            reason: 'Updated via API',
            api_used: true,
            dom_used: false,
            captureSource,
            turnCount,
            memoryId,
          };
        }
        captureSource = 'dom_scroll';
        retroactiveStatus = 'DOM fallback';
        renderBar();
        syncState();
        await clearConversation(conversationId);
        const pump = scrollPumpCapture({
          scrollContainerSelector: config.scrollContainer,
          userSelectors: config.userSelectors,
          assistantSelectors: config.assistantSelectors,
          conversationId,
        });
        for await (const progress of pump) {
          turnCount = progress.turnsFound;
          progressValue = progress.progress;
          renderBar();
          syncState();
        }
        const turns = await getTurns(conversationId);
        if (turns.length > 0) {
          const candidate = await buildBulkCapture({
            sourceApp: config.sourceApp,
            conversationId,
            conversationIdTemporary: config.conversationIdTemporary,
            previousConversationId: config.previousConversationId,
            turns: turns.map(t => ({ user: t.userText, assistant: t.assistantText })),
            captureMode: 'retroactive',
            captureSource: 'dom_scroll',
            title: adapter.detectChatTitle(),
          });
          const result = await sendCapture(candidate);
          memoryId = result?.memoryId || memoryId;
          try {
            const legacyBulkId = await sha256('shail_bulk_' + conversationId);
            if (legacyBulkId !== candidate.customId) await api.deleteMemory(legacyBulkId);
          } catch {
            // Best-effort cleanup for old duplicate retroactive records.
          }
          await clearConversation(conversationId);
          await refreshBackendState();
          retroactiveStatus = 'Updated via DOM';
          syncState();
        } else {
          retroactiveStatus = 'No turns found';
          errorText = 'No conversation turns found on this page';
          setState('ERROR');
          window.setTimeout(() => refreshPolicy(), 5000);
          return {
            status: 'no_turns_found',
            reason: errorText,
            api_used: false,
            dom_used: true,
            captureSource,
            turnCount,
            memoryId,
          };
        }
        setState('LISTENING');
        return {
          status: 'updated',
          reason: 'Updated via DOM',
          api_used: false,
          dom_used: true,
          captureSource,
          turnCount,
          memoryId,
        };
      } catch (err) {
        errorText = userFacingError(err);
        retroactiveStatus = 'Failed';
        setState('ERROR');
        window.setTimeout(() => refreshPolicy(), 5000);
        return {
          status: 'failed',
          reason: errorText,
          api_used: captureSource === 'api',
          dom_used: captureSource === 'dom_scroll',
          captureSource,
          turnCount,
          memoryId,
        };
      }
    }

    window.addEventListener('shail-capture-event', ((event: CustomEvent) => {
      const detail = event.detail as { state?: string; turnCount?: number; memoryId?: string };
      if (detail.turnCount !== undefined) turnCount = detail.turnCount;
      if (detail.memoryId) memoryId = detail.memoryId;
      if (detail.state === 'capturing' || detail.state === 'captured' || detail.memoryId) void showBar();
      switch (detail.state) {
        case 'capturing':
          setState('CAPTURING');
          break;
        case 'captured':
          setState('LISTENING');
          refreshBackendState();
          break;
        case 'paused':
          setState('PAUSED');
          break;
        case 'excluded':
          setState('EXCLUDED');
          break;
        case 'error':
          setState('ERROR');
          window.setTimeout(() => refreshPolicy(), 5000);
          break;
        case 'listening':
          if (state === 'IDLE' || state === 'CAPTURING') setState('LISTENING');
          else renderBar();
          break;
      }
    }) as EventListener);

    async function transcriptText(): Promise<string> {
      const id = await ensureMemoryId();
      if (id) {
        try {
          const full = await api.getFullContent(id);
          if (full.content?.trim()) return full.content.trim();
        } catch {
          // fall through to DOM transcript
        }
      }
      const messages = adapter.extractMessages(document);
      if (!messages.length) return 'No transcript is available yet for this chat.';
      return messages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.text}`)
        .join('\n\n---\n\n');
    }

    function showTranscriptModal() {
      if (!shadow) return;
      const existing = shadow.getElementById('shail-transcript-modal');
      existing?.remove();
      const modalHost = document.createElement('div');
      modalHost.id = 'shail-transcript-modal';
      modalHost.innerHTML = `
        <style>
          .modal-overlay {
            position: fixed; inset: 0; background: rgba(0,0,0,0.62);
            z-index: 2147483647; display: flex; align-items: center; justify-content: center;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
          }
          .modal-box {
            background: #101010; border: 1px solid #303030; border-radius: 8px;
            width: min(760px, calc(100vw - 32px)); max-height: min(720px, calc(100vh - 32px));
            color: #eee; box-shadow: 0 12px 34px rgba(0,0,0,0.52); display:flex; flex-direction:column;
          }
          .modal-head { display:flex; align-items:center; gap:10px; padding:12px 14px; border-bottom:1px solid #232323; }
          .modal-head img { width:24px; height:24px; border-radius:6px; }
          .modal-title { flex:1; min-width:0; font-size:13px; font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
          .modal-meta { font-size:11px; color:#888; font-family: ui-monospace, Menlo, monospace; }
          .modal-close { background:transparent; border:1px solid #333; color:#aaa; border-radius:5px; padding:4px 8px; cursor:pointer; }
          .modal-close:hover { color:#fff; background:#1b1b1b; }
          .transcript {
            padding:14px; margin:0; overflow:auto; white-space:pre-wrap;
            font: 12px/1.55 ui-monospace, "SF Mono", Menlo, monospace;
            color:#ddd;
          }
        </style>
        <div class="modal-overlay">
          <div class="modal-box">
            <div class="modal-head">
              <img src="${logoUrl}" alt="SHAIL" />
              <div class="modal-title">${escapeHtml(adapter.detectChatTitle())}</div>
              <div class="modal-meta">${turnCount} ${turnCount === 1 ? 'turn' : 'turns'}</div>
              <button class="modal-close" id="transcript-close">Close</button>
            </div>
            <pre class="transcript" id="transcript-content">Loading transcript...</pre>
          </div>
        </div>
      `;
      shadow.appendChild(modalHost);
      shadow.getElementById('transcript-close')?.addEventListener('click', () => modalHost.remove());
      void transcriptText().then(text => {
        const el = shadow?.getElementById('transcript-content');
        if (el) el.textContent = text;
      });
    }

    browser.runtime.onMessage.addListener(async (message) => {
      if (message.type === 'TRIGGER_SCROLL_PUMP') {
        if (!scrollConfig) {
          return Promise.resolve({
            status: 'unsupported',
            reason: 'Retroactive capture is not supported on this page',
            state,
            platform: adapter.sourceApp,
            title: adapter.detectChatTitle(),
            turnCount,
            progressValue,
            memoryId,
            backendState,
            errorText,
          });
        }
        try {
          const identity = await resolveConversationIdentity(location.href, scrollConfig.sourceApp);
          void handleCaptureFullSession(identity.conversationId, {
            ...scrollConfig,
            conversationIdTemporary: identity.temporary,
            previousConversationId: identity.previousConversationId,
          }).then(result => {
            if (result?.status) {
              retroactiveStatus = result.reason || result.status;
              syncState();
            }
          });
        } catch (err) {
          errorText = userFacingError(err);
          setState('ERROR');
          return Promise.resolve({
            status: 'error',
            reason: errorText,
            state,
            platform: adapter.sourceApp,
            title: adapter.detectChatTitle(),
            turnCount,
            progressValue,
            memoryId,
            backendState,
            errorText,
          });
        }
        return Promise.resolve({
          status: 'started',
          state: 'SCROLL_PUMP',
          platform: adapter.sourceApp,
          title: adapter.detectChatTitle(),
          turnCount,
          progressValue,
          memoryId,
          captureSource,
          retroactiveStatus,
          backendState,
          errorText: '',
        });
      } else if (message.type === 'GET_ACTIVE_CAPTURE_STATE') {
        return Promise.resolve({
          state,
          platform: adapter.sourceApp,
          title: adapter.detectChatTitle(),
          turnCount,
          progressValue,
          memoryId,
          captureSource,
          retroactiveStatus,
          backendState,
          errorText,
        });
      }
    });

    function showEndCaptureModal() {
      if (!shadow) return;
      const modalHost = document.createElement('div');
      modalHost.id = 'shail-end-modal';
      modalHost.innerHTML = `
        <style>
          .modal-overlay {
            position: fixed; inset: 0; background: rgba(0,0,0,0.62);
            z-index: 2147483647; display: flex; align-items: center; justify-content: center;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
          }
          .modal-box {
            background: #111; border: 1px solid #333; border-radius: 8px;
            padding: 20px; width: min(400px, calc(100vw - 36px)); color: #eee;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
          }
          .modal-title { font-size: 15px; font-weight: 600; margin-bottom: 8px; }
          .modal-stats { font-size: 12px; color: #a3a3a3; margin-bottom: 18px; font-family: ui-monospace, Menlo, monospace; }
          .modal-btn {
            display: block; width: 100%; padding: 10px; margin-bottom: 8px;
            border-radius: 6px; border: 1px solid #333; background: #1a1a1a;
            color: #fff; cursor: pointer; text-align: center; font-size: 13px;
          }
          .modal-btn:hover { background: #222; }
          .modal-btn.primary { background: #2563eb; border-color: #2563eb; }
          .modal-error { font-size: 11px; color: #fca5a5; margin-top: 8px; line-height: 1.4; }
        </style>
        <div class="modal-overlay">
          <div class="modal-box">
            <div class="modal-title">End in-session capture</div>
            <div class="modal-stats">${turnCount} ${turnCount === 1 ? 'turn' : 'turns'} · ${pipelineLabel(backendState)}</div>
            <button class="modal-btn primary" id="modal-keep-both">End and keep transcript</button>
            <button class="modal-btn" id="modal-blueprint-only">End after blueprint only</button>
            <button class="modal-btn" id="modal-cancel">Continue capturing</button>
            <div class="modal-error" id="modal-error"></div>
          </div>
        </div>
      `;
      shadow.appendChild(modalHost);
      const close = () => modalHost.remove();
      const showError = (message: string) => {
        const el = shadow?.getElementById('modal-error');
        if (el) el.textContent = message;
      };
      const setRetention = async (policy: 'keep_raw' | 'blueprint_only' | 'decide_later') => {
        const id = await ensureMemoryId();
        if (!id) {
          showError('No captured memory exists yet for this chat.');
          return;
        }
        const response = await browser.runtime.sendMessage({
          type: 'DELETE_TRANSCRIPT_KEEP_BLUEPRINT',
          payload: { memoryId: id, policy },
        });
        if (!response?.ok) {
          showError(response?.error || 'Retention update failed');
          return;
        }
        await refreshBackendState();
        close();
        await setConversationPaused(adapter, true);
        setState('PAUSED');
      };

      shadow.getElementById('modal-keep-both')?.addEventListener('click', () => setRetention('keep_raw'));
      shadow.getElementById('modal-blueprint-only')?.addEventListener('click', () => setRetention('blueprint_only'));
      shadow.getElementById('modal-cancel')?.addEventListener('click', close);
    }

    refreshPolicy();
    refreshBackendState();
    updateTurnCountFromDom();
    window.setInterval(updateTurnCountFromDom, 2000);
    window.setInterval(refreshBackendState, 5000);

    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local') return;
      if (changes[KEY_ACTIVE_CAPTURE]) {
        const next = changes[KEY_ACTIVE_CAPTURE].newValue as { memoryId?: string; backendState?: CaptureSurfaceState } | undefined;
        memoryId = next?.memoryId || memoryId;
        backendState = next?.backendState || backendState;
        if (memoryId || backendState?.memory_id) void showBar();
        renderBar();
      }
    });
  },
});
