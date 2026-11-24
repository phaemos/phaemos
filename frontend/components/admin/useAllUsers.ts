'use client';

import { useCallback, useEffect, useState } from 'react';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import type { User } from '@/types';

// the API lists users 200 at a time (GET /users, admins only), so this reads page after page until a page comes back short;
// a failure keeps whatever was read and says so, so a name that is missing is explained and not shown as an id without a word.
const PAGE = 200;
const MAX_PAGES = 25;

export function useAllUsers(): { users: User[]; error: string | null; retry: () => void } {
  const [state, setState] = useState<{ users: User[]; error: string | null }>({ users: [], error: null });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    (async () => {
      const all: User[] = [];
      try {
        for (let page = 0; page < MAX_PAGES; page += 1) {
          const res = await api.get<User[]>('/users', { params: { limit: PAGE, skip: page * PAGE } });
          all.push(...res.data);
          if (res.data.length < PAGE) break;
        }
        if (alive) setState({ users: all, error: null });
      } catch (err) {
        if (alive) setState({ users: all, error: describeApiError(err, 'The users') });
      }
    })();
    return () => {
      alive = false;
    };
  }, [attempt]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return { users: state.users, error: state.error, retry };
}
