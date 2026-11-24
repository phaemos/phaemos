'use client';

import { useSyncExternalStore } from 'react';
import { hasSignedInMarker } from '@/lib/signedIn';

// the proxy guards pages with the plain `signed_in` marker cookie, so the same cookie tells the public
// site whether to offer "Open dashboard". The server render assumes signed out and the client corrects it.
function read(): boolean {
  return hasSignedInMarker(document.cookie);
}

// a cookie change fires no event, so re-read when the tab regains focus or storage changes
function subscribe(notify: () => void): () => void {
  window.addEventListener('focus', notify);
  window.addEventListener('storage', notify);
  return () => {
    window.removeEventListener('focus', notify);
    window.removeEventListener('storage', notify);
  };
}

export function useSignedIn(): boolean {
  return useSyncExternalStore(subscribe, read, () => false);
}
