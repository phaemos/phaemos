import type { Config } from 'tailwindcss';
import typography from '@tailwindcss/typography';

const config: Config = {
  darkMode: 'class',
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // neutral near-black surfaces and one accent. Full scales: the components use most shades. A shade missing here renders with no colour at all.
      // brand is the royal blue of the PHAEMOS emblem.
      colors: {
        brand:    { 50:'#eff6ff', 100:'#dbeafe', 200:'#bfdbfe', 300:'#93c5fd', 400:'#60a5fa', 500:'#3b82f6', 600:'#2563eb', 700:'#1d4ed8', 800:'#1e40af', 900:'#1e3a8a', 950:'#172554' },
        success:  { 50:'#f0fdf4', 100:'#dcfce7', 200:'#bbf7d0', 300:'#86efac', 400:'#4ade80', 500:'#22c55e', 600:'#16a34a', 700:'#15803d', 800:'#166534', 900:'#14532d', 950:'#052e16' },
        warning:  { 50:'#fff7ed', 100:'#ffedd5', 200:'#fed7aa', 300:'#fdba74', 400:'#fb923c', 500:'#f97316', 600:'#ea580c', 700:'#c2410c', 800:'#9a3412', 900:'#7c2d12', 950:'#431407' },
        critical: { 50:'#fef2f2', 100:'#fee2e2', 200:'#fecaca', 300:'#fca5a5', 400:'#f87171', 500:'#ef4444', 600:'#dc2626', 700:'#b91c1c', 800:'#991b1b', 900:'#7f1d1d', 950:'#450a0a' },
        surface:  { 0:'#ffffff', 50:'#f7f8f9', 100:'#eff0f2', 200:'#e2e4e8', 300:'#c9ccd3', 400:'#a1a6b0', 500:'#7b818c', 600:'#4a505a', 700:'#353941', 800:'#22252b', 900:'#131519', 950:'#0b0c0e' },
      },
      // the type scale, in rem so browser zoom and the reader's own text size work. Nothing a person reads is under 13 px.
      // meta 13 (metadata, table headers), sm 14 (table cells, dense secondary text), base 16 (body, controls, labels),
      // lg 18, xl 20 (page title), 2xl 24, 3xl 28 (figures). xs is kept at 13 so a stray use still clears the floor.
      fontSize: {
        xs: ['0.8125rem', { lineHeight: '1.25rem' }],
        meta: ['0.8125rem', { lineHeight: '1.25rem' }],
        sm: ['0.875rem', { lineHeight: '1.375rem' }],
        base: ['1rem', { lineHeight: '1.5rem' }],
        lg: ['1.125rem', { lineHeight: '1.625rem' }],
        xl: ['1.25rem', { lineHeight: '1.75rem' }],
        '2xl': ['1.5rem', { lineHeight: '2rem' }],
        '3xl': ['1.75rem', { lineHeight: '2.25rem' }],
        '4xl': ['2.25rem', { lineHeight: '2.5rem' }],
        '5xl': ['3rem', { lineHeight: '1.1' }],
      },
      fontFamily: {
        display: ['var(--typeface-display)', 'var(--typeface-sans)', 'system-ui', 'sans-serif'],
        sans: ['var(--typeface-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--typeface-mono)', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [typography],
};

export default config;
