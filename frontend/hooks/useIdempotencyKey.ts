'use client';

import { useCallback, useRef } from 'react';
import { newIdempotencyKey } from '@/lib/idempotency';

// one Idempotency-Key for each submission of a create form. The key is made the first time it is asked for after the form opens (or after
// the last create worked) and the same key goes with every retry of that submission, so a double click or a retry after a time-out cannot
// make two. The API answers a repeat with a different body 422 `idempotency_key_reused`, so a key belongs to one body: `keyFor` is given
// a text that stands for what is being made (never the password) and starts a new key when that text changes.
export function useIdempotencyKey() {
  const current = useRef<{ key: string; what: string } | null>(null);
  const keyFor = useCallback((what: string) => {
    if (!current.current || current.current.what !== what) current.current = { key: newIdempotencyKey(), what };
    return current.current.key;
  }, []);
  // call when the form opens and after a create worked
  const renew = useCallback(() => {
    current.current = null;
  }, []);
  return { keyFor, renew };
}
