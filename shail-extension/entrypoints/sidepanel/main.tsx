import React, { useState, useEffect, useCallback, useRef } from 'react';
import ReactDOM from 'react-dom/client';
import {
  BrainCircuit, Search, X, Copy, Trash2, Pin, PinOff,
  ArrowUpRight, ExternalLink, Loader2, CheckCircle2, Globe,
  BotMessageSquare, Sparkles, Star, ArrowLeft, FileText,
  MessageSquare, AlertCircle, RefreshCw,
} from 'lucide-react';
import { api, cleanContentForDisplay, formatFullInject, userFacingError } from '../../src/lib/api';
import { timeAgo, getSourceMeta } from '../../src/lib/utils';
import type { MemoryRecord, SourceApp, EventType } from '../../src/types/contracts';
import './style.css';

function openSettings() { chrome.runtime.openOptionsPage(); }

const SOURCE_APPS: SourceApp[] = ['chatgpt', 'claude', 'gemini', 'perplexity', 'web'];

// ─── Inject helper ────────────────────────────────────────────────────────────
// Serialised and run directly inside the target tab via chrome.scripting.executeScript.
// Must be entirely self-contained — no imports, no closures over outer scope.
function injectIntoPage(text: string): boolean {
  const h = location.hostname;

  let el: HTMLElement | null = null;
  if (h.includes('chatgpt.com') || h.includes('openai.com')) {
    el = document.querySelector<HTMLElement>('#prompt-textarea');
  } else if (h.includes('claude.ai')) {
    el = (
      document.querySelector<HTMLElement>('[contenteditable="true"][data-placeholder]') ??
      document.querySelector<HTMLElement>('.ProseMirror[contenteditable="true"]')
    );
  } else if (h.includes('gemini.google.com')) {
    el = (
      document.querySelector<HTMLElement>('.ql-editor[contenteditable="true"]') ??
      document.querySelector<HTMLElement>('rich-textarea .ql-editor')
    );
  } else if (h.includes('perplexity.ai')) {
    el = (
      document.querySelector<HTMLElement>('textarea[placeholder]') ??
      document.querySelector<HTMLElement>('textarea')
    );
  }
  if (!el) {
    el = (
      document.querySelector<HTMLElement>('textarea:not([style*="display:none"]):not([style*="display: none"])') ??
      document.querySelector<HTMLElement>('[contenteditable="true"]')
    );
  }

  if (!el) return false;
  el.focus();

  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    const proto = el.tagName === 'TEXTAREA'
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    const current = (el as HTMLTextAreaElement).value;
    const next = current ? `${current}\n${text}` : text;
    if (nativeSetter) nativeSetter.call(el, next);
    else (el as HTMLTextAreaElement).value = next;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  } else if (el.isContentEditable) {
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel?.removeAllRanges();
    sel?.addRange(range);
    const prefix = el.textContent?.trim() ? '\n' : '';
    document.execCommand('insertText', false, prefix + text);
  }

  return true;
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

// ─── Toast ────────────────────────────────────────────────────────────────────

interface ToastState { message: string; type: 'success' | 'info' | 'error' }

function Toast({ toast, onDone }: { toast: ToastState; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 2200);
    return () => clearTimeout(t);
  }, [toast, onDone]);

  return (
    <div
      className="fixed bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium shadow-lg z-50 animate-in"
      style={{
        background: toast.type === 'success'
          ? 'rgba(34,197,94,0.15)'
          : toast.type === 'error'
          ? 'rgba(239,68,68,0.15)'
          : 'rgba(59,130,246,0.15)',
        border: `1px solid ${
          toast.type === 'success' ? 'rgba(34,197,94,0.3)'
          : toast.type === 'error' ? 'rgba(239,68,68,0.3)'
          : 'rgba(59,130,246,0.3)'
        }`,
        color: toast.type === 'success' ? '#86efac'
          : toast.type === 'error'   ? '#fca5a5'
          : '#93c5fd',
      }}
    >
      {toast.type === 'error' ? <AlertCircle size={12} /> : <CheckCircle2 size={12} />}
      {toast.message}
    </div>
  );
}

// ─── Source icon ──────────────────────────────────────────────────────────────

function SourceIcon({ app, size = 14 }: { app: SourceApp; size?: number }) {
  const p = { size, strokeWidth: 1.8 };
  switch (app) {
    case 'chatgpt':    return <BotMessageSquare {...p} />;
    case 'claude':     return <Sparkles {...p} />;
    case 'gemini':     return <Star {...p} />;
    case 'perplexity': return <Search {...p} />;
    default:           return <Globe {...p} />;
  }
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function CardSkeleton() {
  return (
    <div className="rounded-xl p-3 space-y-2" style={{ background: '#13131a', border: '1px solid #1e1e2e' }}>
      <div className="flex items-center gap-2">
        <div className="w-5 h-5 rounded-md animate-pulse" style={{ background: '#1e1e2e' }} />
        <div className="h-3 w-16 rounded animate-pulse" style={{ background: '#1e1e2e' }} />
        <div className="ml-auto h-3 w-10 rounded animate-pulse" style={{ background: '#1e1e2e' }} />
      </div>
      <div className="h-3 w-full rounded animate-pulse" style={{ background: '#1e1e2e' }} />
      <div className="h-3 w-3/4 rounded animate-pulse" style={{ background: '#1e1e2e' }} />
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="p-4 space-y-4 animate-pulse">
      <div className="h-4 w-3/4 rounded" style={{ background: '#1e1e2e' }} />
      <div className="h-3 w-1/2 rounded" style={{ background: '#1e1e2e' }} />
      <div className="h-px w-full my-4" style={{ background: '#1e1e2e' }} />
      <div className="space-y-2">
        <div className="h-2 w-16 rounded" style={{ background: '#1e1e2e' }} />
        <div className="h-3 w-full rounded" style={{ background: '#1e1e2e' }} />
        <div className="h-3 w-5/6 rounded" style={{ background: '#1e1e2e' }} />
        <div className="h-3 w-4/6 rounded" style={{ background: '#1e1e2e' }} />
      </div>
      <div className="space-y-2 pt-4">
        <div className="h-2 w-12 rounded" style={{ background: '#1e1e2e' }} />
        {[...Array(8)].map((_, i) => (
          <div key={i} className="h-3 rounded" style={{ background: '#1e1e2e', width: `${70 + Math.random() * 28}%` }} />
        ))}
      </div>
    </div>
  );
}

// ─── Action button ────────────────────────────────────────────────────────────

function ActionBtn({
  icon, label, color, onClick, disabled = false,
}: {
  icon: React.ReactNode; label: string; color: string; onClick: () => void; disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      disabled={disabled}
      className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      style={{
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid #1e1e2e',
        color: '#4b5563',
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLButtonElement).style.color = color;
        (e.currentTarget as HTMLButtonElement).style.borderColor = color + '40';
        (e.currentTarget as HTMLButtonElement).style.background = color + '10';
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLButtonElement).style.color = '#4b5563';
        (e.currentTarget as HTMLButtonElement).style.borderColor = '#1e1e2e';
        (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.03)';
      }}
    >
      {icon}
      {label}
    </button>
  );
}

// ─── Memory card (list view) ──────────────────────────────────────────────────

interface MemoryCardProps {
  record: MemoryRecord;
  injecting: boolean;
  index?: number;
  onOpen:   (r: MemoryRecord) => void;
  onInject: (r: MemoryRecord, e: React.MouseEvent) => void;
  onCopy:   (r: MemoryRecord, e: React.MouseEvent) => void;
  onPin:    (r: MemoryRecord, e: React.MouseEvent) => void;
  onDelete: (r: MemoryRecord, e: React.MouseEvent) => void;
}

// PLACEHOLDER — kept for TypeScript only. Use MemoryCardFixed instead.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function _MemoryCard(_p: MemoryCardProps) {
  return null;
}

// Better card — re-done with proper event wiring and delete confirmation
function MemoryCardFixed({ record, injecting, index = 0, onOpen, onInject, onCopy, onPin, onDelete }: MemoryCardProps) {
  const meta = getSourceMeta(record.sourceApp);
  const [deleting,       setDeleting]       = useState(false);
  const [hovered,        setHovered]        = useState(false);
  const [deleteConfirm,  setDeleteConfirm]  = useState(false);

  // Auto-cancel delete confirm after 4 seconds
  useEffect(() => {
    if (!deleteConfirm) return;
    const t = setTimeout(() => setDeleteConfirm(false), 4000);
    return () => clearTimeout(t);
  }, [deleteConfirm]);

  const staggerDelay = Math.min(index * 35, 200);

  return (
    <div
      className={`rounded-xl overflow-hidden transition-all cursor-pointer select-none ${deleting ? 'opacity-40 pointer-events-none' : ''}`}
      style={{
        background: '#13131a',
        border: `1px solid ${hovered ? '#2d2d3e' : '#1e1e2e'}`,
        boxShadow: hovered ? '0 2px 16px rgba(0,0,0,0.45)' : 'none',
        transition: 'border-color 0.15s, box-shadow 0.15s, opacity 0.2s',
        animation: 'shailFadeUp 180ms ease both',
        animationDelay: `${staggerDelay}ms`,
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => !deleteConfirm && onOpen(record)}
    >
      {/* ── Clickable body ── */}
      <div className="p-3 pb-2">
        <div className="flex items-center gap-2 mb-2">
          <div
            className="w-5 h-5 rounded-md flex items-center justify-center flex-shrink-0"
            style={{ background: meta.bg, color: meta.color }}
          >
            <SourceIcon app={record.sourceApp} size={11} />
          </div>
          <span className="text-[10px] font-semibold" style={{ color: meta.color }}>
            {meta.label}
          </span>
          {record.pinned && <Pin size={9} className="text-yellow-400 opacity-70" />}
          <span className="ml-auto text-[10px] flex items-center gap-1" style={{ color: '#374151' }}>
            {timeAgo(record.timestamp)}
          </span>
        </div>

        {record.title && (
          <div className="text-[11px] font-semibold text-white mb-1 line-clamp-1">
            {record.title}
          </div>
        )}

        <div className="text-[11px] leading-relaxed line-clamp-2" style={{ color: '#6b7280' }}>
          {cleanContentForDisplay(record.summary) || 'Click to view full memory…'}
        </div>
      </div>

      {/* ── Tap hint ── */}
      <div
        className="flex items-center gap-1.5 px-3 py-1.5"
        style={{
          borderTop: '1px dashed #1a1a24',
          color: hovered ? '#4b5563' : '#2d2d3e',
          transition: 'color 0.15s',
          fontSize: '10px',
        }}
      >
        <FileText size={9} />
        <span>Open full memory</span>
        <span className="ml-auto" style={{ opacity: hovered ? 0.7 : 0.3 }}>→</span>
      </div>

      {/* ── Action strip — clicks do NOT open detail ── */}
      <div
        className="flex items-center gap-1 px-3 py-2"
        style={{ borderTop: '1px solid #13131a', background: 'rgba(0,0,0,0.3)' }}
        onClick={e => e.stopPropagation()}
      >
        {!deleteConfirm ? (
          <>
            <ActionBtn
              icon={injecting ? <Loader2 size={11} className="animate-spin" /> : <ArrowUpRight size={11} />}
              label={injecting ? '…' : 'Inject'}
              color="#3b82f6"
              disabled={injecting}
              onClick={() => onInject(record, { stopPropagation: () => {} } as React.MouseEvent)}
            />
            <ActionBtn
              icon={<Copy size={11} />}
              label="Copy"
              color="#6b7280"
              onClick={() => onCopy(record, { stopPropagation: () => {} } as React.MouseEvent)}
            />
            <ActionBtn
              icon={record.pinned ? <PinOff size={11} /> : <Pin size={11} />}
              label={record.pinned ? 'Unpin' : 'Pin'}
              color="#eab308"
              onClick={() => onPin(record, { stopPropagation: () => {} } as React.MouseEvent)}
            />
            <ActionBtn
              icon={<Trash2 size={11} />}
              label="Delete"
              color="#ef4444"
              onClick={() => setDeleteConfirm(true)}
            />
          </>
        ) : (
          /* ── Confirm delete strip ── */
          <div className="flex items-center gap-2 w-full">
            <span className="text-[10px] flex-1" style={{ color: '#f87171' }}>
              Delete this memory?
            </span>
            <ActionBtn
              icon={<X size={11} />}
              label="Cancel"
              color="#6b7280"
              onClick={() => setDeleteConfirm(false)}
            />
            <ActionBtn
              icon={<Trash2 size={11} />}
              label="Confirm"
              color="#ef4444"
              onClick={() => {
                setDeleting(true);
                setDeleteConfirm(false);
                onDelete(record, { stopPropagation: () => {} } as React.MouseEvent);
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}


// ─── Full memory detail view ──────────────────────────────────────────────────

interface FullContent {
  content:   string;
  eventType: EventType;
  title:     string;
  userText:  string;
  assistantText: string;
  pageText:  string;
}

function parseFullContent(content: string, eventType: EventType): FullContent {
  const nlnl   = content.indexOf('\n\n');
  const header = nlnl > 0 ? content.slice(0, nlnl)  : '';
  const body   = nlnl > 0 ? content.slice(nlnl + 2) : content;

  const titleMatch  = header.match(/^\[\w+\]\s+(.+)/);
  const title       = titleMatch?.[1]?.trim() ?? '';

  const userMatch      = body.match(/^User:\s*([\s\S]*?)(?=\n\nAssistant:|$)/);
  const assistantMatch = body.match(/\n\nAssistant:\s*([\s\S]*)$/s);

  const userText      = userMatch?.[1]?.trim()      ?? '';
  const assistantText = assistantMatch?.[1]?.trim() ?? '';
  const pageText      = (!userText && !assistantText) ? body.trim() : '';

  return { content, eventType, title, userText, assistantText, pageText };
}

// Renders one labelled section of the detail view
function Section({
  label, text, icon, accent = '#374151',
}: {
  label: string; text: string; icon: React.ReactNode; accent?: string;
}) {
  return (
    <div className="mb-5">
      {/* Section label */}
      <div className="flex items-center gap-2 mb-2">
        <span style={{ color: accent }}>{icon}</span>
        <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: accent }}>
          {label}
        </span>
        <div className="flex-1 h-px" style={{ background: '#1e1e2e' }} />
      </div>
      {/* Text block */}
      <div
        className="text-xs leading-relaxed rounded-lg p-3 whitespace-pre-wrap break-words"
        style={{
          background: '#0d0d14',
          border: '1px solid #1a1a2a',
          color: '#9ca3af',
          fontFamily: label === 'Answer' || label === 'Content'
            ? 'inherit' : 'inherit',
        }}
      >
        {text}
      </div>
    </div>
  );
}

interface MemoryDetailViewProps {
  record:    MemoryRecord;
  onBack:    () => void;
  onInject:  (record: MemoryRecord) => void;
  onCopy:    (record: MemoryRecord) => void;
  onDelete:  (record: MemoryRecord) => void;
  injecting: boolean;
  showToast: (msg: string, type?: 'success' | 'info' | 'error') => void;
}

function MemoryDetailView({
  record, onBack, onInject, onCopy, onDelete, injecting, showToast,
}: MemoryDetailViewProps) {
  const meta = getSourceMeta(record.sourceApp);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [full, setFull] = useState<FullContent | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Fetch full content from Supermemory on mount
  useEffect(() => {
    let cancelled = false;
    setLoadState('loading');
    setFull(null);

    api.getFullContent(record.id)
      .then(({ content, eventType }) => {
        if (cancelled) return;
        setFull(parseFullContent(content, eventType));
        setLoadState('ready');
      })
      .catch(() => {
        if (cancelled) return;
        // Fall back to whatever we have in the record summary
        const fallbackContent = record.summary || record.title || '';
        setFull(parseFullContent(
          `[${record.sourceApp}] ${record.title}\n\n${fallbackContent}`,
          record.eventType,
        ));
        setLoadState('error');
      });

    return () => { cancelled = true; };
  }, [record.id]); // eslint-disable-line

  const isAi  = full?.eventType === 'ai_conversation';
  const title = full?.title || record.title || 'Untitled memory';

  return (
    <div
      className="flex flex-col h-full"
      style={{ background: '#0a0a0f', animation: 'slideInRight 0.2s ease' }}
    >
      <style>{`
        @keyframes slideInRight {
          from { opacity: 0; transform: translateX(18px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>

      {/* ── Detail header ── */}
      <div
        className="flex-shrink-0 flex items-center gap-2 px-3 py-2.5"
        style={{ borderBottom: '1px solid #1e1e2e' }}
      >
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg transition-colors"
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid #1e1e2e',
            color: '#6b7280',
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLButtonElement).style.color = '#9ca3af';
            (e.currentTarget as HTMLButtonElement).style.borderColor = '#2d2d3e';
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.color = '#6b7280';
            (e.currentTarget as HTMLButtonElement).style.borderColor = '#1e1e2e';
          }}
        >
          <ArrowLeft size={11} /> Back
        </button>

        {/* Source badge */}
        <div
          className="flex items-center gap-1.5 px-2 py-1 rounded-lg"
          style={{ background: meta.bg, border: `1px solid ${meta.color}30` }}
        >
          <SourceIcon app={record.sourceApp} size={10} />
          <span className="text-[10px] font-bold" style={{ color: meta.color }}>{meta.label}</span>
        </div>

        <span className="text-[10px] ml-auto" style={{ color: '#374151' }}>
          {timeAgo(record.timestamp)}
        </span>
      </div>

      {/* ── Scrollable body ── */}
      <div className="flex-1 overflow-y-auto min-h-0 p-4">

        {/* Error banner (still shows fallback content) */}
        {loadState === 'error' && (
          <div
            className="flex items-center gap-2 text-[10px] rounded-lg px-3 py-2 mb-4"
            style={{
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.2)',
              color: '#fca5a5',
            }}
          >
            <AlertCircle size={11} />
            Could not fetch full content — showing cached preview
          </div>
        )}

        {/* Loading skeleton */}
        {loadState === 'loading' && <DetailSkeleton />}

        {/* Content */}
        {(loadState === 'ready' || loadState === 'error') && full && (
          <>
            {/* Title */}
            <div className="mb-4">
              <h1 className="text-sm font-bold text-white leading-snug mb-1">
                {title}
              </h1>
              {record.sourceUrl && (
                <a
                  href={record.sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[10px] flex items-center gap-1 w-fit"
                  style={{ color: '#374151' }}
                  onClick={e => e.stopPropagation()}
                >
                  <ExternalLink size={9} />
                  <span className="truncate max-w-[220px]">{record.sourceUrl}</span>
                </a>
              )}
            </div>

            <div className="h-px mb-4" style={{ background: '#1e1e2e' }} />

            {/* AI conversation */}
            {isAi && (
              <>
                {full.userText && (
                  <Section
                    label="Your question"
                    text={full.userText}
                    icon={<MessageSquare size={10} />}
                    accent="#60a5fa"
                  />
                )}
                {full.assistantText && (
                  <Section
                    label="Answer"
                    text={full.assistantText}
                    icon={<BotMessageSquare size={10} />}
                    accent="#a78bfa"
                  />
                )}
                {/* If neither parsed, show raw cleaned content */}
                {!full.userText && !full.assistantText && (
                  <Section
                    label="Content"
                    text={cleanContentForDisplay(full.content)}
                    icon={<FileText size={10} />}
                    accent="#6b7280"
                  />
                )}
              </>
            )}

            {/* Web page capture */}
            {!isAi && (
              <Section
                label="Saved content"
                text={full.pageText || cleanContentForDisplay(full.content)}
                icon={<FileText size={10} />}
                accent="#34d399"
              />
            )}

            {/* Tags */}
            {record.tags && record.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {record.tags.map(tag => (
                  <span
                    key={tag}
                    className="text-[10px] px-2 py-0.5 rounded-full"
                    style={{
                      background: 'rgba(59,130,246,0.08)',
                      border: '1px solid rgba(59,130,246,0.15)',
                      color: '#60a5fa',
                    }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* ── Action footer ── */}
      <div
        className="flex-shrink-0 flex items-center gap-2 px-4 py-3"
        style={{ borderTop: '1px solid #1e1e2e', background: 'rgba(0,0,0,0.3)' }}
      >
        {/* Inject */}
        <button
          onClick={() => onInject(record)}
          disabled={injecting || deleting}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
          style={{
            background: 'rgba(59,130,246,0.12)',
            border: '1px solid rgba(59,130,246,0.25)',
            color: '#60a5fa',
            flex: 1,
            justifyContent: 'center',
          }}
        >
          {injecting
            ? <><Loader2 size={12} className="animate-spin" /> Injecting…</>
            : <><ArrowUpRight size={12} /> Inject into chat</>
          }
        </button>

        {/* Copy */}
        <button
          onClick={() => onCopy(record)}
          disabled={deleting}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid #1e1e2e',
            color: '#6b7280',
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLButtonElement).style.color = '#9ca3af';
            (e.currentTarget as HTMLButtonElement).style.borderColor = '#374151';
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.color = '#6b7280';
            (e.currentTarget as HTMLButtonElement).style.borderColor = '#1e1e2e';
          }}
        >
          <Copy size={12} /> Copy
        </button>

        {/* Pin */}
        <button
          onClick={async () => {
            try {
              await api.patchMemory(record.id, { pinned: !record.pinned }, record);
              showToast(record.pinned ? 'Unpinned' : 'Pinned ★');
            } catch {
              showToast('Could not update', 'info');
            }
          }}
          disabled={deleting}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
          style={{
            background: record.pinned ? 'rgba(234,179,8,0.1)' : 'rgba(255,255,255,0.03)',
            border: `1px solid ${record.pinned ? 'rgba(234,179,8,0.25)' : '#1e1e2e'}`,
            color: record.pinned ? '#fbbf24' : '#6b7280',
          }}
        >
          {record.pinned ? <PinOff size={12} /> : <Pin size={12} />}
        </button>

        {/* Delete */}
        <button
          onClick={() => {
            setDeleting(true);
            onDelete(record);
          }}
          disabled={deleting}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
          style={{
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.15)',
            color: '#f87171',
          }}
        >
          {deleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
        </button>
      </div>
    </div>
  );
}

// ─── Filter pills ─────────────────────────────────────────────────────────────

function FilterPills({
  active, onChange,
}: {
  active: SourceApp | 'all';
  onChange: (v: SourceApp | 'all') => void;
}) {
  const pills: Array<{ key: SourceApp | 'all'; label: string }> = [
    { key: 'all', label: 'All' },
    ...SOURCE_APPS.map(a => ({ key: a, label: getSourceMeta(a).label })),
  ];

  return (
    <div className="flex gap-1.5 overflow-x-auto pb-0.5 scrollbar-none">
      {pills.map(({ key, label }) => {
        const isActive = active === key;
        const meta = key === 'all' ? null : getSourceMeta(key);
        return (
          <button
            key={key}
            onClick={() => onChange(key)}
            className="flex-shrink-0 px-2.5 py-1 rounded-full text-[10px] font-medium transition-all"
            style={{
              background: isActive
                ? (meta ? meta.bg : 'rgba(59,130,246,0.15)')
                : 'rgba(255,255,255,0.04)',
              color: isActive
                ? (meta ? meta.color : '#60a5fa')
                : '#6b7280',
              border: `1px solid ${isActive
                ? (meta ? meta.color + '40' : 'rgba(59,130,246,0.3)')
                : '#1e1e2e'}`,
            }}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

// ─── Empty / Error states ─────────────────────────────────────────────────────

function EmptyState({ query }: { query: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-6 text-center gap-2">
      <Search size={22} className="opacity-20" style={{ color: '#6b7280' }} />
      <div className="text-xs font-medium text-white opacity-40 mt-1">
        {query ? `No memories matching "${query}"` : 'No memories yet'}
      </div>
      <div className="text-[11px] leading-relaxed" style={{ color: '#374151' }}>
        {query
          ? 'Try a different search term or filter.'
          : 'Browse the web or chat with an AI — SHAIL captures automatically.'}
      </div>
    </div>
  );
}

function UnauthState() {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-6 text-center gap-3">
      <div
        className="w-10 h-10 rounded-full flex items-center justify-center"
        style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.15)' }}
      >
        <BrainCircuit size={18} className="text-blue-400 opacity-60" />
      </div>
      <div>
        <div className="text-sm font-medium text-white mb-1">Sign in to SHAIL</div>
        <div className="text-[11px] leading-relaxed" style={{ color: '#6b7280' }}>
          Sign in with Google on the dashboard to start capturing your memory.
        </div>
      </div>
      <button
        onClick={() => openSettings()}
        className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg mt-1"
        style={{
          background: 'rgba(59,130,246,0.12)',
          color: '#60a5fa',
          border: '1px solid rgba(59,130,246,0.2)',
        }}
      >
        Open Dashboard <ExternalLink size={11} />
      </button>
    </div>
  );
}

// ─── Ask mode panel ───────────────────────────────────────────────────────────

const EXAMPLE_QUESTIONS = [
  'What did I learn about React?',
  'What AI conversations have I had?',
  'What articles did I read recently?',
  'What questions did I ask ChatGPT?',
];

interface AskPanelProps {
  view: ViewState;
  onOpenRecord: (r: MemoryRecord) => void;
  onInject: (r: MemoryRecord) => void;
  onCopy: (r: MemoryRecord) => void;
  onPin: (r: MemoryRecord) => void;
  onDelete: (r: MemoryRecord) => void;
  injectingId: string | null;
  showToast: (msg: string, type?: 'success' | 'info' | 'error') => void;
}

function AskPanel({
  view, onOpenRecord, onInject, onCopy, onPin, onDelete, injectingId, showToast,
}: AskPanelProps) {
  const [input,    setInput]    = useState('');
  const [question, setQuestion] = useState('');
  const [results,  setResults]  = useState<MemoryRecord[]>([]);
  const [asking,   setAsking]   = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  async function submit(q: string) {
    const trimmed = q.trim();
    if (!trimmed || asking) return;
    setQuestion(trimmed);
    setAsking(true);
    setResults([]);
    try {
      const bundle = await api.search({ query: trimmed });
      setResults(bundle.items);
    } catch (err) {
      const msg = (err as Error).message ?? '';
      showToast(
        msg === 'BACKEND_OFFLINE' ? 'SHAIL offline — start the backend app'
        : msg === 'BACKEND_TIMEOUT' ? 'Backend timeout — is the app running?'
        : 'Search failed — try again',
        'error',
      );
    } finally {
      setAsking(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit(input);
    }
  }

  function buildSynthesis(items: MemoryRecord[]): string {
    return items
      .slice(0, 3)
      .map(r => {
        const label = getSourceMeta(r.sourceApp).label;
        const text  = cleanContentForDisplay(r.summary).slice(0, 180).trimEnd();
        const suffix = r.summary.length > 180 ? '…' : '';
        return `${r.title || label}:\n${text}${suffix}`;
      })
      .join('\n\n');
  }

  // AskPanel has no unauthenticated state in local mode

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Input area */}
      <div
        className="flex-shrink-0 px-3 pt-3 pb-2"
        style={{ borderBottom: '1px solid #1e1e2e' }}
      >
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: '#13131a', border: '1px solid #1e1e2e' }}
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="What did you learn about…?"
            rows={2}
            className="w-full bg-transparent text-xs placeholder-gray-700 outline-none resize-none px-3 pt-3 pb-1"
            style={{ minHeight: 52, lineHeight: '1.5', color: '#e5e7eb' }}
            autoFocus
          />
          <div
            className="flex items-center justify-between px-3 pb-2 pt-1"
            style={{ color: '#374151' }}
          >
            <span className="text-[10px]">Enter ↵ to search · Shift+Enter for newline</span>
            <button
              onClick={() => submit(input)}
              disabled={!input.trim() || asking}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-all disabled:opacity-30"
              style={{
                background: input.trim() ? 'rgba(59,130,246,0.15)' : 'transparent',
                color: input.trim() ? '#60a5fa' : '#374151',
                border: `1px solid ${input.trim() ? 'rgba(59,130,246,0.25)' : 'transparent'}`,
              }}
            >
              {asking
                ? <Loader2 size={10} className="animate-spin" />
                : <Sparkles size={10} />
              }
              Ask
            </button>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto min-h-0">

        {/* Pre-submit suggestions */}
        {!question && !asking && (
          <div className="p-3 space-y-2">
            <div
              className="text-[9px] uppercase tracking-widest px-0.5 mb-1"
              style={{ color: '#374151' }}
            >
              Try asking…
            </div>
            {EXAMPLE_QUESTIONS.map(q => (
              <button
                key={q}
                onClick={() => { setInput(q); submit(q); }}
                className="w-full text-left px-3 py-2 rounded-xl text-[11px] transition-all"
                style={{ background: '#13131a', border: '1px solid #1e1e2e', color: '#6b7280' }}
                onMouseEnter={e => {
                  (e.currentTarget as HTMLElement).style.borderColor = '#2d2d3e';
                  (e.currentTarget as HTMLElement).style.color = '#9ca3af';
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLElement).style.borderColor = '#1e1e2e';
                  (e.currentTarget as HTMLElement).style.color = '#6b7280';
                }}
              >
                <Sparkles size={10} className="inline mr-2 opacity-40" />
                {q}
              </button>
            ))}
          </div>
        )}

        {/* Searching spinner */}
        {asking && (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <Loader2 size={20} className="animate-spin text-blue-400 opacity-50" />
            <div className="text-xs" style={{ color: '#374151' }}>Searching your memories…</div>
          </div>
        )}

        {/* Results */}
        {!asking && question && (
          <div className="p-3 space-y-3">
            {/* New question button */}
            <button
              onClick={() => { setQuestion(''); setResults([]); setInput(''); setTimeout(() => inputRef.current?.focus(), 50); }}
              className="flex items-center gap-1.5 text-[10px] opacity-50 hover:opacity-100 transition-opacity"
              style={{ color: '#6b7280' }}
            >
              <X size={10} /> Clear · ask another question
            </button>

            {results.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 px-4 text-center gap-2">
                <Search size={20} className="opacity-20" style={{ color: '#6b7280' }} />
                <div className="text-xs font-medium text-white opacity-40 mt-1">No memories found</div>
                <div className="text-[11px] leading-relaxed" style={{ color: '#374151' }}>
                  Nothing in your memory store matches this question yet.
                </div>
              </div>
            ) : (
              <>
                {/* Synthesis block */}
                <div
                  className="rounded-xl p-3 space-y-2"
                  style={{
                    background: 'rgba(59,130,246,0.05)',
                    border: '1px solid rgba(59,130,246,0.12)',
                  }}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <Sparkles size={11} className="text-blue-400" />
                    <span className="text-[10px] font-semibold text-blue-400 uppercase tracking-wide">
                      From your memory
                    </span>
                  </div>
                  <div
                    className="text-[11px] leading-relaxed whitespace-pre-wrap"
                    style={{ color: '#9ca3af' }}
                  >
                    {buildSynthesis(results)}
                  </div>
                </div>

                {/* Source label */}
                <div
                  className="text-[9px] uppercase tracking-widest px-0.5"
                  style={{ color: '#374151' }}
                >
                  {results.length} {results.length === 1 ? 'source' : 'sources'} found
                </div>

                {/* Memory cards */}
                {results.map(record => (
                  <MemoryCardFixed
                    key={record.id}
                    record={record}
                    injecting={injectingId === record.id}
                    onOpen={onOpenRecord}
                    onInject={r => onInject(r)}
                    onCopy={r => onCopy(r)}
                    onPin={r => onPin(r)}
                    onDelete={r => onDelete(r)}
                  />
                ))}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main sidepanel ───────────────────────────────────────────────────────────

type ViewState = 'loading' | 'unauthenticated' | 'error' | 'ready';
type BackendStatus = 'checking' | 'online' | 'offline';

function Sidepanel() {
  const [panelMode,      setPanelMode]      = useState<'browse' | 'ask'>('browse');
  const [view,           setView]           = useState<ViewState>('loading');
  const [backendStatus,  setBackendStatus]  = useState<BackendStatus>('checking');
  const [query,          setQuery]          = useState('');
  const [sourceFilter,   setSourceFilter]   = useState<SourceApp | 'all'>('all');
  const [records,        setRecords]        = useState<MemoryRecord[]>([]);
  const [searching,      setSearching]      = useState(false);
  const [toast,          setToast]          = useState<ToastState | null>(null);
  const [injectingId,    setInjectingId]    = useState<string | null>(null);
  const [lastSearchError, setLastSearchError] = useState<string | null>(null);

  // ── Detail view state ──────────────────────────────────────────────────────
  const [selectedRecord, setSelectedRecord] = useState<MemoryRecord | null>(null);

  const searchRef = useRef<HTMLInputElement>(null);
  const debouncedQuery = useDebounce(query, 300);

  // ── Backend health ping ────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    const ping = async () => {
      try {
        const res = await fetch('http://localhost:8000/browser/me', {
          signal: AbortSignal.timeout(2000),
        });
        if (!cancelled) setBackendStatus(res.ok ? 'online' : 'offline');
      } catch {
        if (!cancelled) setBackendStatus('offline');
      }
    };
    ping();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line

  // ── Search ─────────────────────────────────────────────────────────────────

  const doSearch = useCallback(async (q: string, src: SourceApp | 'all') => {
    setSearching(true);
    setRecords([]); // clear stale data immediately so spinner shows without old results
    try {
      const bundle = await api.search({
        query: q,
        filters: src !== 'all' ? { sourceApp: src } : undefined,
      });
      setRecords(bundle.items);
      setView('ready');
      setLastSearchError(null);
    } catch (err) {
      const msg = (err as Error).message ?? '';
      if (msg === 'BACKEND_OFFLINE' || msg === 'BACKEND_TIMEOUT') {
        setBackendStatus('offline');
        // Browse (empty query) falls back to local index — don't show error state
        if (!q.trim()) {
          setView('ready');
        } else {
          setView('error');
          setLastSearchError('SHAIL offline — start the backend app to search');
        }
      } else {
        setView('error');
        setLastSearchError(userFacingError(err));
        showToast(userFacingError(err), 'error');
      }
    } finally {
      setSearching(false);
    }
  }, []); // eslint-disable-line — view removed from deps; behaviour must not vary by view state

  useEffect(() => {
    doSearch(debouncedQuery, sourceFilter);
  }, [debouncedQuery, sourceFilter]); // eslint-disable-line

  // ── Auto-focus search when sidepanel is opened via Ctrl+Space ──────────────
  // Two paths:
  //   A) Fresh open  — storage flag is already set when the panel mounts
  //   B) Already open — background sets the flag and storage.onChanged fires
  useEffect(() => {
    function focusSearch() {
      setSelectedRecord(null);  // back to list if detail view is open
      // Small delay so the DOM has settled after any view-state change
      setTimeout(() => searchRef.current?.focus(), 80);
    }

    // Path A: check flag on mount (sidepanel just opened)
    chrome.storage.local.get('shail_focus_search').then(result => {
      if (result['shail_focus_search']) {
        chrome.storage.local.remove('shail_focus_search');
        focusSearch();
      }
    });

    // Path B: watch for flag being set while panel is already open
    const storageListener = (
      changes: Record<string, chrome.storage.StorageChange>,
      area: string,
    ) => {
      if (area === 'local' && changes['shail_focus_search']?.newValue === true) {
        chrome.storage.local.remove('shail_focus_search');
        focusSearch();
      }
    };
    chrome.storage.onChanged.addListener(storageListener);
    return () => chrome.storage.onChanged.removeListener(storageListener);
  }, []); // eslint-disable-line

  // ── Ctrl/Cmd+K also focuses search ────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        if (selectedRecord) setSelectedRecord(null);
        searchRef.current?.focus();
      }
      if (e.key === 'Escape' && selectedRecord) {
        setSelectedRecord(null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [selectedRecord]);

  // ── Toast ──────────────────────────────────────────────────────────────────

  function showToast(message: string, type: ToastState['type'] = 'success') {
    setToast({ message, type });
  }

  // ── Inject ─────────────────────────────────────────────────────────────────

  async function handleInject(record: MemoryRecord) {
    if (injectingId) return;
    setInjectingId(record.id);

    let text: string;
    try {
      const { content, eventType } = await api.getFullContent(record.id);
      text = formatFullInject(content, eventType, getSourceMeta(record.sourceApp).label);
    } catch {
      const cleanSummary = cleanContentForDisplay(record.summary || record.title);
      text = `--- Prior context (${getSourceMeta(record.sourceApp).label}) ---\n${cleanSummary}\n\n`;
    }

    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tab?.id) {
        const results = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func:   injectIntoPage,
          args:   [text],
        });
        if (results?.[0]?.result === true) {
          showToast('Injected into composer!');
          setInjectingId(null);
          return;
        }
        showToast('No chat input found — open a chat first', 'info');
        setInjectingId(null);
        return;
      }
    } catch { /* chrome:// pages */ }

    try {
      await navigator.clipboard.writeText(text);
      showToast('Copied to clipboard — paste into your chat', 'info');
    } catch {
      showToast('Copy failed — try manually', 'info');
    }

    setInjectingId(null);
  }

  // ── Copy ───────────────────────────────────────────────────────────────────

  async function handleCopy(record: MemoryRecord) {
    try {
      const { content, eventType } = await api.getFullContent(record.id);
      const text = formatFullInject(content, eventType, getSourceMeta(record.sourceApp).label);
      await navigator.clipboard.writeText(text);
      showToast('Copied to clipboard');
    } catch {
      try {
        await navigator.clipboard.writeText(cleanContentForDisplay(record.summary || record.title));
        showToast('Copied (preview only)', 'info');
      } catch {
        showToast('Copy failed', 'info');
      }
    }
  }

  // ── Pin ────────────────────────────────────────────────────────────────────

  async function handlePin(record: MemoryRecord) {
    try {
      const updated = await api.patchMemory(record.id, { pinned: !record.pinned }, record);
      setRecords(prev => prev.map(r => r.id === record.id ? updated : r));
      // Also update selected record if open
      if (selectedRecord?.id === record.id) setSelectedRecord(updated);
      showToast(updated.pinned ? 'Pinned ★' : 'Unpinned');
    } catch {
      showToast('Could not update — try again', 'info');
    }
  }

  // ── Delete ─────────────────────────────────────────────────────────────────

  async function handleDelete(record: MemoryRecord) {
    // ── Optimistic: remove card immediately ─────────────────────────────────
    let prevRecords: MemoryRecord[] = [];
    setRecords(prev => {
      prevRecords = prev;
      return prev.filter(r => r.id !== record.id);
    });
    if (selectedRecord?.id === record.id) setSelectedRecord(null);

    // Remove from local index immediately so it won't reappear
    let prevIndex: Array<{ id: string }> = [];
    try {
      const stored = await browser.storage.local.get('shail_doc_index');
      prevIndex = (stored['shail_doc_index'] as Array<{ id: string }>) ?? [];
      await browser.storage.local.set({
        shail_doc_index: prevIndex.filter(e => e.id !== record.id),
      });
    } catch { /* non-critical */ }

    // ── Background API call ─────────────────────────────────────────────────
    try {
      await api.deleteMemory(record.id);
      showToast('Memory deleted');
    } catch {
      // Rollback: restore card at original position + restore local index
      setRecords(prevRecords);
      if (selectedRecord?.id === record.id) setSelectedRecord(record);
      try {
        await browser.storage.local.set({ shail_doc_index: prevIndex });
      } catch { /* non-critical */ }
      showToast('Delete failed — try again', 'error');
    }
  }

  // ── Shared header ──────────────────────────────────────────────────────────

  const Header = () => (
    <div
      className="flex-shrink-0 flex items-center gap-2 px-4 py-3"
      style={{ borderBottom: '1px solid #1e1e2e' }}
    >
      <div
        className="w-6 h-6 rounded-md flex items-center justify-center"
        style={{ background: 'rgba(59,130,246,0.12)' }}
      >
        <BrainCircuit size={13} className="text-blue-400" />
      </div>
      <span className="text-xs font-bold text-white tracking-wide">SHAIL Memory</span>
      <div className="ml-auto flex items-center gap-3">
        {searching && <Loader2 size={11} className="text-gray-600 animate-spin" />}
        <div className="flex items-center gap-1.5">
          <div
            className="w-1.5 h-1.5 rounded-full"
            style={{
              background: backendStatus === 'online'
                ? '#22c55e'
                : backendStatus === 'checking'
                ? '#f59e0b'
                : '#ef4444',
              animation: backendStatus === 'checking' ? 'pulse 1.5s cubic-bezier(0.4,0,0.6,1) infinite' : 'none',
            }}
          />
          <span
            className="text-[10px] font-medium"
            style={{
              color: backendStatus === 'online'
                ? '#22c55e'
                : backendStatus === 'checking'
                ? '#f59e0b'
                : '#ef4444',
            }}
          >
            {backendStatus === 'online' ? 'Active' : backendStatus === 'checking' ? 'Connecting…' : 'Offline'}
          </span>
        </div>
        <button
          onClick={() => doSearch(debouncedQuery, sourceFilter)}
          title="Refresh memories from backend"
          disabled={backendStatus === 'offline' || searching}
          className="opacity-30 hover:opacity-70 transition-opacity disabled:opacity-10"
        >
          <RefreshCw size={12} className={`text-gray-400 ${searching ? 'animate-spin' : ''}`} />
        </button>
        <button
          onClick={() => openSettings()}
          title="Open full dashboard"
          className="opacity-30 hover:opacity-70 transition-opacity"
        >
          <ExternalLink size={12} className="text-gray-400" />
        </button>
      </div>
    </div>
  );

  // ── Detail view ────────────────────────────────────────────────────────────

  if (selectedRecord) {
    return (
      <div className="flex flex-col h-full" style={{ background: '#0a0a0f' }}>
        <Header />
        <div className="flex-1 min-h-0 overflow-hidden">
          <MemoryDetailView
            record={selectedRecord}
            onBack={() => setSelectedRecord(null)}
            onInject={handleInject}
            onCopy={handleCopy}
            onDelete={handleDelete}
            injecting={injectingId === selectedRecord.id}
            showToast={showToast}
          />
        </div>
        {toast && <Toast toast={toast} onDone={() => setToast(null)} />}
      </div>
    );
  }

  // ── List / Ask views ──────────────────────────────────────────────────────

  const filtered = sourceFilter === 'all'
    ? records
    : records.filter(r => r.sourceApp === sourceFilter);

  return (
    <div className="flex flex-col h-full" style={{ background: '#0a0a0f' }}>
      <style>{`
        @keyframes shailFadeUp {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      <Header />

      {/* Mode tabs */}
      <div
        className="flex-shrink-0 flex gap-1 px-3 py-2"
        style={{ borderBottom: '1px solid #1e1e2e' }}
      >
        {(['browse', 'ask'] as const).map(mode => {
          const isActive = panelMode === mode;
          return (
            <button
              key={mode}
              onClick={() => setPanelMode(mode)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-all"
              style={{
                background: isActive ? 'rgba(59,130,246,0.12)' : 'transparent',
                color: isActive ? '#60a5fa' : '#4b5563',
                border: `1px solid ${isActive ? 'rgba(59,130,246,0.2)' : 'transparent'}`,
              }}
            >
              {mode === 'browse' ? <Search size={11} /> : <Sparkles size={11} />}
              {mode === 'browse' ? 'Browse' : 'Ask'}
            </button>
          );
        })}
      </div>

      {/* ── Ask mode ────────────────────────────────────────────────────────── */}
      {panelMode === 'ask' && (
        <div className="flex-1 min-h-0 overflow-hidden">
          <AskPanel
            view={view}
            onOpenRecord={r => setSelectedRecord(r)}
            onInject={handleInject}
            onCopy={handleCopy}
            onPin={handlePin}
            onDelete={handleDelete}
            injectingId={injectingId}
            showToast={showToast}
          />
        </div>
      )}

      {/* ── Browse mode ─────────────────────────────────────────────────────── */}
      {panelMode === 'browse' && <>

      {/* Search + filters */}
      {(view === 'ready' || view === 'loading') && (
        <div
          className="flex-shrink-0 px-3 pt-3 pb-2 space-y-2"
          style={{ borderBottom: '1px solid #1e1e2e' }}
        >
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-xl"
            style={{
              background: '#13131a',
              border: `1px solid ${query ? '#2d2d4e' : '#1e1e2e'}`,
              transition: 'border-color 0.15s',
            }}
          >
            <Search size={13} style={{ color: query ? '#6b7280' : '#374151', flexShrink: 0 }} />
            <input
              ref={searchRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  doSearch(query, sourceFilter);
                }
              }}
              disabled={backendStatus === 'offline'}
              placeholder={
                backendStatus === 'offline'
                  ? 'Start SHAIL to search…'
                  : 'Search memories… (Enter to search)'
              }
              style={{ color: '#e5e7eb', cursor: backendStatus === 'offline' ? 'not-allowed' : undefined }}
              className="flex-1 bg-transparent text-xs placeholder-gray-600 outline-none min-w-0 disabled:opacity-50"
            />
            {query && (
              <button onClick={() => setQuery('')} className="opacity-50 hover:opacity-100 flex-shrink-0">
                <X size={11} style={{ color: '#6b7280' }} />
              </button>
            )}
          </div>
          <FilterPills active={sourceFilter} onChange={setSourceFilter} />
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto min-h-0">

        {view === 'loading' && (
          <div className="p-3 space-y-2">
            {[...Array(5)].map((_, i) => <CardSkeleton key={i} />)}
          </div>
        )}

        {/* Offline banner (shown when backend is offline, above cards in browse) */}
        {backendStatus === 'offline' && view !== 'error' && (
          <div
            className="mx-3 mt-3 flex items-start gap-2 rounded-xl px-3 py-2.5"
            style={{
              background: 'rgba(239,68,68,0.06)',
              border: '1px solid rgba(239,68,68,0.15)',
            }}
          >
            <AlertCircle size={13} className="flex-shrink-0 mt-0.5" style={{ color: '#f87171' }} />
            <div className="flex-1 min-w-0">
              <div className="text-[11px] font-semibold" style={{ color: '#f87171' }}>
                SHAIL is offline
              </div>
              <div className="text-[10px] mt-0.5" style={{ color: '#9ca3af' }}>
                Browse shows cached memories. Search unavailable.
              </div>
            </div>
            <button
              onClick={() => {
                setBackendStatus('checking');
                fetch('http://localhost:8000/browser/me', { signal: AbortSignal.timeout(2000) })
                  .then(r => setBackendStatus(r.ok ? 'online' : 'offline'))
                  .catch(() => setBackendStatus('offline'));
              }}
              className="flex-shrink-0 text-[10px] px-2 py-1 rounded-lg transition-colors"
              style={{
                background: 'rgba(239,68,68,0.1)',
                border: '1px solid rgba(239,68,68,0.2)',
                color: '#f87171',
              }}
            >
              Retry
            </button>
          </div>
        )}

        {view === 'error' && (
          <div className="flex flex-col items-center justify-center py-12 px-6 text-center gap-3">
            <AlertCircle size={20} className="opacity-40" style={{ color: '#f87171' }} />
            <div className="text-xs text-white opacity-40 font-medium">Search unavailable</div>
            {lastSearchError && (
              <div
                className="text-[10px] rounded-lg px-3 py-2 text-left w-full"
                style={{
                  background: 'rgba(239,68,68,0.06)',
                  border: '1px solid rgba(239,68,68,0.15)',
                  color: '#9ca3af',
                  wordBreak: 'break-all',
                }}
              >
                {lastSearchError.length > 160 ? lastSearchError.slice(0, 157) + '…' : lastSearchError}
              </div>
            )}
            <div className="text-[11px] leading-relaxed" style={{ color: '#374151' }}>
              Start the SHAIL backend app, then retry.
            </div>
            <button
              onClick={() => doSearch(debouncedQuery, sourceFilter)}
              className="text-[11px] text-blue-400 underline opacity-60 hover:opacity-100"
            >
              Retry
            </button>
          </div>
        )}

        {view === 'ready' && (
          <div className="p-3 space-y-2">
            {filtered.length === 0 ? (
              <EmptyState query={query} />
            ) : (
              <>
                <div className="text-[9px] uppercase tracking-widest px-0.5 mb-1" style={{ color: '#374151' }}>
                  {filtered.length} {filtered.length === 1 ? 'memory' : 'memories'}
                  {query ? ' · sorted by relevance' : ' · newest first'}
                </div>

                {filtered.map((record, idx) => (
                  <MemoryCardFixed
                    key={record.id}
                    record={record}
                    index={idx}
                    injecting={injectingId === record.id}
                    onOpen={r => setSelectedRecord(r)}
                    onInject={r => handleInject(r)}
                    onCopy={r => handleCopy(r)}
                    onPin={r => handlePin(r)}
                    onDelete={r => handleDelete(r)}
                  />
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div
        className="flex-shrink-0 flex items-center justify-center px-4 py-2"
        style={{ borderTop: '1px solid #1e1e2e' }}
      >
        <button
          onClick={() => openSettings()}
          className="flex items-center gap-1 text-[10px] opacity-30 hover:opacity-70 transition-opacity"
          style={{ color: '#6b7280' }}
        >
          Open full dashboard <ExternalLink size={10} />
        </button>
      </div>

      </>} {/* end panelMode === 'browse' */}

      {toast && <Toast toast={toast} onDone={() => setToast(null)} />}
    </div>
  );
}

// ─── Mount ────────────────────────────────────────────────────────────────────

ReactDOM.createRoot(document.getElementById('app')!).render(
  <React.StrictMode>
    <Sidepanel />
  </React.StrictMode>
);
