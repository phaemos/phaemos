import { PHASE_PRODUCTION_BUILD } from 'next/constants.js';

const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// a production build bakes the API's address into the browser bundle. With none set it would point every visitor's browser at
// http://localhost:8000 and over http the sign-in and every reading would cross the network in clear. So a production build
// stops unless the address is https. A local production build for testing can say it means it with ALLOW_INSECURE_API_URL=1.
export function checkApiUrl(value, phase, allow) {
  if (phase !== PHASE_PRODUCTION_BUILD || allow === '1') return;
  if (!value) {
    throw new Error('NEXT_PUBLIC_API_URL is not set. A production build needs the https address of the API. For a local test build set ALLOW_INSECURE_API_URL=1.');
  }
  if (!/^https:\/\//i.test(value)) {
    throw new Error(`NEXT_PUBLIC_API_URL is ${value}, which is not https. A production build needs the https address of the API. For a local test build set ALLOW_INSECURE_API_URL=1.`);
  }
}

/** @type {(phase: string) => import('next').NextConfig} */
const nextConfig = (phase) => {
  checkApiUrl(process.env.NEXT_PUBLIC_API_URL, phase, process.env.ALLOW_INSECURE_API_URL);
  return {
    output: 'standalone',
    // the framework's name is not for visitors to read
    poweredByHeader: false,
    env: {
      NEXT_PUBLIC_API_URL: apiUrl,
      // Vercel sets VERCEL=1 while it builds. Vercel Web Analytics only exists there: its script is served by Vercel, so anywhere else
      // /_vercel/insights/script.js is a 404 and every page logs two console errors. The layout mounts the package only when this is 1.
      NEXT_PUBLIC_ON_VERCEL: process.env.VERCEL ? '1' : '',
    },
    // a filtered changelog link in query form works without script: it lands on the static filter page
    async redirects() {
      return [
        {
          source: '/changelog',
          has: [{ type: 'query', key: 'type', value: '(?<type>added|changed|fixed|security|removed)' }],
          destination: '/changelog/filter/:type',
          permanent: false,
        },
      ];
    },
    async headers() {
      return [
        {
          source: '/(.*)',
          headers: [
            { key: 'X-Frame-Options',           value: 'DENY' },
            { key: 'X-Content-Type-Options',    value: 'nosniff' },
            { key: 'Referrer-Policy',            value: 'strict-origin-when-cross-origin' },
            { key: 'Permissions-Policy',         value: 'camera=(), microphone=(), geolocation=()' },
            {
              key: 'Strict-Transport-Security',
              value: 'max-age=63072000; includeSubDomains; preload',
            },
            // the Content-Security-Policy is set in proxy.ts, because the dashboard's needs a nonce made for each request;
            // nothing opens a window (the provider sign-in is a full-page redirect), so the page can be cut off from any other.
            { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
            { key: 'Cross-Origin-Resource-Policy', value: 'same-origin' },
          ],
        },
      ];
    },
  };
};

export default nextConfig;
