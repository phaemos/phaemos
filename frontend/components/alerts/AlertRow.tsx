'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import type { Alert } from '@/types';
import { TicketAction } from '@/components/AlertBanner';
import Button from '@/components/ui/Button';
import StatusBadge from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';
import { evidenceWindowWords } from '@/lib/anomalyEvidence';
import { alertFacts, isModelAlert, occurrenceOf, ruleHeadline } from '@/lib/alertLife';
import { alertMachineHref, alertText } from './alertText';
import RangeMark from './RangeMark';

const LINK = 'inline-flex min-h-[44px] items-center text-sm font-medium text-brand-800 underline-offset-2 hover:underline dark:text-brand-400';

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="label text-surface-700 dark:text-surface-300">{label}</dt>
      <dd className="text-base text-surface-900 dark:text-surface-50">{children}</dd>
    </div>
  );
}

interface Props {
  alert: Alert;
  name: string;
  // the actions exist only for an active alert
  canAct?: boolean;
  pending?: boolean;
  onResolve?: (alert: Alert) => void;
  // the machine page is already about one machine, so the name and the link to it are left out
  hideMachine?: boolean;
  // a fixed clock for sample data
  now?: number;
  // false renders the actions as plain text for the public illustration, where nothing is clickable
  interactive?: boolean;
}

// one alert. It lasts as long as its condition, so the row says when the condition first held, when the alert was raised, whether it is
// still occurring (or when it was last seen), how many readings met it and the peak and latest values with their unit. A model alert
// says in words which sensor stood out and where its value sits against the machine's usual range, with a small range mark.
export default function AlertRow({ alert, name, canAct = false, pending = false, onResolve, hideMachine = false, now, interactive = true }: Props) {
  const model = isModelAlert(alert);
  const monitoring = alert.category === 'monitoring';
  const facts = alertFacts(alert);
  const life = occurrenceOf(alert);
  const headline = model ? alertText(alert) : (ruleHeadline(alert) ?? alertText(alert));
  const window = model ? evidenceWindowWords(alert.evidence) : null;
  const rule = !model && !monitoring && alert.rule_id !== null;
  // the model's alert has no hold and no count of readings that met a rule, so those lines are left to the rule alert
  const showFirst = rule;
  const source = monitoring ? 'Monitoring' : model ? 'Anomaly model' : 'Alert rule';
  const href = alertMachineHref(alert);
  const stillOccurring = alert.still_occurring === true && !alert.resolved;

  return (
    <li className="px-4 py-3">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-x-4 gap-y-2 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
            <StatusBadge status={alert.severity ?? 'info'} />
            {hideMachine ? null : <span className="text-sm font-medium text-surface-900 dark:text-surface-50">{name}</span>}
            <span className="text-meta text-surface-700 dark:text-surface-300">{source}</span>
          </p>
          <p className={`mt-1 break-words text-base text-surface-900 dark:text-surface-50 ${!model && !monitoring ? 'num' : ''}`}>{headline}</p>
          {monitoring && <p className="text-meta font-medium text-surface-800 dark:text-surface-200">About the monitoring of this machine, not the machine itself.</p>}
          {model && <RangeMark evidence={alert.evidence} />}
          {window && <p className="mt-1 text-sm text-surface-700 dark:text-surface-300">{window}.</p>}

          <dl className="mt-2 grid grid-cols-[minmax(0,1fr)] gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
            {(showFirst || (model && alert.first_seen_at)) && (
              <Fact label="Condition first held">
                {alert.first_seen_at ? <Time value={alert.first_seen_at} now={now} format="datetime" /> : <span className="text-surface-700 dark:text-surface-300">Not recorded</span>}
              </Fact>
            )}
            <Fact label="Alert raised"><Time value={alert.triggered_at} now={now} format="datetime" /></Fact>
            <Fact label={life.state === 'resolved' ? 'Resolved' : 'Status'}>
              {life.state === 'resolved' ? (
                life.at ? <Time value={life.at} now={now} format="datetime" /> : 'Resolved'
              ) : life.state === 'occurring' ? (
                <StatusBadge status="open" label="Still occurring" className="text-base" />
              ) : life.state === 'last_seen' ? (
                <span className="inline-flex flex-wrap items-center gap-x-2">
                  <StatusBadge status="closed" label="Not occurring now" className="text-base" />
                  <span className="text-sm text-surface-800 dark:text-surface-200">last seen <Time value={life.at} now={now} format="relative" /></span>
                </span>
              ) : (
                <span className="text-surface-700 dark:text-surface-300">Open</span>
              )}
            </Fact>
            {showFirst && facts.readings && <Fact label="Readings that met it"><span className="tnum">{facts.readings}</span></Fact>}
            {(showFirst || model) && facts.peak && <Fact label={facts.peakLabel}><span className="num">{facts.peak}</span></Fact>}
            {showFirst && facts.latest && <Fact label={facts.latestLabel}><span className="num">{facts.latest}</span></Fact>}
          </dl>
          {stillOccurring && <p role="status" className="sr-only">This alert is still occurring.</p>}
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 lg:justify-end">
          {interactive ? (
            <>
              {canAct && <TicketAction alert={alert} detail={facts.readings ? `${facts.readings} so far.` : undefined} />}
              {canAct && onResolve && (
                <Button variant="secondary" pending={pending} onClick={() => onResolve(alert)}>
                  Resolve<span className="sr-only"> alert on {name}</span>
                </Button>
              )}
              {!hideMachine && <Link href={href} className={LINK}>{monitoring ? 'Open monitoring health' : 'View machine'}<span className="sr-only">: {name}</span></Link>}
            </>
          ) : (
            <span className="inline-flex min-h-[44px] items-center justify-center rounded-md border border-surface-500 px-4 text-sm font-medium text-surface-900 dark:text-surface-50">Create ticket</span>
          )}
        </div>
      </div>
    </li>
  );
}
