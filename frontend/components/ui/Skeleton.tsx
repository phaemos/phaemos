import { cn } from '@/lib/cn';

// one placeholder block. It is hidden from assistive technology, so wrap a group in SkeletonGroup (or use
// SkeletonRows) to give the group a single spoken label.
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn('h-4 rounded bg-surface-200 dark:bg-surface-800', className)} />;
}

// names a loading region once for screen readers. The pulse stops under reduced motion through the global rule.
export function SkeletonGroup({ label = 'Loading', className, children }: { label?: string; className?: string; children: React.ReactNode }) {
  return (
    <div role="status" className={className}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

// the widths cycle so the rows do not look like one uniform bar. Nothing is random so server and client match
const WIDTHS = ['w-full', 'w-5/6', 'w-4/5'];

export function SkeletonRows({ rows = 3, label, className }: { rows?: number; label?: string; className?: string }) {
  return (
    <SkeletonGroup label={label} className={cn('space-y-3', className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={WIDTHS[i % WIDTHS.length]} />
      ))}
    </SkeletonGroup>
  );
}

export default Skeleton;
