import type { SourceApp } from '../types/contracts';

// ─── Relative timestamps ──────────────────────────────────────────────────────

export function timeAgo(isoString: string): string {
  const seconds = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days}d ago`;
  return new Date(isoString).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// ─── Source app metadata ──────────────────────────────────────────────────────

export const SOURCE_META: Record<SourceApp, { label: string; color: string; bg: string }> = {
  chatgpt:    { label: 'ChatGPT',    color: '#10a37f', bg: 'rgba(16,163,127,0.12)' },
  claude:     { label: 'Claude',     color: '#cc785c', bg: 'rgba(204,120,92,0.12)' },
  gemini:     { label: 'Gemini',     color: '#4285f4', bg: 'rgba(66,133,244,0.12)' },
  perplexity: { label: 'Perplexity', color: '#20b2aa', bg: 'rgba(32,178,170,0.12)' },
  web:        { label: 'Web',        color: '#6b7280', bg: 'rgba(107,114,128,0.12)' },
};

export function getSourceMeta(app: SourceApp) {
  return SOURCE_META[app] ?? SOURCE_META.web;
}

// ─── Source initials (used as icon fallback) ──────────────────────────────────

export function sourceInitial(app: SourceApp): string {
  return getSourceMeta(app).label[0].toUpperCase();
}
