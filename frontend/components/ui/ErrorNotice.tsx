'use client';

import { cn } from '@/lib/cn';
import Button from './Button';
import RequestRef from './RequestRef';
import { StatusShape } from './StatusBadge';

interface Props {
  // what failed, in words a user can act on: "The machines did not load."
  message: string;
  // one more line when the first does not say what to do
  detail?: string;
  // shows a "Try again" button that calls this. Leave it out when retrying cannot help.
  onRetry?: () => void;
  retryLabel?: string;
  pending?: boolean;
  // the request_id of the failed request, in small text so it can be quoted
  requestId?: string | null;
  className?: string;
}

// the one surface for a failed request. Use it in place of an empty state, because "no machines" and "the request
// failed" are different facts. It is announced to screen readers as soon as it appears.
export default function ErrorNotice({ message, detail, onRetry, retryLabel = 'Try again', pending, requestId, className }: Props) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-wrap items-center justify-between gap-3 rounded-lg border border-critical-700 px-4 py-3 text-base text-surface-900 dark:border-critical-400 dark:text-surface-50',
        className,
      )}
    >
      <div className="flex min-w-0 items-start gap-2">
        <span className="mt-1.5 text-critical-800 dark:text-critical-300"><StatusShape shape="diamond" /></span>
        <div>
          <p className="font-medium">{message}</p>
          {detail && <p className="mt-0.5 text-surface-600 dark:text-surface-400">{detail}</p>}
          <RequestRef id={requestId} />
        </div>
      </div>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry} pending={pending}>
          {retryLabel}
        </Button>
      )}
    </div>
  );
}
