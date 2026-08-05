'use client';

import Script from 'next/script';
import { useEffect, useState } from 'react';

// I defer GA4 loading until consent is confirmed - loading unconditionally
// would fire before the cookie banner is dismissed and breach GDPR.
export default function GoogleAnalytics() {
  const [consented, setConsented] = useState(false);

  useEffect(() => {
    // Synchronizing with the external localStorage source, the documented
    // effect pattern (react.dev/learn/synchronizing-with-effects).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setConsented(localStorage.getItem('cookie_consent') === 'accepted');

    function onStorage(e: StorageEvent) {
      if (e.key === 'cookie_consent') {
        setConsented(e.newValue === 'accepted');
      }
    }
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const id = process.env.NEXT_PUBLIC_GA_ID;
  if (!id || !consented) return null;

  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${id}`}
        strategy="afterInteractive"
      />
      <Script id="ga4-init" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          gtag('config', '${id}', { anonymize_ip: true });
        `}
      </Script>
    </>
  );
}
