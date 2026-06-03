'use client';

import { useEffect, useState } from 'react';

interface StatusResponse {
  status: 'operational' | 'degraded';
  api: 'ok' | 'error';
  database: 'ok' | 'error';
  redis: 'ok' | 'error';
  updated_at: string;
}

const COMPONENTS: { key: keyof Pick<StatusResponse, 'api' | 'database' | 'redis'>; label: string }[] = [
  { key: 'api',      label: 'API' },
  { key: 'database', label: 'Database' },
  { key: 'redis',    label: 'Cache (Redis)' },
];

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short',
  });
}

export default function StatusPage() {
  const [data, setData]       = useState<StatusResponse | null>(null);
  const [error, setError]     = useState(false);
  const [loading, setLoading] = useState(true);

  async function fetchStatus() {
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/status`,
        { cache: 'no-store' },
      );
      if (!res.ok) throw new Error('non-2xx');
      setData(await res.json());
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStatus();
    // I poll every 30s so the page stays current without a manual refresh.
    const id = setInterval(fetchStatus, 30_000);
    return () => clearInterval(id);
  }, []);

  const degraded = !error && data?.status === 'degraded';

  return (
    <main className="p-6 max-w-2xl mx-auto space-y-8">

      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-widest text-surface-400 dark:text-surface-500">
          System status
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-surface-900 dark:text-surface-50">
          PHAEMOS Status
        </h1>
      </section>

      {/* Overall banner */}
      <div className={`card p-5 flex items-center gap-4 border-l-4 ${
        loading  ? 'border-surface-300 dark:border-surface-700' :
        error    ? 'border-critical-500' :
        degraded ? 'border-warning-500' :
                   'border-success-500'
      }`}>
        <span className={`w-3 h-3 rounded-full shrink-0 ${
          loading  ? 'bg-surface-300 dark:bg-surface-700' :
          error    ? 'bg-critical-500' :
          degraded ? 'bg-warning-500 animate-pulse' :
                     'bg-success-500'
        }`} />
        <div>
          <p className="font-semibold text-surface-900 dark:text-surface-50">
            {loading  ? 'Checking status...' :
             error    ? 'Status unavailable' :
             degraded ? 'Partial outage' :
                        'All systems operational'}
          </p>
          {data && !error && (
            <p className="text-xs text-surface-400 dark:text-surface-500 mt-0.5">
              Last checked: {formatTime(data.updated_at)}
            </p>
          )}
        </div>
      </div>

      {/* Component breakdown */}
      <section className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-surface-400 dark:text-surface-500">
          Components
        </p>
        <div className="card divide-y divide-surface-200 dark:divide-surface-800">
          {COMPONENTS.map(({ key, label }) => {
            const val = data?.[key];
            const ok  = val === 'ok';
            return (
              <div key={key} className="flex items-center justify-between px-5 py-4">
                <span className="text-sm font-medium text-surface-900 dark:text-surface-50">
                  {label}
                </span>
                {loading || !data ? (
                  <span className="text-xs text-surface-400 dark:text-surface-500">Checking...</span>
                ) : (
                  <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${
                    ok
                      ? 'bg-success-50 dark:bg-success-500/10 text-success-600 dark:text-success-400'
                      : 'bg-critical-50 dark:bg-critical-500/10 text-critical-600 dark:text-critical-400'
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-success-500' : 'bg-critical-500'}`} />
                    {ok ? 'Operational' : 'Error'}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Public status page link */}
      <div className="card p-4 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-surface-900 dark:text-surface-50">
            Public status page
          </p>
          <p className="text-xs text-surface-400 dark:text-surface-500 mt-0.5">
            Incident history and uptime reports for external users
          </p>
        </div>
        <a
          href="https://status.phaemos.com"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs font-medium text-brand-600 dark:text-brand-400 hover:underline shrink-0"
        >
          status.phaemos.com &rarr;
        </a>
      </div>

      {/* Footer note */}
      <p className="text-xs text-surface-400 dark:text-surface-500 text-center">
        Auto-refreshes every 30 seconds.{' '}
        For incident reports, contact{' '}
        <a href="mailto:support@phaemos.com" className="text-brand-600 dark:text-brand-400 hover:underline">
          support@phaemos.com
        </a>
        .
      </p>

    </main>
  );
}
