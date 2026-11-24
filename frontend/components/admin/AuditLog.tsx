'use client';

import { useMemo, useState } from 'react';
import type { User } from '@/types';
import { useApiResource } from '@/hooks/useApiResource';
import { useAllUsers } from './useAllUsers';
import { formatDateTime, formatDateTimeExact } from '@/lib/format';
import DataTable from '@/components/ui/DataTable';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import Panel from '@/components/ui/Panel';
import { SkeletonRows } from '@/components/ui/Skeleton';
import Pager from './Pager';
import Time from '@/components/ui/Time';

interface AuditEntry {
  id: string;
  user_id: string;
  action: string;
  resource: string;
  resource_id: string;
  detail: string;
  created_at: string;
}

const PAGE_SIZE = 50;

// GET /audit-logs with skip and limit, newest first. The API records a user id, so the users are read once to show
// an email instead. If that read fails the short id is shown and the log still works.
export default function AuditLog() {
  const [skip, setSkip] = useState(0);
  const { data, error, loading, retry } = useApiResource<AuditEntry[]>('/audit-logs', { params: { skip, limit: PAGE_SIZE }, what: 'The audit log' });
  const users = useAllUsers();
  const emails = useMemo(() => Object.fromEntries(users.users.map((u) => [u.id, u.email])), [users.users]);

  return (
    <Panel title="Recorded actions" description="Newest first. Only admins can read this." bodyClassName="p-0">
      {loading && !data ? (
        <div className="p-4"><SkeletonRows rows={5} label="Loading the audit log" /></div>
      ) : error && !data ? (
        <div className="p-4"><ErrorNotice message={error} onRetry={retry} /></div>
      ) : data && data.length === 0 && skip === 0 ? (
        <EmptyState heading="Nothing logged yet" subMessage="Firmware uploads, ticket changes and other admin actions are recorded here." />
      ) : data ? (
        <>
          {error && <div className="p-4"><ErrorNotice message={error} onRetry={retry} /></div>}
          {users.error && <div className="p-4"><ErrorNotice message="The user names could not be loaded, so the User column shows short ids." detail={users.error} onRetry={users.retry} /></div>}
          <DataTable caption="Audit log">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">User</th>
                <th scope="col">Action</th>
                <th scope="col">Resource</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {data.map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap"><Time value={e.created_at} /></td>
                  <td>{emails[e.user_id] ?? <span className="num" title={e.user_id}>{e.user_id.slice(0, 8)}</span>}</td>
                  <td>{e.action.replace(/_/g, ' ')}</td>
                  <td>
                    {e.resource}
                    {e.resource_id && <span className="num ml-2 text-surface-600 dark:text-surface-400" title={e.resource_id}>{e.resource_id.slice(0, 8)}</span>}
                  </td>
                  <td className="max-w-[24rem] break-words">{e.detail || ''}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
          <Pager skip={skip} shown={data.length} pageSize={PAGE_SIZE} onChange={setSkip} what="Audit log" />
        </>
      ) : null}
    </Panel>
  );
}
