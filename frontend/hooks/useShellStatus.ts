'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { linkOf, type DeviceLike } from '@/lib/machineState';

// the fleet by how recently each node posted: online, late and offline
export interface ShellStatus {
  online: number;
  late: number;
  offline: number;
  total: number;
  activeAlerts: number;
}

export interface ShellUser {
  email: string;
  name: string | null;
  role: string;
}

interface HealthSummary {
  total_devices: number;
  online: number;
  offline: number;
  active_alerts: number;
  // machines by how recently their node posted. Absent from an older API.
  link_states?: { online?: number; late?: number; offline?: number };
}

interface Me {
  email: string;
  name: string | null;
  role: string;
}

// the app shell needs three facts on every page: who is signed in (for the Admin link and the user row),
// the fleet counts (for the top bar pill) and the active alert count (for the badge). They come from the
// calls the dashboard already makes, /auth/me and /fleet/summary, so no endpoint is added.
// the shell's read has stopped answering: since is when the last good answer arrived or null when there never was one. The
// figures from before are not to be shown as current while this is set.
export interface ShellStale {
  since: number | null;
}

// two missed reads in a row (or a first read that never answered after two tries) make the status stale. One good read clears it.
export const STALE_AFTER_FAILURES = 2;

export function useShellStatus(intervalMs = 15_000): { status: ShellStatus | null; user: ShellUser | null; stale: ShellStale | null } {
  const [status, setStatus] = useState<ShellStatus | null>(null);
  const [user, setUser] = useState<ShellUser | null>(null);
  const [stale, setStale] = useState<ShellStale | null>(null);

  useEffect(() => {
    let alive = true;
    // who is signed in decides the Admin link for the whole page, so a failed read is asked again (3 tries, 1 s then 2 s
    // apart) in place of being swallowed. A 401 is already retried once by the API client after a refresh.
    const loadMe = async (attempt = 0): Promise<void> => {
      try {
        const { data } = await api.get<Me>('/auth/me');
        if (alive) setUser({ email: data.email, name: data.name ?? null, role: data.role });
      } catch {
        if (alive && attempt < 2) setTimeout(() => void loadMe(attempt + 1), 1000 * (attempt + 1));
      }
    };
    void loadMe();

    // polite polling, as in useApiResource: a tick is skipped while the last read is still out and while the tab is hidden;
    // coming back to the tab reads at once.
    let inFlight = false;
    let failures = 0;
    let lastOk: number | null = null;
    const load = () => {
      if (inFlight) return;
      inFlight = true;
      return api
        .get<HealthSummary>('/fleet/summary', { timeout: 20_000 })
        .then(async ({ data }) => {
          let links = data.link_states;
          // an older API has no link counts and its "online" can be hours old, so count the machines by their last post
          if (!links) {
            try {
              const list = await api.get<DeviceLike[]>('/devices', { params: { limit: 200 } });
              const counted = { online: 0, late: 0, offline: 0 };
              for (const d of list.data) counted[linkOf(d)] += 1;
              links = counted;
            } catch {
              links = undefined;
            }
          }
          failures = 0;
          lastOk = Date.now();
          if (alive) setStale(null);
          if (alive) setStatus({
              online: links?.online ?? data.online,
              late: links?.late ?? 0,
              offline: links?.offline ?? data.offline,
              total: data.total_devices,
              activeAlerts: data.active_alerts,
            });
        })
        .catch(() => {
          failures += 1;
          if (alive && failures >= STALE_AFTER_FAILURES) setStale({ since: lastOk });
        })
        .finally(() => {
          inFlight = false;
        });
    };
    load();
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === 'visible') load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive = false;
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [intervalMs]);

  return { status, user, stale };
}
