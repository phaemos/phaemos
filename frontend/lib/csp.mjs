// builds the Content-Security-Policy header value. Kept as a plain function with no
// imports so next.config.mjs can load it and the unit tests can call it directly.
//
// vendor sources follow each vendor's own CSP guide:
// - Cloudflare Turnstile: script-src and frame-src for https://challenges.cloudflare.com
//   (developers.cloudflare.com/turnstile/reference/content-security-policy)
// - Google tag (GA4): script, img and connect sources
//   (developers.google.com/tag-platform/security/guides/csp)
// a vendor is only added when its public env value is set, so a deployment that
// does not use it keeps the tighter policy.
//
// 'unsafe-eval' is there for the development server only: React's refresh and the dev overlay rebuild functions from strings
// and fail without it. The production bundle needs it nowhere. The app's own dependencies (recharts, d3, axios, the markdown
// renderer, the Turnstile and analytics wrappers) hold no eval or new Function call. The third-party scripts load from
// their own origins. Production leaves it out. This is one layer and not the whole defence: while 'unsafe-inline' stays in
// script-src an injected inline script still runs and can read the access token, which is in localStorage.
//
// two policies. The public site's pages are static and cached, so they cannot carry a nonce made for each request and keep
// 'unsafe-inline' (they hold no credential: the access token is only ever on the dashboard's pages). The dashboard, the sign-in
// page and the invitation page are rendered for each request and get buildNonceCsp: no inline script runs unless it carries that
// request's nonce and no script is allowed by address. proxy.ts picks the policy.

const TURNSTILE = 'https://challenges.cloudflare.com';
const GTM = 'https://www.googletagmanager.com';
const GA_COLLECT = 'https://*.google-analytics.com';
// a wildcard host does not match the bare domain, so both are listed
const GA_REGION = ['https://*.analytics.google.com', 'https://analytics.google.com'];

/**
 * @param {{ apiUrl?: string, turnstileSiteKey?: string, gaId?: string, development?: boolean }} [options]
 * @returns {string}
 */
export function buildCsp({ apiUrl, turnstileSiteKey, gaId, development = false } = {}) {
  // the browser treats a ws: or wss: connection as a different origin from the http API,
  // so the live telemetry socket needs its own connect-src entry built from the same value;
  // only the origin goes into the policy: a source with a path matches that exact path alone,
  // which would block every request below it.
  const apiOrigin = new URL(apiUrl || 'http://localhost:8000').origin;
  const wsOrigin = apiOrigin.replace(/^http/, 'ws');

  const turnstile = Boolean(turnstileSiteKey);
  const analytics = Boolean(gaId);

  const scriptSrc = ["'self'", "'unsafe-inline'"];
  if (development) scriptSrc.push("'unsafe-eval'");
  const imgSrc = ["'self'", 'data:', 'blob:'];
  const connectSrc = ["'self'", apiOrigin, wsOrigin];
  const frameSrc = [];

  if (turnstile) {
    scriptSrc.push(TURNSTILE);
    frameSrc.push(TURNSTILE);
  }
  if (analytics) {
    scriptSrc.push(GTM);
    imgSrc.push(GTM, GA_COLLECT);
    connectSrc.push(GTM, GA_COLLECT, ...GA_REGION);
  }

  const directives = [
    "default-src 'self'",
    `script-src ${scriptSrc.join(' ')}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src ${imgSrc.join(' ')}`,
    `connect-src ${connectSrc.join(' ')}`,
    "font-src 'self'",
    "object-src 'none'",
    // a stray <base> tag cannot redirect every relative address and a form can only post back to this site
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  // without frame-src the policy falls back to default-src, which blocks the widget frame
  if (frameSrc.length) directives.push(`frame-src ${frameSrc.join(' ')}`);
  return directives.join('; ');
}

/**
 * The policy for the dashboard, the sign-in page and the invitation page: no inline script is allowed, except scripts that carry the
 * request's own nonce and scripts those load ('strict-dynamic'). An injected inline script has no nonce and does not run. The host
 * allowances of the site policy (Turnstile, the analytics tag) are not here because these pages load neither. Style stays open to
 * inline style attributes, which React and the chart library write, because a style cannot read the token.
 * @param {{ nonce: string, apiUrl?: string, development?: boolean, scriptHashes?: string[] }} options
 * @returns {string}
 */
export function buildNonceCsp({ nonce, apiUrl, development = false, scriptHashes = [] }) {
  const apiOrigin = new URL(apiUrl || 'http://localhost:8000').origin;
  const wsOrigin = apiOrigin.replace(/^http/, 'ws');
  const scriptSrc = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", ...scriptHashes.map((h) => `'${h}'`)];
  if (development) scriptSrc.push("'unsafe-eval'");
  return [
    "default-src 'self'",
    `script-src ${scriptSrc.join(' ')}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    `connect-src 'self' ${apiOrigin} ${wsOrigin}`,
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join('; ');
}
