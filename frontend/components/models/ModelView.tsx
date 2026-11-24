'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import { requestIdOf } from '@/lib/apiCode';
import { useApiResource } from '@/hooks/useApiResource';
import { useRole } from '@/hooks/useRole';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import DataTable from '@/components/ui/DataTable';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import PageHeader from '@/components/ui/PageHeader';
import Panel from '@/components/ui/Panel';
import { SkeletonRows } from '@/components/ui/Skeleton';
import StatusBadge, { StatusShape } from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';
import ModelBadge from '@/components/machines/ModelBadge';
import { detectionWords, FALSE_ALERT_BUDGET, falseAlertRow, fileStateWords, modelName, nightlyWords, NO_ALERTS_WHILE_LEARNING, retrainCounts, retrainFinished, retrainHeadline, retrainRefusalWords, retrainStateBadge, rowsRefusedWords } from '@/lib/modelState';
import { formatCount, plural } from '@/lib/format';
import type { Device, MlRetrainModel, MlStatus } from '@/types';

const SLOW_MS = 30_000;
const FAST_MS = 4_000;
// a retrain that has not reported after this long is no longer waited for. The result is still read from the status route.
const GIVE_UP_MS = 10 * 60_000;

function hoursText(n: number | undefined): string {
  return typeof n === 'number' && Number.isFinite(n) ? `${Math.round(n * 10) / 10}` : 'not measured';
}

function detailOf(err: unknown): string | null {
  const d = (err as { response?: { data?: { detail?: unknown } } } | null)?.response?.data?.detail;
  return typeof d === 'string' && d.trim() ? d : null;
}

function ModelRows({ models }: { models: MlRetrainModel[] }) {
  return (
    <DataTable caption="Models in the last retrain, with their state, clean readings, false alerts per week and faults found" minWidth="48rem">
      <thead>
        <tr>
          <th scope="col">Model</th>
          <th scope="col">Result</th>
          <th scope="col">Clean hours</th>
          <th scope="col">Readings to fit and to measure</th>
          <th scope="col">False alerts a week</th>
          <th scope="col">Faults found</th>
        </tr>
      </thead>
      <tbody>
        {models.map((m) => {
          const badge = retrainStateBadge(m.state);
          const fa = falseAlertRow(m.false_alerts_per_week, m.budget_per_week);
          const det = m.detection && typeof m.detection.trials === 'number' && m.detection.trials > 0 ? `${m.detection.caught ?? 0} of ${m.detection.trials}` : 'Not measured';
          return (
            <tr key={m.key}>
              <th scope="row" className="text-left font-medium text-surface-900 dark:text-surface-50">{modelName(m)}</th>
              <td><StatusBadge status={badge.status} label={badge.label} /></td>
              <td className="tnum">{hoursText(m.clean_hours)}{typeof m.span_hours === 'number' ? ` of ${hoursText(m.span_hours)}` : ''}</td>
              <td className="tnum">{typeof m.rows_fit === 'number' ? formatCount(m.rows_fit) : 'None'} and {typeof m.rows_heldout === 'number' ? formatCount(m.rows_heldout) : 'none'}</td>
              <td>
                {fa.rate === null ? (
                  <span className="text-surface-700 dark:text-surface-300">Not measured</span>
                ) : (
                  <span className="inline-flex flex-wrap items-center gap-x-2">
                    <span className="tnum">{fa.rate === 0 ? '0' : fa.rate.toFixed(1)}</span>
                    <StatusBadge status={fa.over ? 'warning' : 'healthy'} label={fa.over ? `Over the budget of ${fa.budget}` : `Within the budget of ${fa.budget}`} />
                  </span>
                )}
              </td>
              <td className="tnum">{det}</td>
            </tr>
          );
        })}
      </tbody>
    </DataTable>
  );
}

// the anomaly model: what is in service, what the last retrain did and why and when the next one runs. The refusals are quoted exactly
// as the API wrote them, because each says what to do. A machine in learning raises no anomaly alerts, which this page says first.
export default function ModelView() {
  const role = useRole();
  const isAdmin = role === 'admin';
  const [running, setRunning] = useState<{ askedAt: number; baseline: string | null } | null>(null);
  const [gaveUp, setGaveUp] = useState(false);
  const status = useApiResource<MlStatus>('/ml/status', { what: 'The model status', intervalMs: running && !gaveUp ? FAST_MS : SLOW_MS });
  const machines = useApiResource<Device[]>('/devices', { params: { limit: 200 }, what: 'The machines', intervalMs: 60_000 });
  const [confirm, setConfirm] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorRef, setErrorRef] = useState<string | null>(null);

  const finishedAt = status.data?.last_retrain?.finished_at ?? null;

  // the result of a retrain is not in the answer to the request: the status route holds it when the run ends
  const finished = running !== null && retrainFinished(finishedAt, running.baseline, running.askedAt);
  const waiting = running !== null && !finished && !gaveUp;

  useEffect(() => {
    if (!running) return;
    const left = Math.max(0, running.askedAt + GIVE_UP_MS - Date.now());
    const t = setTimeout(() => setGaveUp(true), left);
    return () => clearTimeout(t);
  }, [running]);

  async function retrain() {
    setPending(true);
    setError(null);
    setGaveUp(false);
    const baseline = status.data?.last_retrain?.finished_at ?? null;
    try {
      await api.post('/ml/retrain');
      setConfirm(false);
      setRunning({ askedAt: Date.now(), baseline });
    } catch (err) {
      const code = (err as { response?: { status?: number } } | null)?.response?.status;
      setError(code === 429 || code === 403 ? retrainRefusalWords(code, detailOf(err)) : describeApiError(err, 'The retrain'));
      setErrorRef(requestIdOf(err) ?? null);
      setConfirm(false);
    } finally {
      setPending(false);
    }
  }

  const ml = status.data;
  const retrainInfo = ml?.last_retrain ?? null;
  const models = retrainInfo?.models ?? [];
  const refused = models.filter((m) => m.state === 'refused');
  const counts = retrainCounts(retrainInfo);
  const nightly = nightlyWords(ml?.schedule?.nightly_utc);
  const learningNotes = retrainInfo?.learning ?? [];
  const learningMachines = (machines.data ?? []).filter((d) => d.model?.state === 'learning').length;

  const actions = isAdmin ? (
    <Button onClick={() => { setError(null); setConfirm(true); }} pending={waiting} disabled={waiting}>
      {waiting ? 'Retrain running' : 'Retrain now'}
    </Button>
  ) : undefined;

  let body;
  if (status.error && !ml) {
    body = <ErrorNotice requestId={status.errorRef} message={status.error} detail="The model state is unknown. This is not the same as no models." onRetry={status.retry} pending={status.loading} />;
  } else if (!ml) {
    body = <SkeletonRows rows={6} label="Loading the model status" />;
  } else {
    body = (
      <>
        {status.error && <ErrorNotice message="The model status could not be refreshed. This page may be out of date." detail={status.error} onRetry={status.retry} />}

        <Panel title="What the model does" bodyClassName="p-4">
          <div className="max-w-[72ch] space-y-2 text-base text-surface-900 dark:text-surface-50">
            <p>{fileStateWords(ml.state)}</p>
            <p className="flex items-start gap-2 font-medium">
              <span className="mt-1.5 text-brand-800 dark:text-brand-400"><StatusShape shape="square" /></span>
              <span>{NO_ALERTS_WHILE_LEARNING} {learningMachines > 0 ? `${plural(learningMachines, 'machine is', 'machines are')} learning now.` : ''}</span>
            </p>
            {ml.trained_at && <p className="text-surface-800 dark:text-surface-200">The models in service were trained <Time value={ml.trained_at} format="datetime" />.</p>}
          </div>
        </Panel>

        <Panel title="Last retrain" bodyClassName="p-4">
          {!retrainInfo ? (
            <EmptyState heading="No retrain has run yet" subMessage={nightly ? `The first one runs at ${nightly}.` : 'The first one runs on the nightly schedule or when an admin starts it.'} />
          ) : (
            <div className="max-w-[72ch] space-y-3 text-base text-surface-900 dark:text-surface-50">
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <StatusBadge status={retrainInfo.status === 'trained' ? 'healthy' : 'warning'} label={retrainInfo.status === 'trained' ? 'Trained' : 'Refused'} />
                <span className="font-medium">{retrainHeadline(retrainInfo)}</span>
              </p>
              {retrainInfo.finished_at && <p className="text-surface-800 dark:text-surface-200">Finished <Time value={retrainInfo.finished_at} format="datetime" />.</p>}
              <p className="text-surface-800 dark:text-surface-200">
                {plural(counts.ready, 'model')} accepted, {counts.refused} refused and {counts.learning} still learning.
              </p>
              {retrainInfo.summary && <p className="text-surface-800 dark:text-surface-200">{retrainInfo.summary}</p>}
            </div>
          )}
        </Panel>

        {models.length > 0 && (
          <Panel title="Every model in the last retrain" description="The measured false alerts are on healthy readings the model did not train on. A model over the budget is refused." bodyClassName="p-0">
            <ModelRows models={models} />
          </Panel>
        )}

        <Panel title="Refusals" description="A refused model never replaces one in service. Each message says what to do." bodyClassName="p-0">
          {refused.length === 0 && learningNotes.length === 0 ? (
            <EmptyState heading="Nothing was refused" subMessage={retrainInfo && models.length > 0 ? 'Every model in the last retrain was accepted.' : retrainInfo ? 'The last retrain had no machines to judge, so it refused nothing.' : 'There is no retrain to refuse anything yet.'} />
          ) : (
            <ul className="divide-y divide-surface-200 dark:divide-surface-800">
              {refused.map((m) => {
                const rows = rowsRefusedWords(m.rows_refused);
                const det = detectionWords(m.detection);
                const fa = falseAlertRow(m.false_alerts_per_week, m.budget_per_week ?? FALSE_ALERT_BUDGET);
                return (
                  <li key={m.key} className="px-4 py-3">
                    <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <StatusBadge status="warning" label="Refused" />
                      <span className="text-base font-medium text-surface-900 dark:text-surface-50">{modelName(m)}</span>
                    </p>
                    <p className="mt-1 max-w-[72ch] text-base text-surface-900 dark:text-surface-50">{m.message || 'No reason was given.'}</p>
                    {(rows || det || fa.rate !== null) && (
                      <ul className="mt-1 max-w-[72ch] list-disc space-y-0.5 pl-5 text-sm text-surface-800 dark:text-surface-200">
                        {fa.rate !== null && <li>{fa.words}.</li>}
                        {det && <li>{det}</li>}
                        {rows && <li>{rows}</li>}
                      </ul>
                    )}
                  </li>
                );
              })}
              {learningNotes.map((text) => (
                <li key={text} className="px-4 py-3">
                  <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <StatusBadge status="open" label="Learning" />
                  </p>
                  <p className="mt-1 max-w-[72ch] text-base text-surface-900 dark:text-surface-50">{text}</p>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Schedule" bodyClassName="p-4">
          <div className="max-w-[72ch] space-y-1 text-base text-surface-900 dark:text-surface-50">
            {nightly ? <p>Models are retrained every night at {nightly}.</p> : <p>The API did not say when the nightly retrain runs.</p>}
            {ml.schedule?.next_at ? <p>Next retrain: <Time value={ml.schedule.next_at} format="datetime" />.</p> : null}
            {isAdmin ? <p className="text-surface-800 dark:text-surface-200">An admin can also retrain now. A retrain reads the last 14 days of each machine, one machine at a time.</p> : null}
          </div>
        </Panel>

        <Panel title="Every machine" description="What the model is doing for each machine." bodyClassName="p-0">
          {machines.error && !machines.data ? (
            <div className="p-4"><ErrorNotice message={machines.error} onRetry={machines.retry} pending={machines.loading} /></div>
          ) : !machines.data ? (
            <div className="p-4"><SkeletonRows rows={3} label="Loading machines" /></div>
          ) : machines.data.length === 0 ? (
            <EmptyState heading="No machines yet" subMessage="A machine is scored once it has a day of clean readings." />
          ) : (
            <DataTable caption="Machines and the state of their anomaly model" minWidth="32rem">
              <thead>
                <tr><th scope="col">Machine</th><th scope="col">Anomaly model</th></tr>
              </thead>
              <tbody>
                {machines.data.map((d) => (
                  <tr key={d.id}>
                    <th scope="row" className="text-left font-medium">
                      <Link href={`/devices/${d.id}`} className="inline-flex min-h-[44px] items-center whitespace-nowrap text-brand-800 underline-offset-2 hover:underline dark:text-brand-400">{d.name}</Link>
                    </th>
                    <td><ModelBadge device={d} status={ml} detail link={false} /></td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </Panel>
      </>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Anomaly models" description="Each machine has a model of how it normally behaves. It raises an anomaly alert when a sensor leaves its usual range. This page shows what is in service and why a model was refused." actions={actions} />
      <div role="status" className="text-base font-medium text-surface-900 dark:text-surface-50 empty:hidden">
        {waiting && running ? <>A retrain was started at <Time value={running.askedAt} format="datetime" />. It runs in the background and the result appears here when it finishes.</> : null}
        {finished ? 'The retrain finished. Its result is below.' : null}
        {running && gaveUp && !finished ? 'The retrain has not reported after 10 minutes. The result appears here when it does.' : null}
      </div>
      {error && <ErrorNotice message="The retrain was not started." detail={error} requestId={errorRef} />}
      {body}

      <ConfirmDialog
        open={confirm}
        destructive={false}
        title="Retrain the anomaly models?"
        confirmLabel="Retrain now"
        pending={pending}
        onCancel={() => setConfirm(false)}
        onConfirm={retrain}
      >
        <div className="space-y-2">
          <p>This runs in the background and reads the last 14 days of each machine. It can take a few minutes.</p>
          <p>A model that would raise more than {FALSE_ALERT_BUDGET} false alert per machine per week is refused and so is one that finds fewer than half of the faults tried on it. A refused model never replaces one in service.</p>
          <p>It cannot be started again for a while and the result is read from this page when it finishes.</p>
        </div>
      </ConfirmDialog>
    </div>
  );
}
