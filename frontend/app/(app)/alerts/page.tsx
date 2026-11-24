import { Suspense } from 'react';
import AlertsView from '@/components/alerts/AlertsView';
import { SkeletonRows } from '@/components/ui/Skeleton';

// the filters live in the address, which a page can only read inside a Suspense boundary
export default function AlertsPage() {
  return (
    <Suspense fallback={<div className="p-0"><SkeletonRows rows={6} label="Loading alerts" /></div>}>
      <AlertsView />
    </Suspense>
  );
}
