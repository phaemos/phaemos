'use client';

import { useState } from 'react';
import Button from './Button';
import { CheckIcon, CopyIcon } from './icons';

// an id on one line in mono with a Copy button. In a narrow column it is cut in the middle, so the start and the end
// stay readable. The full value is always in the title and is what Copy puts on the clipboard.
export default function CopyValue({ value, what = 'value', tail = 6 }: { value: string; what?: string; tail?: number }) {
  const [copied, setCopied] = useState(false);
  const head = value.length > tail * 2 ? value.slice(0, -tail) : value;
  const end = value.length > tail * 2 ? value.slice(-tail) : '';

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // the clipboard can be blocked, so the visible id stays selectable as the fallback
    }
  }

  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="num flex min-w-0 text-meta text-surface-900 dark:text-surface-50" title={value}>
        <span className="truncate">{head}</span>
        <span className="shrink-0">{end}</span>
      </span>
      <Button variant="ghost" size="small" onClick={copy} aria-label={copied ? `Copied ${what}` : `Copy ${what}`} icon={copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}>
        {copied ? 'Copied' : 'Copy'}
      </Button>
      <span role="status" className="sr-only">{copied ? 'Copied to the clipboard' : ''}</span>
    </span>
  );
}
