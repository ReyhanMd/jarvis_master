import React from 'react';

export type Action = {
  label: string;
  onClick: () => void;
  variant?: 'primary' | 'secondary' | 'destructive';
  icon?: React.ReactNode;
  disabled?: boolean;
  title?: string;
};

const VARIANT_STYLE: Record<NonNullable<Action['variant']>, React.CSSProperties> = {
  primary:     { background: '#1f3a52', color: '#cfe4ff', border: '1px solid #2a4d6a' },
  secondary:   { background: '#1a1a1a', color: '#d0d0d0', border: '1px solid #2a2a2a' },
  destructive: { background: '#2a1212', color: '#e0a0a0', border: '1px solid #3a1a1a' },
};

export function ActionBar({ actions, dense = false }: { actions: Action[]; dense?: boolean }) {
  return (
    <div style={{ display: 'flex', gap: dense ? 6 : 8, flexWrap: 'wrap' }}>
      {actions.map((a, i) => {
        const v = a.variant ?? 'secondary';
        return (
          <button
            key={i}
            onClick={a.onClick}
            disabled={a.disabled}
            title={a.title ?? a.label}
            style={{
              ...VARIANT_STYLE[v],
              padding: dense ? '4px 8px' : '6px 12px',
              fontSize: dense ? 11 : 12,
              fontWeight: 500,
              borderRadius: 5,
              cursor: a.disabled ? 'not-allowed' : 'pointer',
              opacity: a.disabled ? 0.45 : 1,
              display: 'inline-flex', alignItems: 'center', gap: 6,
            }}
          >
            {a.icon}
            {a.label}
          </button>
        );
      })}
    </div>
  );
}
