import { Suspense } from 'react';
import TicketsView from '@/components/tickets/TicketsView';
import { SkeletonRows } from '@/components/ui/Skeleton';

// the filters and the open ticket live in the address, which a page can only read inside a Suspense boundary
export default function TicketsPage() {
  return (
    <Suspense fallback={<div className="p-0"><SkeletonRows rows={6} label="Loading tickets" /></div>}>
      <TicketsView />
    </Suspense>
  );
}
