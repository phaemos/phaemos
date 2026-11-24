'use client';

import { useApiResource } from '@/hooks/useApiResource';
import { StatusShape } from '@/components/ui/StatusBadge';
import { limitSentence, limitsFromMetrics, limitsReached, resumeWords, type AuditEntryLike, type DailyLimit } from '@/lib/notificationLimit';
import { serverNow } from '@/lib/serverClock';

interface Metrics {
  daily_limits?: Record<string, DailyLimit> | null;
}

// says when the daily alert email or text limit has stopped messages. Every signed-in role reads it from `daily_limits` on
// GET /alert-metrics. An API that does not send that field falls back, for an admin only, to the audit entry written when a limit is
// reached. Alerts are always recorded, which the notice says first. While the read loads nothing shows. If it cannot be read the page
// says so, so a missing notice is not taken to mean no limit was reached.
export default function NotificationLimitNotice({ isAdmin }: { isAdmin: boolean }) {
  const metrics = useApiResource<Metrics>('/alert-metrics', { what: 'The alert limits', intervalMs: 60_000 });
  const hasField = Boolean(metrics.data && metrics.data.daily_limits);
  const audit = useApiResource<AuditEntryLike[]>('/audit-logs', { params: { limit: 100 }, what: 'The audit log', intervalMs: 60_000, enabled: isAdmin && Boolean(metrics.data) && !hasField });
  if (metrics.error && !metrics.data) {
    return <p className="text-meta text-surface-700 dark:text-surface-300">Whether the daily email and text limit was reached could not be checked. {metrics.error}</p>;
  }
  const limits = hasField ? limitsFromMetrics(metrics.data?.daily_limits) : limitsReached(audit.data, serverNow());
  if (limits.length === 0) return null;
  const when = resumeWords(limits[0].resumesAt);
  return (
    <p role="status" className="flex max-w-[80ch] items-start gap-2 rounded-lg border border-warning-800 px-4 py-3 text-base font-medium text-surface-900 dark:border-warning-400 dark:text-surface-50">
      <span className="mt-1.5 text-warning-800 dark:text-warning-400"><StatusShape shape="triangle" /></span>
      <span>{limitSentence(limits, when)}</span>
    </p>
  );
}
