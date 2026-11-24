// where the browser may be sent to on the strength of an address the API gave (the page of a provider's sign-in). The address is
// data from a response, so it is checked against a short fixed list and not trusted: an address the API was tricked into sending or one
// a script injected, must not take the person to a look-alike site. Allowed: the provider's own host for a provider the API lists and
// the two addresses this site is configured with. Anything else is refused.
const PROVIDER_HOSTS: ReadonlyMap<string, readonly string[]> = new Map([
  ['google', ['accounts.google.com']],
  ['github', ['github.com']],
  ['microsoft', ['login.microsoftonline.com']],
]);

export function canLeaveFor(address: string, providers: readonly string[], ownOrigins: readonly string[]): boolean {
  let url: URL;
  try {
    url = new URL(address);
  } catch {
    return false;
  }
  // an address with a name and password in it is how look-alike addresses are written
  if (url.username || url.password) return false;
  if (ownOrigins.includes(url.origin)) return true;
  if (url.protocol !== 'https:') return false;
  return providers.some((p) => PROVIDER_HOSTS.get(p)?.includes(url.hostname) === true);
}
