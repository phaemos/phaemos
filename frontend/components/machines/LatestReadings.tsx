'use client';

import { useEffect, useState } from 'react';
import type { Device, Telemetry } from '@/types';
import DataTable from '@/components/ui/DataTable';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import Panel from '@/components/ui/Panel';
import { SkeletonRows } from '@/components/ui/Skeleton';
import StatusBadge from '@/components/ui/StatusBadge';
import { formatReadingValue, groupReadings, isRaised } from '@/lib/readingGroups';
import { faultedFieldsNow } from '@/lib/machineState';
import Time from '@/components/ui/Time';
import { serverNow } from '@/lib/serverClock';

interface Props {
  // the machine, for its node type and the sensors reported as faulted or marked as not fitted
  device: Pick<Device, 'id' | 'type' | 'health' | 'not_fitted' | 'expected_interval_s'>;
  // the machine's newest readings, loaded once by the page. A hub forwards the other nodes' fields in separate readings,
  // so the single newest reading does not hold every field the machine reports and the table searches the recent ones.
  readings: { data: Telemetry[] | null; error: string | null; loading: boolean; retry: () => void };
}

// the newest value of every sensor the machine carries, as one table grouped by sensor. A faulted sensor shows "No reading"
// with its reason and a sensor marked as not fitted shows "Not fitted", never an older value that would look current. A
// machine that has never posted shows one empty state and not a table of "no reading".
export default function LatestReadings({ device, readings }: Props) {
  const { data, error, loading, retry } = readings;
  const faulted = faultedFieldsNow(device, data?.[0] ?? null);
  // a value counts as a reading only while it is no older than three expected intervals, the same rule the charts and the cards use
  const [now, setNow] = useState(() => serverNow());
  useEffect(() => {
    const id = setInterval(() => setNow(serverNow()), 5000);
    return () => clearInterval(id);
  }, []);
  const limitMs = 3 * Math.max(5, device.expected_interval_s ?? 5) * 1000;
  const groups = data && data.length > 0 ? groupReadings(data, device.type, (field) => faulted.has(field)) : [];

  return (
    <Panel title="Latest readings" description="The newest value from each sensor, refreshed every 5 seconds." bodyClassName="">
      {loading ? (
        <div className="p-4"><SkeletonRows rows={6} label="Loading the latest readings" /></div>
      ) : !data ? (
        <div className="p-4"><ErrorNotice message={error ?? 'The latest readings did not load.'} onRetry={retry} /></div>
      ) : groups.length === 0 ? (
        <EmptyState heading="No readings yet" subMessage="The node has not posted a reading. Check that it is powered and that it sends this machine's API key." />
      ) : (
        <>
          {error && <div className="p-4"><ErrorNotice message="The readings could not be refreshed. These values may be out of date." onRetry={retry} /></div>}
          <DataTable caption="Latest reading of each sensor on this machine">
            <thead>
              <tr>
                <th scope="col">Sensor</th>
                <th scope="col">Reading</th>
                <th scope="col" className="text-right">Value</th>
                <th scope="col">When</th>
              </tr>
            </thead>
            {groups.map((g) => (
              <tbody key={g.id}>
                {g.rows.map((r, i) => {
                  // a raised flag never goes stale into "no reading": its age is shown beside it instead
                  const stale = r.at !== null && now - Date.parse(r.at) > limitMs && !(r.kind === 'flag' && r.value === true);
                  const text = stale ? null : formatReadingValue(r);
                  const fault = faulted.get(r.key);
                  return (
                    <tr key={r.key}>
                      {i === 0 && (
                        <th scope="rowgroup" rowSpan={g.rows.length} className="border-b border-surface-200 text-left align-top font-medium text-surface-900 dark:border-surface-800 dark:text-surface-50">
                          {g.name}
                          <span className="block text-meta font-normal text-surface-600 dark:text-surface-400">{g.model}</span>
                        </th>
                      )}
                      <th scope="row">{r.label}</th>
                      <td className="num">
                        {fault ? (
                          <span className="font-sans text-surface-900 dark:text-surface-50">
                            {fault.state === 'not_fitted' ? 'Not fitted' : fault.state === 'warming_up' ? 'Warming up' : `No reading: ${fault.name} ${fault.words}`}
                          </span>
                        ) : text === null ? (
                          <span className="font-sans text-surface-800 dark:text-surface-200">No reading</span>
                        ) : isRaised(r) ? (
                          <StatusBadge status="critical" label={text} />
                        ) : (
                          text
                        )}
                      </td>
                      <td className="whitespace-nowrap text-surface-600 dark:text-surface-400">
                        {fault ? (fault.state === 'not_fitted' ? 'Marked by an admin' : 'Not trusted') : r.at ? (stale ? <>Last value <Time value={r.at} format="relative" /></> : <Time value={r.at} format="relative" />) : 'Never'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            ))}
          </DataTable>
        </>
      )}
    </Panel>
  );
}
