import type { ReactNode } from 'react';
import RequestRef from '@/components/ui/RequestRef';

// one headed block of the profile page. Sections are told apart by a heading, spacing and a hairline rule, not by boxes.
export default function Section({ id, title, description, children }: { id: string; title: string; description?: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-heading`} className="border-t border-surface-200 py-8 first:border-t-0 first:pt-0 dark:border-surface-800">
      <h2 id={`${id}-heading`} className="text-base font-semibold text-surface-900 dark:text-surface-50">{title}</h2>
      {description && <p className="mt-1 max-w-[72ch] text-base text-surface-600 dark:text-surface-400">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

// the outcome of a form, in one reserved line so it never moves the controls around it. The success line is a polite
// status and the failure line an alert. Both exist before they have text so a screen reader announces the change.
export function FormMessage({ ok, error, requestId }: { ok?: string; error?: string; requestId?: string | null }) {
  return (
    <div className="min-h-5">
      <p role="status" className="text-base text-surface-900 dark:text-surface-50">{ok}</p>
      <p role="alert" className="text-base font-medium text-critical-800 dark:text-critical-300">{error}</p>
      {error && <RequestRef id={requestId} />}
    </div>
  );
}
