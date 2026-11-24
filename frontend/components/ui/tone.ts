// the text colour for each tone: the 700 shade on light and the 400 shade on dark, 4.5:1 or better on the page and
// panel backgrounds. It lives here and not in lib/ because Tailwind only scans app/ and components/.
import type { Tone } from '@/lib/status';

export const TONE_TEXT: Record<Tone, string> = {
  success: 'text-success-800 dark:text-success-400',
  warning: 'text-warning-800 dark:text-warning-400',
  critical: 'text-critical-800 dark:text-critical-300',
  info: 'text-brand-800 dark:text-brand-400',
  neutral: 'text-surface-600 dark:text-surface-400',
};
