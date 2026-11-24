'use client';

import { useEffect, useRef, useState } from 'react';

// a spinner that waits before it shows and stays once it does, so a fast request never flashes one and a slow one
// never blinks. It shows after `delay` ms of work and hides no sooner than `min` ms after it appeared.
export function useSpinnerVisible(active: boolean, delay = 200, min = 300): boolean {
  const [visible, setVisible] = useState(false);
  const shownAt = useRef(0);

  useEffect(() => {
    if (active) {
      const t = setTimeout(() => {
        shownAt.current = Date.now();
        setVisible(true);
      }, delay);
      return () => clearTimeout(t);
    }
    // not active: hide at once if it never showed or after the minimum time if it did
    const left = Math.max(0, min - (Date.now() - shownAt.current));
    const t = setTimeout(() => setVisible(false), left);
    return () => clearTimeout(t);
  }, [active, delay, min]);

  return visible;
}
