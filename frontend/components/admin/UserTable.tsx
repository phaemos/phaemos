'use client';

import { useState, useEffect } from 'react';
import type { User } from '../../types/index';
import api from '../../lib/api';
import LoadingSkeleton from '../ui/LoadingSkeleton';
import ErrorToast from '../ui/ErrorToast';

export default function UserTable() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // I fetch once on mount - the user list does not change often enough
    // to warrant polling, and an admin can refresh the page to see new users.
    api.get<User[]>('/auth/users')
      .then((r) => setUsers(r.data))
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Failed to fetch users';
        setError(message);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingSkeleton />;

  return (
    <>
      {error && <ErrorToast message={error} onDismiss={() => setError(null)} />}
      <div className="rounded-xl border border-surface-200 dark:border-surface-800 overflow-hidden">
        <table className="w-full text-sm text-surface-800 dark:text-surface-200">
          <thead className="bg-surface-100 dark:bg-surface-800 text-xs text-surface-600 dark:text-surface-400 uppercase tracking-wider">
            <tr>
              <th className="px-4 py-3 text-left">Name</th>
              <th className="px-4 py-3 text-left">Email</th>
              <th className="px-4 py-3 text-left">Role</th>
              <th className="px-4 py-3 text-left">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-100 dark:divide-surface-800">
            {users.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-surface-400 dark:text-surface-600">
                  No users found
                </td>
              </tr>
            ) : (
              users.map((u) => (
                <tr key={u.id} className="hover:bg-surface-50 dark:hover:bg-white/5 transition-colours">
                  <td className="px-4 py-3 font-medium text-surface-800 dark:text-surface-200">
                    {u.name ?? '—'}
                  </td>
                  <td className="px-4 py-3 text-surface-600 dark:text-surface-400">{u.email}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        u.role === 'admin'
                          ? 'bg-brand-50 dark:bg-brand-600/20 text-brand-600 dark:text-brand-400'
                          : u.role === 'technician'
                          ? 'bg-primary-100 dark:bg-primary-600/20 text-primary-600 dark:text-primary-400'
                          : 'bg-surface-100 dark:bg-surface-600/20 text-surface-600 dark:text-surface-400'
                      }`}
                    >
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-surface-400 dark:text-surface-600 text-xs">
                    {new Date(u.created_at ?? '').toLocaleDateString('en-GB', {
                      day: '2-digit',
                      month: 'short',
                      year: 'numeric',
                    })}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
