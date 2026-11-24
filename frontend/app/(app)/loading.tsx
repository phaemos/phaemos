import { Skeleton, SkeletonGroup } from '@/components/ui/Skeleton';

// shown by Next while a signed-in page streams in. It stands in for a page header and a panel, in the shell's own
// width, so the page does not jump when the real content arrives.
export default function AppLoading() {
  return (
    <SkeletonGroup label="Loading the page" className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-72 max-w-full" />
      </div>
      <div className="space-y-3 rounded-lg border border-surface-200 p-4 dark:border-surface-800">
        <Skeleton className="w-full" />
        <Skeleton className="w-5/6" />
        <Skeleton className="w-4/5" />
        <Skeleton className="w-full" />
      </div>
    </SkeletonGroup>
  );
}
