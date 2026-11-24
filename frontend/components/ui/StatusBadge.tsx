// a small shape and a word on a plain background. The shape, word and tone come from lib/status.ts, so a machine
// status, an alert severity and a ticket state all read the same way everywhere. Colour is never the only signal.
import { statusInfo, type ShapeName, type StatusKey } from '@/lib/status';
import { cn } from '@/lib/cn';
import { TONE_TEXT } from './tone';

export type Status = StatusKey;

interface Props {
  // any key from lib/status.ts. An unknown value reads "Unknown".
  status: Status | (string & {});
  // replace the word, for example "Degraded" for a fleet figure
  label?: string;
  className?: string;
}

export function StatusShape({ shape, className = '' }: { shape: ShapeName; className?: string }) {
  const common = { width: 10, height: 10, viewBox: '0 0 10 10', 'aria-hidden': true, focusable: false, className: `shrink-0 ${className}` } as const;
  switch (shape) {
    case 'circle':
      return <svg {...common}><circle cx="5" cy="5" r="4" fill="currentColor" /></svg>;
    case 'ring':
      return <svg {...common}><circle cx="5" cy="5" r="3.25" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>;
    case 'triangle':
      return <svg {...common}><path d="M5 .75 9.5 9H.5Z" fill="currentColor" /></svg>;
    case 'diamond':
      return <svg {...common}><path d="M5 .5 9.5 5 5 9.5.5 5Z" fill="currentColor" /></svg>;
    default:
      return <svg {...common}><rect x="1.5" y="1.5" width="7" height="7" rx="1" fill="currentColor" /></svg>;
  }
}

// the shape, the tone classes and the word for a status, for components that lay the parts out themselves
export function statusShape(status: string): { shape: ShapeName; tone: string; label: string } {
  const info = statusInfo(status);
  return { shape: info.shape, tone: TONE_TEXT[info.tone], label: info.word };
}

export default function StatusBadge({ status, label, className }: Props) {
  const info = statusInfo(status);
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-meta font-medium', TONE_TEXT[info.tone], className)}>
      <StatusShape shape={info.shape} />
      <span className="text-surface-800 dark:text-surface-200">{label ?? info.word}</span>
    </span>
  );
}
