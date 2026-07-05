import React from 'react';

function tier(c: number): { label: string; fg: string; bg: string } {
  if (c >= 0.8) return { label: 'high',    fg: '#7aa6e0', bg: '#0e1a2a' };
  if (c >= 0.5) return { label: 'medium',  fg: '#a89ad4', bg: '#1a1626' };
  if (c >= 0.2) return { label: 'low',     fg: '#d2a05f', bg: '#2a1f0e' };
  return            { label: 'unknown', fg: '#888',    bg: '#1a1a1a' };
}

export function ConfidenceBadge({ value, showBar = false }: { value: number; showBar?: boolean }) {
  const t = tier(value);
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <span
      title={`Confidence: ${pct}%`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        background: t.bg, color: t.fg,
        padding: '3px 8px', fontSize: 11, fontWeight: 500,
        borderRadius: 4,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: t.fg }} />
      {t.label}
      {showBar && (
        <span style={{ width: 28, height: 3, background: '#2a2a2a', borderRadius: 2, overflow: 'hidden' }}>
          <span style={{ display: 'block', width: `${pct}%`, height: '100%', background: t.fg }} />
        </span>
      )}
    </span>
  );
}
