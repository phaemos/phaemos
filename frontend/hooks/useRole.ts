'use client';

import { useSyncExternalStore } from 'react';
import { canWrite, roleFromToken, type Role } from '@/lib/role';

// the signed-in role, read from the access token. useSyncExternalStore gives the server render and the first
// client render the same answer (no role) and then corrects it, so admin controls do not cause a hydration
// mismatch. It decides what to offer only: the API enforces the role.
function read(): Role | null {
  try {
    return roleFromToken(localStorage.getItem('token'));
  } catch {
    return null;
  }
}

function subscribe(notify: () => void): () => void {
  window.addEventListener('storage', notify);
  return () => window.removeEventListener('storage', notify);
}

export function useRole(): Role | null {
  return useSyncExternalStore(subscribe, read, () => null);
}

// false for a viewer and while the role is not known yet. See canWrite in lib/role.ts.
export function useCanWrite(): boolean {
  return canWrite(useRole());
}
