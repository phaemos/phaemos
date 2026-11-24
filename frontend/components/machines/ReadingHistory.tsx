'use client';

import { useKeysetList } from '@/hooks/useKeysetList';
import Button from '@/components/ui/Button';
import DataTable from '@/components/ui/DataTable';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import Panel from '@/components/ui/Panel';
import { SkeletonRows } from '@/components/ui/Skeleton';
import { StatusShape } from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';
import { isBacklog, lateWords } from '@/lib/backlog';
import { formatReading } from '@/lib/alertGroups';
import { metricUnit } from '@/lib/alertGroups';
import type { Telemetry } from '@/types';

const PAGE = 50;

// the columns: a few readings an operator scans the history for. Every reading is in the CSV export.
const COLUMNS = [
  { key: 'temperature', label: 'Temperature' },
  { key: 'vib_magnitude', label: 'Vibration' },
  { key: 'current_ma', label: 'Current' },
  { key: 'humidity', label: 'Humidity' },
] as const;

function cell(r: Telemetry, key: string): string {
  const v = (r as unknown as Record<string, unknown>)[key];
  if (typeof v !== 'number' || !Number.isFinite(v)) return '-';
  const unit = metricUnit(key);
  const n = formatReading(v);
  return unit ? (unit === '%' ? `${n}%` : `${n} ${unit}`) : n;
}

// the machine's readings, newest first, read by keyset paging: each older page is asked for with `before` until one comes back short, so
// a long history pages quickly and a reading arriving live cannot shift a page. The API sends no total for readings on purpose. A reading
// a gateway sent after an outage sits at the time it was taken and says in words that it arrived late and was never judged.
export default function ReadingHistory({ deviceId }: { deviceId: string }) {
  const list = useKeysetList<Telemetry>(`/telemetry/${deviceId}`, {
    pageSize: PAGE,
    cursorOf: (r) => `${r.recorded_at},${r.id}`,
    intervalMs: 15_000,
    what: 'The readings',
  });
  const hasData = list.updatedAt !== null;
  const late = list.items.filter((r) => isBacklog(r)).length;

  return (
    <Panel id="reading-history" title="Reading history" description="Every reading, newest first, at the time it was taken." bodyClassName="p-0">
      {list.error && !hasData ? (
        <div className="p-4"><ErrorNotice message={list.error} detail="No readings are shown because the history could not be loaded. This is not the same as no readings." requestId={list.errorRef} onRetry={list.retry} pending={list.loading} /></div>
      ) : !hasData ? (
        <div className="p-4"><SkeletonRows rows={5} label="Loading the reading history" /></div>
      ) : list.items.length === 0 ? (
        <EmptyState heading="No readings yet" subMessage="The node has not posted a reading." />
      ) : (
        <>
          {list.error && <div className="p-4"><ErrorNotice message={list.error} detail="Showing the readings already loaded." requestId={list.errorRef} onRetry={list.retry} pending={list.loading} /></div>}
          <DataTable caption="Readings, newest first, with when each was taken, whether it arrived late and its main values" minWidth="40rem">
            <thead>
              <tr>
                <th scope="col">Taken</th>
                <th scope="col">Arrival</th>
                {COLUMNS.map((c) => <th key={c.key} scope="col">{c.label}</th>)}
                <th scope="col">Anomaly score</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((r) => {
                const isLate = isBacklog(r);
                return (
                  <tr key={r.id}>
                    <td className="whitespace-nowrap"><Time value={r.recorded_at} format="exact" /></td>
                    <td className="min-w-[14rem]">
                      {isLate ? (
                        <span className="inline-flex items-start gap-2 text-sm text-surface-900 dark:text-surface-50">
                          <span className="mt-1 text-surface-800 dark:text-surface-200"><StatusShape shape="square" /></span>
                          <span><span className="font-medium">Arrived late.</span> {lateWords(r.recorded_at, r).replace(/^Arrived late[,.] ?/, '')}</span>
                        </span>
                      ) : (
                        <span className="text-surface-700 dark:text-surface-300">On time</span>
                      )}
                    </td>
                    {COLUMNS.map((c) => <td key={c.key} className="num whitespace-nowrap">{cell(r, c.key)}</td>)}
                    <td className="num">{typeof r.anomaly_score === 'number' ? r.anomaly_score.toFixed(2) : isLate ? 'Not scored' : '-'}</td>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-200 px-4 py-3 dark:border-surface-800">
            <p className="text-base text-surface-800 dark:text-surface-200">
              Showing <span className="tabular-nums">{list.items.length}</span> {list.items.length === 1 ? 'reading' : 'readings'}
              {late > 0 ? <>, <span className="tabular-nums">{late}</span> of them arrived late</> : null}.
              {list.hasMore ? '' : ' That is the whole history.'}
            </p>
            {list.hasMore && <Button variant="secondary" onClick={list.loadMore} pending={list.loadingMore}>Load older readings</Button>}
          </div>
        </>
      )}
    </Panel>
  );
}
