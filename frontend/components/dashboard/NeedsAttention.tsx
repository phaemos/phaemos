'use client';

import Link from 'next/link';
import Panel from '@/components/ui/Panel';
import AlertRow from '@/components/alerts/AlertRow';
import { plural } from '@/lib/format';
import type { Alert } from '@/types';

const LINK = 'inline-flex min-h-[44px] items-center text-sm font-medium text-brand-800 underline-offset-2 hover:underline dark:text-brand-400';

// the same look without the hover change, for the illustration where nothing is clickable
const STATIC_LINK = LINK.replace(' hover:underline', '') + ' cursor-default';

interface Props {
  // the active alerts, critical first and then the most recently seen. Each is one long-lived alert, so a row is never one reading.
  alerts: Alert[];
  // machine names by device id
  deviceNames?: Record<string, string>;
  // how many alerts to show before the link to every alert
  limit?: number;
  // total active alerts, for the header
  alertCount: number;
  // how many of them the page holds, when the API has more than it sent
  loadedCount?: number;
  // false renders every control as plain text so the panel can sit on the public page as an illustration
  interactive?: boolean;
  // a fixed clock for sample data
  now?: number;
}

// the active alerts that need a person, most urgent first
export default function NeedsAttention({ alerts, deviceNames, limit = 5, alertCount, loadedCount, interactive = true, now }: Props) {
  if (alerts.length === 0) return null;
  const shown = alerts.slice(0, limit);
  const more = alerts.length - shown.length;
  const moreText = more > 0 ? `${more} more ${more === 1 ? 'alert' : 'alerts'}: view all alerts` : 'View all alerts';

  return (
    <Panel
      title="Needs attention"
      description={loadedCount !== undefined && loadedCount < alertCount ? `Showing the newest ${loadedCount} of ${alertCount} active alerts` : plural(alertCount, 'active alert')}
      bodyClassName="p-0"
    >
      <ul className="divide-y divide-surface-200 dark:divide-surface-800">
        {shown.map((a) => (
          <AlertRow key={a.id} alert={a} name={deviceNames?.[a.device_id] ?? 'Unknown machine'} canAct={interactive} interactive={interactive} now={now} />
        ))}
      </ul>
      <div className="border-t border-surface-200 px-4 dark:border-surface-800">
        {interactive ? <Link href="/alerts" className={LINK}>{moreText}</Link> : <span className={STATIC_LINK}>{moreText}</span>}
      </div>
    </Panel>
  );
}
