import React from 'react';

type Props = {
  title: string;
  hint?: string;
  action?: { label: string; onClick: () => void };
  icon?: React.ReactNode;
};

export function EmptyState({ title, hint, action, icon }: Props) {
  return (
    <div
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        gap: 12, padding: '48px 24px', textAlign: 'center',
        color: '#9a9a9a',
      }}
    >
      {icon && <div style={{ opacity: 0.6 }}>{icon}</div>}
      <div style={{ color: '#e0e0e0', fontSize: 15, fontWeight: 500 }}>{title}</div>
      {hint && <div style={{ fontSize: 13, maxWidth: 420, lineHeight: 1.55 }}>{hint}</div>}
      {action && (
        <button
          onClick={action.onClick}
          style={{
            marginTop: 8, padding: '8px 16px', fontSize: 13,
            background: '#1a1a1a', color: '#e0e0e0',
            border: '1px solid #2a2a2a', borderRadius: 6,
            cursor: 'pointer',
          }}
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
