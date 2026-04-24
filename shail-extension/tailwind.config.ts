import type { Config } from 'tailwindcss';

export default {
  content: [
    './entrypoints/**/*.{ts,tsx,html}',
    './components/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        shail: {
          bg: '#0a0a0f',
          surface: '#13131a',
          border: '#1e1e2e',
          accent: '#3b82f6',
          green: '#22c55e',
          muted: '#6b7280',
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
