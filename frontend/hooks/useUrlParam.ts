'use client';

import { useCallback } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

// one value kept in the address, so a view can be linked and survives a reload. An unknown or missing value reads as the
// fallback and the fallback is never written, so the plain page keeps a plain address. The page that calls this sits inside a
// suspense boundary, as useSearchParams needs.
export function useUrlParam<T extends string>(name: string, fallback: T, allowed: readonly T[]): [T, (value: T) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const raw = params.get(name);
  const value = (allowed as readonly string[]).includes(raw ?? '') ? (raw as T) : fallback;
  const set = useCallback(
    (next: T) => {
      const q = new URLSearchParams(params.toString());
      if (next === fallback) q.delete(name);
      else q.set(name, next);
      const s = q.toString();
      router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
    },
    [fallback, name, params, pathname, router],
  );
  return [value, set];
}
