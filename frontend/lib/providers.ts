// the sign-in providers the page can show. GET /auth/providers answers { providers: ["google", ...] } with only the ones
// the API has configured. While that is loading or if it fails (including a 404 from an API that predates the route),
// no provider button is shown, so a button that cannot work is never offered.

export const PROVIDER_LABELS: Record<string, string> = {
  google: 'Google',
  github: 'GitHub',
  microsoft: 'Microsoft',
};

// the known providers in a fixed order, from whatever the API sent. Anything unexpected gives an empty list.
export function parseProviders(body: unknown): string[] {
  const list = (body as { providers?: unknown } | null)?.providers;
  if (!Array.isArray(list)) return [];
  const wanted = new Set(list.filter((p): p is string => typeof p === 'string'));
  return Object.keys(PROVIDER_LABELS).filter((p) => wanted.has(p));
}
