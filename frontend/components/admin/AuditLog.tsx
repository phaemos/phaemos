'use client';

import { useState, useEffect } from 'react';
import api from '../../lib/api';
import LoadingSkeleton from '../ui/LoadingSkeleton';
import ErrorToast from '../ui/ErrorToast';

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

export default function AuditLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [skip, setSkip] = useState(0);

  useEffect(() => {
    setLoading(true);
    api
      .get<AuditEntry[]>('/audit-logs', { params: { skip, limit: PAGE_SIZE } })
      .then((r) => {
        setEntries(r.data);
        setError(null);
      })
      .catch((err: unknown) => {
        const message =
          err instanceof Error ? err.message : 'Failed to fetch audit log';
        setError(message);
      })
      .finally(() => setLoading(false));
  }, [skip]);

  if (loading) return <LoadingSkeleton />;

  return (
    <>
      {error && <ErrorToast message={error} onDismiss={() => setError(null)} />}
      <div className="rounded-xl border border-surface-200 dark:border-surface-800 overflow-hidden">
        <table className="w-full text-sm text-surface-800 dark:text-surface-200">
          <thead className="bg-surface-100 dark:bg-surface-800 text-xs text-surface-600 dark:text-surface-400 uppercase tracking-wider">
            <tr>
              <th className="px-4 py-3 text-left">When</th>
              <th className="px-4 py-3 text-left">User</th>
              <th className="px-4 py-3 text-left">Action</th>
              <th className="px-4 py-3 text-left">Resource</th>
              <th className="px-4 py-3 text-left">Detail</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-100 dark:divide-surface-800">
            {entries.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-surface-400 dark:text-surface-600">
                  No audit events yet
                </td>
              </tr>
            ) : (
              entries.map((e) => (
                <tr key={e.id} className="hover:bg-surface-50 dark:hover:bg-white/5 transition-colours">
                  <td className="px-4 py-3 text-surface-400 dark:text-surface-600 text-xs whitespace-nowrap">
                    {new Date(e.created_at).toLocaleString('en-GB', {
                      day: '2-digit',
                      month: 'short',
                      year: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-surface-600 dark:text-surface-400 max-w-[8rem] truncate">
                    {e.user_id}
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-brand-50 dark:bg-brand-600/20 px-2 py-0.5 text-xs text-brand-600 dark:text-brand-400">
                      {e.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-surface-600 dark:text-surface-400">
                    <span className="text-surface-800 dark:text-surface-200">{e.resource}</span>
                    <span className="ml-1 font-mono text-xs text-surface-400 dark:text-surface-600 truncate max-w-[6rem] inline-block align-bottom">
                      {e.resource_id}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-surface-400 dark:text-surface-600 text-xs max-w-[14rem] truncate">
                    {e.detail || '-'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination - I use skip/limit rather than page numbers so the controls
            map directly onto the backend query params without any conversion. */}
        <div className="flex items-center justify-between px-4 py-3 bg-surface-50 dark:bg-surface-800/50 border-t border-surface-200 dark:border-surface-800">
          <button
            type="button"
            onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}
            disabled={skip === 0}
            className="rounded px-3 py-1 text-xs text-surface-600 dark:text-surface-400 hover:text-surface-900 dark:hover:text-surface-50 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-xs text-surface-400 dark:text-surface-600">
            Showing {skip + 1}–{skip + entries.length}
          </span>
          <button
            type="button"
            onClick={() => setSkip(skip + PAGE_SIZE)}
            disabled={entries.length < PAGE_SIZE}
            className="rounded px-3 py-1 text-xs text-surface-600 dark:text-surface-400 hover:text-surface-900 dark:hover:text-surface-50 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>
    </>
  );
}
