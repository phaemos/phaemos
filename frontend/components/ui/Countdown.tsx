'use client';

import { useEffect, useRef, useState } from 'react';
import { waitPhrase } from '@/lib/retryAfter';

interface Props {
  // how long to wait, in seconds, when the wait starts
  seconds: number;
  // changes with each new wait, so a second 429 restarts the count
  runKey: number;
  // what the wait is for, in a sentence start: "Too many sign-in attempts."
  lead: string;
  // called when the wait is over
  onDone: () => void;
}

// a wait the person can see running down and a screen reader hears about twice only: once when it starts ("... try again in 30 seconds")
// and once when it ends ("You can try again now"). The number that changes every second is hidden from assistive technology, because
// announcing each second would talk over everything else on the page. The form around it stays usable.
export default function Countdown({ seconds, runKey, lead, onDone }: Props) {
  const [left, setLeft] = useState(seconds);
  const [done, setDone] = useState(false);
  const doneRef = useRef(onDone);
  useEffect(() => { doneRef.current = onDone; }, [onDone]);

  useEffect(() => {
    // a new wait restarts the count: this is state following a prop that changed
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLeft(seconds);
    setDone(false);
    const end = Date.now() + seconds * 1000;
    const id = setInterval(() => {
      const remaining = Math.max(0, Math.ceil((end - Date.now()) / 1000));
      setLeft(remaining);
      if (remaining === 0) {
        clearInterval(id);
        setDone(true);
        doneRef.current();
      }
    }, 1000);
    return () => clearInterval(id);
  }, [seconds, runKey]);

  return (
    <div className="text-base text-surface-900 dark:text-surface-50">
      {/* the one announcement while it counts and a second when it ends. The sentence does not change in between. */}
      <p role="status">{done ? 'You can try again now.' : `${lead} Try again in ${waitPhrase(seconds)}.`}</p>
      {!done && (
        <p aria-hidden="true" className="tnum text-surface-700 dark:text-surface-300">
          {left} {left === 1 ? 'second' : 'seconds'} left
        </p>
      )}
    </div>
  );
}
