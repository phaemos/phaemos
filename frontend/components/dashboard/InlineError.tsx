'use client';

import ErrorNotice from '@/components/ui/ErrorNotice';

interface Props {
  // what failed, in words a user can act on: "Alerts could not be loaded."
  message: string;
  onRetry: () => void;
}

// a failed request must never read as an empty list, so each container shows this beside or in place of its content;
// it is now the shared ErrorNotice under its earlier name.
export default function InlineError({ message, onRetry }: Props) {
  return <ErrorNotice message={message} onRetry={onRetry} />;
}
