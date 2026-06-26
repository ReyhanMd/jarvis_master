import React from 'react';

export type MemoryState =
  | 'captured'
  | 'partial'
  | 'queued'
  | 'replayable'
  | 'active'
  | 'historical'
  | 'failed'
  | 'synced'
  | 'local-only'
  | 'trusted'
  | 'incomplete';

const STYLES: Record<MemoryState, { bg: string; fg: string; label: string }> = {
  captured:    { bg: '#0e2a1a', fg: '#5fd29a', label: 'captured' },
  partial:     { bg: '#2a230e', fg: '#e0b65a', label: 'partial' },
  queued:      { bg: '#1a1a26', fg: '#8a8ad4', label: 'queued' },
  replayable:  { bg: '#0e1f2a', fg: '#5fb6d2', label: 'replayable' },
  active:      { bg: '#102a18', fg: '#67d18b', label: 'active' },
  historical:  { bg: '#1a1a1a', fg: '#888',    label: 'historical' },
  failed:      { bg: '#2a0e0e', fg: '#e07070', label: 'failed' },
  synced:      { bg: '#0e1a2a', fg: '#7aa6e0', label: 'synced' },
  'local-only':{ bg: '#1a1a1a', fg: '#9a9a9a', label: 'local' },
  trusted:     { bg: '#10221a', fg: '#62c898', label: 'trusted' },
  incomplete:  { bg: '#2a1a0e', fg: '#d2a05f', label: 'incomplete' },
};

export function StateBadge({ state, size = 'sm' }: { state: MemoryState; size?: 'xs' | 'sm' | 'md' }) {
  const s = STYLES[state];
  const padding = size === 'xs' ? '2px 6px' : size === 'md' ? '4px 10px' : '3px 8px';
  const fontSize = size === 'xs' ? 10 : size === 'md' ? 12 : 11;
  return (
    <span
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        background: s.bg, color: s.fg,
        padding, fontSize, fontWeight: 500,
        borderRadius: 4, letterSpacing: 0.2,
        textTransform: 'lowercase',
      }}
    >
      {s.label}
    </span>
  );
}
