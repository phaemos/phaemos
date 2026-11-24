'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import DataTable from '@/components/ui/DataTable';
import ErrorNotice from '@/components/ui/ErrorNotice';
import StatusBadge, { StatusShape } from '@/components/ui/StatusBadge';
import { formatDateTime } from '@/lib/format';
import { statusInfo } from '@/lib/status';
import { CHECK_INTERVAL_MS, CHECK_TIMEOUT_MS, PARTS, failingParts, parseStatus, type StatusReport } from '@/lib/siteStatus';
import Time from '@/components/ui/Time';

type State = { phase: 'checking' } | { phase: 'done'; report: StatusReport } | { phase: 'unreachable' };

// asks the API's public /status route from the visitor's browser. A check that fails or takes longer than the
// timeout ends in a plain "could not reach" state with a retry. It never stays on "checking".
export default function StatusCheck() {
  const [state, setState] = useState<State>({ phase: 'checking' });
  const [retrying, setRetrying] = useState(false);
  const alive = useRef(true);

  const check = useCallback(async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), CHECK_TIMEOUT_MS);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/status`, { cache: 'no-store', signal: controller.signal });
      if (!res.ok) throw new Error('not ok');
      const report = parseStatus(await res.json());
      if (!report) throw new Error('unexpected reply');
      if (alive.current) setState({ phase: 'done', report });
    } catch {
      if (alive.current) setState({ phase: 'unreachable' });
    } finally {
      clearTimeout(timer);
      if (alive.current) setRetrying(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    // the first check runs on mount and then every 30 seconds, so the page stays current without a reload
    // eslint-disable-next-line react-hooks/set-state-in-effect
    check();
    const id = setInterval(check, CHECK_INTERVAL_MS);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [check]);

  const retry = () => {
    setRetrying(true);
    setState({ phase: 'checking' });
    check();
  };

  const report = state.phase === 'done' ? state.report : null;
  const failing = report ? failingParts(report) : [];

  let summary: string;
  let shape = statusInfo('unknown').shape;
  if (state.phase === 'checking') {
    summary = 'Checking';
  } else if (!report) {
    summary = 'We could not reach the API from your browser';
  } else if (failing.length === 0) {
    summary = 'Everything is running';
    shape = statusInfo('online').shape;
  } else {
    summary = `Something is down: ${failing.join(' and ')}`;
    shape = statusInfo('fault').shape;
  }

  return (
    <div className="max-w-3xl">
      <p role="status" className="flex items-center gap-2.5 text-xl font-semibold text-surface-900 dark:text-surface-50">
        <StatusShape shape={shape} />
        {summary}
      </p>
      {report && (
        <p className="mt-1 text-base text-surface-600 dark:text-surface-400">
          Last checked <Time value={report.updatedAt} />
        </p>
      )}

      {state.phase === 'unreachable' && (
        <ErrorNotice
          className="mt-4"
          message="The check did not get an answer."
          detail="This page asks the API from your browser. The API may be down or your connection may be blocking it."
          onRetry={retry}
          retryLabel="Check again"
          pending={retrying}
        />
      )}

      <DataTable caption="Parts of the service and whether each answers" maxHeightClass="max-h-none" framed className="mt-6">
        <thead>
          <tr>
            <th scope="col">Part</th>
            <th scope="col">What we check</th>
            <th scope="col">Result</th>
          </tr>
        </thead>
        <tbody>
          {PARTS.map(({ key, label, what }) => (
            <tr key={key}>
              <th scope="row">{label}</th>
              <td>{what}</td>
              <td>
                {report ? (
                  <StatusBadge status={report[key] === 'ok' ? 'online' : 'fault'} label={report[key] === 'ok' ? 'Running' : 'Down'} />
                ) : (
                  <StatusBadge status="unknown" label={state.phase === 'checking' ? 'Checking' : 'Unknown'} />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  );
}
