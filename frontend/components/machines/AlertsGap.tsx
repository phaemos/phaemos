'use client';

import { createContext, useContext, type ReactNode } from 'react';

// why the page cannot trust "no alerts", in words or null when the alerts read is complete. A machine badge reads it, so
// every badge on a page says Unknown while the alerts are missing and none of them says Healthy by default. Pages that
// do not provide it (the public sample) get null.
const AlertsGapContext = createContext<string | null>(null);

export function AlertsGapProvider({ gap, children }: { gap: string | null; children: ReactNode }) {
  return <AlertsGapContext.Provider value={gap}>{children}</AlertsGapContext.Provider>;
}

export function useAlertsGap(): string | null {
  return useContext(AlertsGapContext);
}
