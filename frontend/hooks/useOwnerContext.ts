'use client';

import { useMemo } from 'react';
import { useApiResource } from '@/hooks/useApiResource';
import type { OwnerContext } from '@/lib/machineList';
import type { User } from '@/types';

export interface OwnerLookup extends OwnerContext {
  // the people an admin may pick from. Empty for other roles
  users: User[];
  // false while the lookup that names owners is still loading
  ready: boolean;
}

// the API returns a machine's owner as an id and only admins may list people (GET /users). An admin gets every
// name. Anyone else can name themselves from GET /auth/me. See ownerLabel for what the page prints for the rest.
export function useOwnerContext(isAdmin: boolean, signedIn: boolean): OwnerLookup {
  const users = useApiResource<User[]>('/users', { params: { limit: 200 }, what: 'The people list', enabled: isAdmin });
  const me = useApiResource<User>('/auth/me', { what: 'Your account', enabled: signedIn && !isAdmin });
  return useMemo(() => {
    const list = users.data ?? [];
    return {
      names: Object.fromEntries(list.map((u) => [u.id, u.name ?? u.email])),
      me: me.data,
      users: list,
      ready: isAdmin ? !users.loading : !me.loading,
    };
  }, [users.data, users.loading, me.data, me.loading, isAdmin]);
}
