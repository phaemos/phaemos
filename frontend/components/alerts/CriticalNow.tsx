'use client';

import { useApiResource } from '@/hooks/useApiResource';
import Button from '@/components/ui/Button';
import { StatusShape } from '@/components/ui/StatusBadge';
import { plural } from '@/lib/format';
import type { Alert } from '@/types';

interface Props {
  // the filters now applied, so the button can say what pressing it does
  severity: 'all' | 'critical' | 'warning' | 'info';
  state: 'active' | 'resolved';
  onChoose: (severity: 'all' | 'critical') => void;
}

// the first question at the alerts page is "what is critical right now". This answers it before any filter is touched: how many open
// alerts are critical, from the server's own count, with a shape and words and never colour alone. The button applies the critical filter
// or clears it when it is already applied. It counts every open critical alert, whatever the other filters say.
export default function CriticalNow({ severity, state, onChoose }: Props) {
  const res = useApiResource<Alert[]>('/alerts', { params: { resolved: false, severity: 'critical', limit: 1 }, what: 'The critical alerts', intervalMs: 10_000 });
  const count = res.total ?? (res.data ? res.data.length : null);
  const showing = severity === 'critical' && state === 'active';

  if (res.error && count === null) {
    return <p className="text-base text-surface-800 dark:text-surface-200">The number of critical alerts could not be read. {res.error}</p>;
  }
  if (count === null) {
    return <p className="min-h-[44px] text-base text-surface-700 dark:text-surface-300" role="status">Counting the critical alerts</p>;
  }
  const none = count === 0;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <p role="status" className="flex items-center gap-2 text-base font-medium text-surface-900 dark:text-surface-50">
        <span className={none ? 'text-success-800 dark:text-success-400' : 'text-critical-800 dark:text-critical-300'}><StatusShape shape={none ? 'circle' : 'diamond'} /></span>
        {none ? 'No critical alerts are open' : `${plural(count, 'critical alert')} open now`}
      </p>
      {!none && (
        <Button variant="secondary" onClick={() => onChoose(showing ? 'all' : 'critical')}>
          {showing ? 'Show every severity' : 'Show only critical'}
        </Button>
      )}
    </div>
  );
}
