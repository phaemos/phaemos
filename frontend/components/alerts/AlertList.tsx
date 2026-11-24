'use client';

import type { Alert } from '@/types';
import Panel from '@/components/ui/Panel';
import AlertRow from './AlertRow';

interface Props {
  alerts: Alert[];
  deviceNames: Record<string, string>;
  canAct: boolean;
  pendingIds: ReadonlySet<string>;
  onResolve: (alert: Alert) => void;
  title: string;
  description: string;
}

// one row for each alert, in the order the page chose. An alert lasts as long as its condition, so a row stands for the whole of it and
// never for one reading.
export default function AlertList({ alerts, deviceNames, canAct, pendingIds, onResolve, title, description }: Props) {
  return (
    <Panel title={title} description={description} bodyClassName="p-0">
      <ul className="divide-y divide-surface-200 dark:divide-surface-800">
        {alerts.map((a) => (
          <AlertRow key={a.id} alert={a} name={deviceNames[a.device_id] ?? 'Unknown machine'} canAct={canAct} pending={pendingIds.has(a.id)} onResolve={onResolve} />
        ))}
      </ul>
    </Panel>
  );
}
