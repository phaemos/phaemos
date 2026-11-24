'use client';

import { usePathname } from 'next/navigation';
import { useEffect } from 'react';
import { isSitePath } from '@/lib/publicPaths';
import { setAnalyticsDisabled } from '@/lib/consent';

// Google Analytics belongs to the public site pages and nothing else. The tag is mounted in the site layout, but once it has
// loaded it listens to the browser's history for page views, so a visitor who accepted and then follows a link into sign-in
// or the dashboard on the same address (the one-address setup) would still be counted. This sits in the root layout, outside
// every route group: when the path is not a site page it switches the tag off at once (Google's documented ga-disable switch,
// which the tag checks before every hit) and, if the tag had loaded, reloads the page so the tag is gone and not merely quiet;
// the reload happens on a path that never mounts the tag again, so it happens once.
export default function AnalyticsGuard() {
  const pathname = usePathname();
  const id = process.env.NEXT_PUBLIC_GA_ID;

  // the tag listens to the browser's history and a page view for the new address can be sent the moment the address changes;
  // so the off switch is set before the change is made, not after the page has rendered: this wraps pushState and replaceState
  // (the tag, which loads later, wraps this wrapper, so it only sees the change once the switch is already set) and listens for
  // popstate in the capture phase, ahead of any listener the tag adds. Nothing is sent for a path that is not a site page.
  useEffect(() => {
    if (!id) return;
    const off = (path: string) => {
      if (!isSitePath(path)) setAnalyticsDisabled(id, true);
    };
    const wrap = (original: History['pushState']): History['pushState'] =>
      function (this: History, state, title, url) {
        if (url !== undefined && url !== null) {
          try {
            off(new URL(String(url), window.location.href).pathname);
          } catch {
            // an address that cannot be read cannot be a site page either
            setAnalyticsDisabled(id, true);
          }
        }
        return original.call(this, state, title, url);
      };
    const push = window.history.pushState;
    const replace = window.history.replaceState;
    window.history.pushState = wrap(push);
    window.history.replaceState = wrap(replace);
    const onPop = () => off(window.location.pathname);
    window.addEventListener('popstate', onPop, true);
    return () => {
      window.history.pushState = push;
      window.history.replaceState = replace;
      window.removeEventListener('popstate', onPop, true);
    };
  }, [id]);

  useEffect(() => {
    if (!id || isSitePath(pathname)) return;
    setAnalyticsDisabled(id, true);
    const loaded = Boolean(document.querySelector('script[src*="googletagmanager.com/gtag/js"]')) || Boolean((window as unknown as { google_tag_manager?: unknown }).google_tag_manager);
    if (loaded) window.location.reload();
  }, [id, pathname]);

  return null;
}
