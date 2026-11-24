import Link from 'next/link';
import type { Device, MlStatus } from '@/types';
import ModelBadge from '@/components/machines/ModelBadge';
import DataTable from '@/components/ui/DataTable';
import { LastPost, LinkBadge, MachineBadge } from '@/components/machines/MachineStatus';
import type { AlertLike } from '@/lib/machineState';
import Badge from '@/components/ui/Badge';
import { nodeTypeLabel } from '@/lib/nodeTypes';
import { ownerLabel, type OwnerContext } from '@/lib/machineList';

interface Props {
  machines: Device[];
  // the active machine alerts, so a machine's state can say Warning or Fault
  alerts: readonly AlertLike[];
  owners: OwnerContext;
  // false while the lookup that names owners is still loading, so a name is not shown as "Another technician" first
  ownersReady: boolean;
  // GET /ml/status, for the refusal behind a machine with no model
  ml?: MlStatus | null;
}

// the machines as a table for scanning the fleet and finding the one that needs attention: the name first, then what the machine
// is and how it is watched, each short fact on one line and the secondary facts on a second line inside the cell. The row is
// one link: the name is the link and a pseudo-element stretches it over the row. The owner column appears only when some machine
// has an owner, so it is never a column of "Unassigned".
export default function MachineTable({ machines, alerts, owners, ownersReady, ml }: Props) {
  const anyOwner = machines.some((m) => m.owner_id);
  const anyTags = machines.some((m) => m.tags && m.tags.length > 0);
  return (
    <DataTable caption="Machines, with state, monitoring link, last post, anomaly model, location, node type, tags and owner">
      <thead>
        <tr>
          <th scope="col">Machine</th>
          <th scope="col">Machine state</th>
          <th scope="col">Monitoring link</th>
          <th scope="col">Anomaly model</th>
          {anyTags && <th scope="col">Tags</th>}
          {anyOwner && <th scope="col">Owner</th>}
        </tr>
      </thead>
      <tbody>
        {machines.map((m) => (
          <tr key={m.id} className="row-action relative">
            <td className="whitespace-nowrap">
              <Link
                href={`/devices/${m.id}`}
                className="inline-flex min-h-[44px] items-center font-medium text-brand-800 underline-offset-2 after:absolute after:inset-0 hover:underline dark:text-brand-400"
              >
                {m.name}
              </Link>
              <span className="block text-meta text-surface-700 dark:text-surface-300">
                {m.location ?? 'No location'}, {nodeTypeLabel(m.type)}
              </span>
            </td>
            <td className="min-w-[14rem]"><MachineBadge device={m} alerts={alerts} /></td>
            <td className="whitespace-nowrap">
              <LinkBadge device={m} />
              <span className="block text-meta text-surface-700 dark:text-surface-300">Last post <LastPost device={m} showExact /></span>
            </td>
            <td className="min-w-[12rem]"><ModelBadge device={m} status={ml} raised /></td>
            {anyTags && (
              <td>
                {m.tags && m.tags.length > 0 ? (
                  <ul className="flex flex-wrap gap-1" aria-label={`Tags on ${m.name}`}>
                    {m.tags.map((t) => <li key={t}><Badge>{t}</Badge></li>)}
                  </ul>
                ) : (
                  <span className="text-surface-600 dark:text-surface-400">No tags</span>
                )}
              </td>
            )}
            {anyOwner && (
              <td className="whitespace-nowrap text-surface-700 dark:text-surface-300">
                {!m.owner_id ? 'Unassigned' : ownersReady ? ownerLabel(m.owner_id, owners) : <span className="text-surface-600 dark:text-surface-400">Loading</span>}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}
