import { cn } from '@/lib/cn';

// says why a control is missing, in words: a viewer account reads and does not change. Shown once on a page that would
// otherwise offer an action, so the missing button is explained and not just absent.
export default function ReadOnlyNote({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <p role="note" className={cn('max-w-[72ch] text-base text-surface-800 dark:text-surface-200', className)}>
      <span className="font-medium">View-only account.</span> {children}
    </p>
  );
}
