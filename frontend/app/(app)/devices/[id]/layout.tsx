import { notFound } from 'next/navigation';
import { isUuid } from '@/lib/uuid';

// a machine's address ends in its id, which is a UUID. Anything else is not a machine, so it gets the 404 page at once and never
// reaches a request to the API.
export default async function MachineLayout({ children, params }: { children: React.ReactNode; params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return children;
}
