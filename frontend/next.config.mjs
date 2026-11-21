// the browser treats a ws: or wss: connection as a different origin from the http API,
// so the live telemetry socket needs its own connect-src entry built from the same value.
// Only the origin goes into the policy: a source with a path matches that exact path alone,
// which would block every request below it.
const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const apiOrigin = new URL(apiUrl).origin;
const wsOrigin = apiOrigin.replace(/^http/, 'ws');

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  env: {
    NEXT_PUBLIC_API_URL: apiUrl,
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
          {
            key: 'Content-Security-Policy',
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob:",
              `connect-src 'self' ${apiOrigin} ${wsOrigin}`,
              "font-src 'self'",
              "object-src 'none'",
              "frame-ancestors 'none'",
            ].join('; '),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
