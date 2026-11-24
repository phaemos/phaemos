'use client';

import Link from 'next/link';
import { useState } from 'react';
import type { Alert } from '@/types';
import Button from '@/components/ui/Button';
import { useRole } from '@/hooks/useRole';
import { canWrite as canWriteRole } from '@/lib/role';
import { alertText } from '@/components/alerts/alertText';
import StatusBadge from '@/components/ui/StatusBadge';
import { parseAlertMessage } from '@/lib/alertGroups';
import { formatDateTime, formatDateTimeExact, formatRelative } from '@/lib/format';
import TicketDialog from './tickets/TicketDialog';
import TicketForm from './tickets/TicketForm';
import Time from '@/components/ui/Time';

interface ActionProps {
  // the alert the ticket is raised from: for a group of alerts this is the newest one
  alert: Alert;
  // extra words for the ticket description, such as how many times the alert fired
  detail?: string;
  className?: string;
  size?: 'default' | 'small';
}

// the one ticket action for an alert. An alert raised by the anomaly model already has a ticket,
// so those link to the ticket list instead of opening the form.
export function TicketAction({ alert, detail, className, size = 'default' }: ActionProps) {
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState(false);
  const role = useRole();
  // until the role is known no ticket control is offered, so a viewer never sees one flash
  const canWrite = canWriteRole(role);

  // an alert about the monitoring (a silent node) raises no ticket, so there is nothing to create or to open
  if (alert.category === 'monitoring') return null;

  if (alert.rule_id === null) {
    return <Button href="/tickets" variant="secondary" size={size} className={className}>View ticket</Button>;
  }

  // a viewer cannot create a ticket: the API answers 403. The page says so once, so the button is simply not offered.
  if (!canWrite) return null;

  // once the ticket exists the button gives way to a note, so a second click cannot raise a duplicate
  if (created) {
    return (
      <span role="status" className={`inline-flex min-h-[44px] items-center gap-2 text-base text-surface-800 dark:text-surface-200 ${className ?? ''}`}>
        Ticket created.
        <Link href="/tickets" className="font-medium text-brand-800 underline underline-offset-2 dark:text-brand-400">View tickets</Link>
      </span>
    );
  }

  const prefill = {
    device_id: alert.device_id,
    device_name: parseAlertMessage(alert.message)?.deviceName ?? undefined,
    // the title field holds 200 characters
    title: alertText(alert).slice(0, 200),
    description: `Raised from a ${alert.severity} alert at ${formatDateTime(alert.triggered_at)}.${detail ? ` ${detail}` : ''}`,
  };

  return (
    <>
      <Button variant="secondary" size={size} className={className} onClick={() => setOpen(true)}>Create ticket</Button>
      <TicketDialog open={open} title="Create ticket" onClose={() => setOpen(false)}>
        <TicketForm
          prefill={prefill}
          onCancel={() => setOpen(false)}
          onSuccess={() => {
            setOpen(false);
            setCreated(true);
          }}
        />
      </TicketDialog>
    </>
  );
}

interface Props {
  alert: Alert;
}

// one alert on its own line: severity shape and word, the message, when it fired and the ticket action
export default function AlertBanner({ alert }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 text-base">
      <span className="w-24 shrink-0"><StatusBadge status={alert.severity ?? 'info'} /></span>
      <span className="min-w-0 flex-1 basis-60 text-surface-800 dark:text-surface-200">{alertText(alert)}</span>
      <Time value={alert.triggered_at} format="relative" className="shrink-0 text-meta text-surface-600 dark:text-surface-400" />
      <TicketAction alert={alert} />
    </div>
  );
}
