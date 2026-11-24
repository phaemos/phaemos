import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { statusInfo, type Tone } from '@/lib/status';
import { StatusShape } from './StatusBadge';
import { TONE_TEXT } from './tone';

// the shape each tone carries when `shape` is set, read from the same map as StatusBadge
const SHAPE_FOR_TONE = { neutral: 'ring', info: 'square', success: 'circle', warning: 'triangle', critical: 'diamond' } as const;

interface Props {
  tone?: Tone;
  // add the shape for the tone before the text
  shape?: boolean;
  // or take tone and shape from a status key in lib/status.ts and show its word unless children are given
  status?: string;
  children?: ReactNode;
  className?: string;
}

// a plain label with a hairline border for a category or a count of words, such as a role or a rule type;
// it is not a pill and not interactive, so it needs no 44 px target.
export default function Badge({ tone = 'neutral', shape = false, status, children, className }: Props) {
  const info = status ? statusInfo(status) : null;
  const t = info ? info.tone : tone;
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded border border-surface-300 px-1.5 py-0.5 text-meta font-medium dark:border-surface-700', TONE_TEXT[t], className)}>
      {(shape || info) && <StatusShape shape={info ? info.shape : SHAPE_FOR_TONE[t]} />}
      {children ?? info?.word}
    </span>
  );
}
