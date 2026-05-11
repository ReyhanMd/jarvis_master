/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Legacy (kept for backward compatibility — do not remove)
        'shail-blue': '#00D4FF',
        'shail-dark': '#0A0E27',
        'shail-darker': '#050815',

        // v2 palette — manifesto §Visual style
        // Layered depth: charcoal base, progressively lighter surfaces.
        'bg-base':    'var(--shail-bg-base)',
        'bg-surface': 'var(--shail-bg-surface)',
        'bg-raised':  'var(--shail-bg-raised)',
        'bg-overlay': 'var(--shail-bg-overlay)',
        'border-subtle': 'var(--shail-border-subtle)',
        'border-strong': 'var(--shail-border-strong)',
        'text-primary':   'var(--shail-text-primary)',
        'text-secondary': 'var(--shail-text-secondary)',
        'text-muted':     'var(--shail-text-muted)',
        // Semantic
        'accent':         'var(--shail-accent)',
        'accent-soft':    'var(--shail-accent-soft)',
        'evidence':       'var(--shail-evidence)',
        'evidence-soft':  'var(--shail-evidence-soft)',
        'success':        'var(--shail-success)',
        'warning':        'var(--shail-warning)',
        'danger':         'var(--shail-danger)',
      },
      backdropBlur: {
        'glass': '20px',
      },
    },
  },
  plugins: [],
}
