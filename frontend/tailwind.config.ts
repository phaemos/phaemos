import type { Config } from 'tailwindcss';
import typography from '@tailwindcss/typography';

const config: Config = {
  darkMode: 'class',
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand:    { 500:'#6366f1', 600:'#4f46e5', 700:'#4338ca' },
        primary:  { 50:'#f0f9ff', 100:'#e0f2fe', 500:'#0ea5e9', 600:'#0284c7', 700:'#0369a1' },
        success:  { 50:'#f0fdf4', 500:'#22c55e', 600:'#16a34a' },
        warning:  { 50:'#fff7ed', 500:'#f97316', 600:'#ea580c' },
        critical: { 50:'#fef2f2', 500:'#ef4444', 600:'#dc2626' },
        surface:  { 0:'#ffffff', 50:'#f8fafc', 100:'#f1f5f9', 200:'#e2e8f0', 400:'#94a3b8', 600:'#475569', 800:'#1e293b', 900:'#0f172a', 950:'#020617' },
      },
      fontFamily: {
        sans: ['var(--font-geist-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-geist-mono)', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [typography],
};

export default config;
