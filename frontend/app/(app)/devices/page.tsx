import { Suspense } from 'react';
import MachinesView from '@/components/machines/MachinesView';
import { SkeletonRows } from '@/components/ui/Skeleton';

// the search, filters and sort order live in the address, which a page can only read inside a Suspense boundary
export default function MachinesPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={6} label="Loading machines" />}>
      <MachinesView />
    </Suspense>
  );
}
