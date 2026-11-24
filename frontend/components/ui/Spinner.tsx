'use client';

import { useSpinnerVisible } from '@/hooks/useSpinnerVisible';
import { SpinnerIcon } from './icons';

// the one spinner. It only means "still working" and shows after 200 ms, so a quick load never flashes one;
// standalone it announces itself with `label`. Inside a button pass `decorative` because the button's aria-busy
// already says the work is under way.
export default function Spinner({ label = 'Loading', size = 16, decorative = false }: { label?: string; size?: number; decorative?: boolean }) {
  // a mounted spinner is active. A button that stays mounted passes its own state through useSpinnerVisible instead.
  const visible = useSpinnerVisible(true);
  if (decorative) return <SpinnerIcon size={size} />;
  return (
    <span role="status" className="inline-flex min-h-[1.5rem] items-center gap-2 text-base text-surface-700 dark:text-surface-300">
      {visible && (
        <>
          <SpinnerIcon size={size} />
          <span>{label}</span>
        </>
      )}
    </span>
  );
}
