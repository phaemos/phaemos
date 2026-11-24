'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { clearSession } from '@/lib/session';
import api from '@/lib/api';
import { errorInfo } from '@/lib/apiCode';
import { describeApiError } from '@/lib/apiError';
import { useApiResource } from '@/hooks/useApiResource';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { SkeletonRows } from '@/components/ui/Skeleton';
import Time from '@/components/ui/Time';
import { TOKENS_REVOKED_NOTE } from '@/lib/tokenScopes';
import Section, { FormMessage } from './Section';

interface SessionRow {
  id: string;
  // a coarse description made from the browser's name when the session began: "Chrome on macOS" or "Unknown browser"
  label: string;
  created_at: string;
  last_used_at: string;
  current: boolean;
}

// GET /auth/sessions lists the person's own live sessions. DELETE /auth/sessions/{id} ends one and
// POST /auth/sessions/end-others ends all but this one. No address is shown because the API keeps none.
export default function SessionsSection() {
  const router = useRouter();
  const { data, error: loadError, loading, retry } = useApiResource<SessionRow[]>('/auth/sessions', { what: 'Your sessions' });
  const [ending, setEnding] = useState<string | null>(null);
  const [askAll, setAskAll] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');
  const [reference, setReference] = useState<string | null>(null);

  const others = (data ?? []).filter((s) => !s.current);

  async function endOne(row: SessionRow) {
    setError('');
    setOk('');
    setEnding(row.id);
    try {
      await api.delete(`/auth/sessions/${row.id}`);
      if (row.current) {
        // this browser's own session: the API has cleared the cookies, so this browser forgets its token and goes to sign-in
        await clearSession({ anyway: true });
        router.push('/login');
        return;
      }
      setOk(`Signed out ${row.label}.`);
      retry();
    } catch (err) {
      // a session that has already ended answers 404, which is the state the person wanted
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 404) retry();
      else { const info = errorInfo(err); setError(info.detail ?? describeApiError(err, 'The session')); setReference(info.requestId ?? null); }
    } finally {
      setEnding(null);
    }
  }

  async function endOthers() {
    setError('');
    setOk('');
    setPending(true);
    try {
      const { data: res } = await api.post<{ ended: number }>('/auth/sessions/end-others');
      setAskAll(false);
      setOk(res.ended === 1 ? 'Signed out 1 other session.' : `Signed out ${res.ended} other sessions.`);
      retry();
    } catch (err) {
      setAskAll(false);
      { const info = errorInfo(err); setError(info.detail ?? describeApiError(err, 'The sessions')); setReference(info.requestId ?? null); }
    } finally {
      setPending(false);
    }
  }

  return (
    <Section
      id="sessions"
      title="Where you are signed in"
      description="Each browser that is signed in to this account. A sign-in lasts at most 30 days, however often it is used. We keep a coarse browser name and the times and no address."
    >
      <div className="max-w-2xl space-y-4">
        {loading && !data ? (
          <SkeletonRows rows={2} label="Loading your sessions" />
        ) : loadError && !data ? (
          <ErrorNotice message={loadError} onRetry={retry} />
        ) : (
          <ul className="divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
            {(data ?? []).map((s) => (
              <li key={s.id} className="flex min-h-[56px] flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
                <div className="min-w-0">
                  <p className="text-base font-medium text-surface-900 dark:text-surface-50">
                    {s.label}
                    {s.current && <span className="ml-2 font-normal text-surface-700 dark:text-surface-300">This browser</span>}
                  </p>
                  <p className="text-base text-surface-600 dark:text-surface-400">
                    Signed in <Time value={s.created_at} format="datetime" />. Last used <Time value={s.last_used_at} format="relative" />.
                  </p>
                </div>
                <Button variant="secondary" size="small" onClick={() => endOne(s)} pending={ending === s.id} aria-label={s.current ? 'Sign out of this browser' : `Sign out ${s.label}, signed in ${new Date(s.created_at).toLocaleString('en-GB')}`}>
                  Sign out
                </Button>
              </li>
            ))}
          </ul>
        )}
        {others.length > 0 && <Button variant="secondary" onClick={() => setAskAll(true)}>Sign out everywhere else</Button>}
        <FormMessage ok={ok} error={error} requestId={reference} />
      </div>
      <ConfirmDialog open={askAll} title="Sign out everywhere else?" confirmLabel="Sign out the others" destructive={false} onCancel={() => setAskAll(false)} onConfirm={endOthers} pending={pending}>
        <p>
          {others.length === 1 ? 'The other browser' : `The other ${others.length} browsers`} will need a password to sign in again. This browser stays signed in. {TOKENS_REVOKED_NOTE}
        </p>
      </ConfirmDialog>
    </Section>
  );
}
