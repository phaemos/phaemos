import type { ReactNode } from 'react';
import SiteHeading from '@/components/ui/SiteHeading';

interface Props {
  title: string;
  lead?: ReactNode;
  children: ReactNode;
}

// the frame of every content page: the same container as the site header and footer, the shared heading, then the
// content on that left edge. Reading text sets its own 72 character column inside it (see Prose).
export default function PageShell({ title, lead, children }: Props) {
  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 md:py-16">
      <SiteHeading title={title} lead={lead} />
      <div className="mt-10 md:mt-12">{children}</div>
    </div>
  );
}
