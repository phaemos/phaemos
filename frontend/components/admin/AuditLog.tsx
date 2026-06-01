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
      <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <table className="w-full text-sm text-gray-700 dark:text-gray-300">
          <thead className="bg-gray-100 dark:bg-gray-800 text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            <tr>
              <th className="px-4 py-3 text-left">When</th>
              <th className="px-4 py-3 text-left">User</th>
              <th className="px-4 py-3 text-left">Action</th>
              <th className="px-4 py-3 text-left">Resource</th>
              <th className="px-4 py-3 text-left">Detail</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {entries.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-gray-400 dark:text-gray-500">
                  No audit events yet
                </td>
              </tr>
            ) : (
              entries.map((e) => (
                <tr key={e.id} className="hover:bg-gray-50 dark:hover:bg-white/5 transition-colors">
                  <td className="px-4 py-3 text-gray-400 dark:text-gray-500 text-xs whitespace-nowrap">
                    {new Date(e.created_at).toLocaleString('en-GB', {
                      day: '2-digit',
                      month: 'short',
                      year: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-500 dark:text-gray-400 max-w-[8rem] truncate">
                    {e.user_id}
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-indigo-100 dark:bg-indigo-500/20 px-2 py-0.5 text-xs text-indigo-700 dark:text-indigo-300">
                      {e.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                    <span className="text-gray-700 dark:text-gray-300">{e.resource}</span>
                    <span className="ml-1 font-mono text-xs text-gray-400 dark:text-gray-600 truncate max-w-[6rem] inline-block align-bottom">
                      {e.resource_id}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-400 dark:text-gray-500 text-xs max-w-[14rem] truncate">
                    {e.detail || '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination - I use skip/limit rather than page numbers so the controls
            map directly onto the backend query params without any conversion. */}
        <div className="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-800/50 border-t border-gray-200 dark:border-gray-700">
          <button
            type="button"
            onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}
            disabled={skip === 0}
            className="rounded px-3 py-1 text-xs text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-xs text-gray-400 dark:text-gray-500">
            Showing {skip + 1}–{skip + entries.length}
          </span>
          <button
            type="button"
            onClick={() => setSkip(skip + PAGE_SIZE)}
            disabled={entries.length < PAGE_SIZE}
            className="rounded px-3 py-1 text-xs text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>
    </>
  );
}
