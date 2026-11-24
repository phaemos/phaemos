// a response from a route that has moved carries `Deprecation` and `Sunset` headers (and a `Link` to the new path). In development this
// says so in the console, once for each route, so the next person to add a call to an old path sees it. Nothing is logged in production;
// no import, so the tests can load it.

type HeaderBag = { get?: (name: string) => unknown } | Record<string, unknown> | undefined | null;

function header(headers: HeaderBag, name: string): string | null {
  if (!headers) return null;
  const viaGet = typeof (headers as { get?: unknown }).get === 'function' ? (headers as { get: (n: string) => unknown }).get(name) : undefined;
  const raw = viaGet ?? (headers as Record<string, unknown>)[name.toLowerCase()];
  return typeof raw === 'string' && raw ? raw : null;
}

// the sentence to log or null when the route is not deprecated
export function deprecationWarning(method: string | undefined, path: string, headers: HeaderBag): string | null {
  const dep = header(headers, 'deprecation');
  if (!dep || dep === 'false') return null;
  const sunset = header(headers, 'sunset');
  const link = header(headers, 'link');
  const successor = link?.match(/<([^>]+)>\s*;\s*rel="?successor-version"?/i)?.[1];
  const route = `${(method ?? 'get').toUpperCase()} ${path}`;
  return `${route} is a deprecated API path${sunset ? ` and stops working on ${sunset}` : ''}.${successor ? ` Call ${successor} instead.` : ' Check docs/api-reference.md for its new path.'}`;
}

// kept on the global object, so two copies of this module in a bundle still say it once
const G = globalThis as { __phaemosDeprecated?: Set<string> };
const warned = (G.__phaemosDeprecated ??= new Set<string>());

export function warnDeprecated(method: string | undefined, path: string, headers: HeaderBag, isDevelopment: boolean, log: (m: string) => void = (m) => console.warn(m)): boolean {
  if (!isDevelopment) return false;
  const text = deprecationWarning(method, path, headers);
  if (!text) return false;
  const key = `${method ?? 'get'} ${path}`;
  if (warned.has(key)) return false;
  warned.add(key);
  log(text);
  return true;
}
