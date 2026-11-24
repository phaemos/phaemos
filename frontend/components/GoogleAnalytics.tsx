'use client';

import Script from 'next/script';
import { useSignedIn } from '@/hooks/useSignedIn';
import { SPLIT } from '@/lib/links';
import { useEffect, useRef, useSyncExternalStore } from 'react';
import {
  clearAnalyticsCookies,
  getServerConsent,
  readConsent,
  setAnalyticsDisabled,
  subscribeConsent,
} from '@/lib/consent';

// defer GA4 loading until consent is confirmed - loading unconditionally
// would fire before the cookie banner is dismissed and breach GDPR.
function storedToken(): boolean {
  try {
    return typeof window !== 'undefined' && Boolean(window.localStorage.getItem('token'));
  } catch {
    return false;
  }
}

export default function GoogleAnalytics() {
  const consent = useSyncExternalStore(subscribeConsent, readConsent, getServerConsent);
  const id = process.env.NEXT_PUBLIC_GA_ID;
  // with one address the site's pages and the dashboard's share an origin, so third-party script on a site page could read the access
  // token in localStorage. The tag is therefore never loaded while a token is held in this browser: a signed-in person is not counted.
  // (With two addresses the token lives on the dashboard's origin only and this never applies.)
  const signedInHere = useSignedIn() || storedToken();
  const accepted = consent === 'accepted' && (SPLIT.split || !signedInHere);

  // true once this page has rendered the tag. A page that never loaded it has
  // nothing to unload, which is also what stops the reload below from looping.
  const tagLoaded = useRef(false);

  useEffect(() => {
    if (!id) return;
    setAnalyticsDisabled(id, !accepted);
    if (accepted) {
      tagLoaded.current = true;
      return;
    }
    if (consent === 'declined') {
      // a visitor who has declined must not keep the cookies of an earlier accept
      clearAnalyticsCookies();
      // the disable switch above is only a backstop: Google documents it for
      // use before the tag loads. Reloading makes the tag simply absent.
      if (tagLoaded.current) {
        tagLoaded.current = false;
        window.location.reload();
      }
    }
  }, [id, accepted, consent]);

  if (!id || !accepted) return null;

  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`}
        strategy="afterInteractive"
      />
      <Script id="ga4-init" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          // cookie_domain none keeps the cookies on this address only, so they do not reach the dashboard or the other subdomains
          gtag('config', ${JSON.stringify(id)}, { cookie_domain: 'none' });
        `}
      </Script>
    </>
  );
}
