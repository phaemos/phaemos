// the access token lives in localStorage for API calls. A plain cookie holds only a signed_in marker so the proxy can guard pages. The refresh
// token stays in an httpOnly cookie that only the API can read. Everything that starts, renews or ends a session is here,
// so there is one way each of them happens.

import { serverNow } from './serverClock';
import { canLeaveFor } from './leave';
import { SPLIT } from './links';
import { LEGACY_TOKEN_COOKIE, SIGNED_IN_COOKIE, SIGNED_IN_MAX_AGE } from './signedIn';

const API = `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/api/v1/auth`;
const CHANNEL = 'phaemos-session';

export function storeSession(accessToken: string): void {
  localStorage.setItem('token', accessToken);
  // secure whenever the page is served over https, which is everywhere except local development. The cookie lasts
  // 24 hours although the token in it lasts 15 minutes: the proxy only checks that the cookie exists and the API
  // client replaces the token from the 7 day refresh cookie, so a shorter life would sign people out of pages their
  // refresh cookie still allows. The cookies page says the same.
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `${SIGNED_IN_COOKIE}=1; path=/; max-age=${SIGNED_IN_MAX_AGE}; SameSite=Strict${secure}`;
  // the old cookie held the token itself: any copy is expired
  document.cookie = `${LEGACY_TOKEN_COOKIE}=; path=/; max-age=0; SameSite=Strict`;
}

// removes the token from both places it lives. It touches nothing on the server.
export function forgetSession(): void {
  try {
    localStorage.removeItem('token');
  } catch {
    // storage can be blocked so the cookie is removed whatever happens
  }
  document.cookie = `${SIGNED_IN_COOKIE}=; path=/; max-age=0; SameSite=Strict`;
  document.cookie = `${LEGACY_TOKEN_COOKIE}=; path=/; max-age=0; SameSite=Strict`;
}

function tell(message: string): void {
  try {
    const channel = new BroadcastChannel(CHANNEL);
    channel.postMessage(message);
    channel.close();
  } catch {
    // an old browser has no channel: other tabs find out at their next request
  }
}

// ends the session: asks the API to revoke it and waits for the answer, then clears this browser. The call needs only the
// refresh cookie, so an expired access token never stops someone signing out. A failed call must not trap them in a
// session they asked to leave. Other tabs are told, so they leave too.
// true from the moment this browser starts to leave (sign-out or a deleted account). A read still in flight then meets a 401 it
// caused itself and lib/api.ts must not send the person to the sign-in page on top of where they are going.
let leaving = false;
export function isLeaving(): boolean {
  return leaving;
}

// gives true when the API confirmed the sign-out. When it could not be reached the session may still be open, here and
// elsewhere, so this browser is left as it is and false comes back, unless `anyway` says to leave this browser regardless (a
// deleted account has no session left to end).
export async function clearSession(options: { anyway?: boolean } = {}): Promise<boolean> {
  leaving = true;
  let reached = false;
  try {
    // a call that does not answer in 8 seconds is given up, so Sign out never waits for ever on a slow or dead API
    const res = await fetch(`${API}/logout`, { method: 'POST', credentials: 'include', signal: AbortSignal.timeout(8000) });
    reached = res.ok;
  } catch {
    // offline, refused or timed out
  }
  if (!reached && !options.anyway) {
    leaving = false;
    return false;
  }
  forgetSession();
  tell('signed-out');
  return reached;
}

// the "exp" claim in seconds. Null when there is none. A token is only read here to decide whether to ask for a new one: the API
// decides whether it is valid.
export function tokenExpiry(token: string | null | undefined): number | null {
  const part = token?.split('.')[1];
  if (!part) return null;
  try {
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
    const exp = JSON.parse(atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, '='))).exp;
    return typeof exp === 'number' ? exp : null;
  } catch {
    return null;
  }
}

// true when the token has at least `skewSeconds` left
// measured on the server's clock: the token's expiry was stamped by the API and a browser clock that is minutes out would
// otherwise call a dead token fresh (or a fresh one dead)
export function tokenIsFresh(token: string | null | undefined, skewSeconds = 30, nowMs: number = serverNow()): boolean {
  const exp = tokenExpiry(token);
  return exp !== null && exp * 1000 - nowMs > skewSeconds * 1000;
}

let inFlight: Promise<string | null> | null = null;

async function exchange(failedToken: string | null, force: boolean): Promise<string | null> {
  // a refresh token works once and a second use is read as theft, so only one refresh may run in the whole browser. Another
  // tab may have finished one while this tab waited for the lock: its token is already stored.
  const stored = localStorage.getItem('token');
  if (!force && stored && stored !== failedToken && tokenIsFresh(stored)) return stored;
  try {
    const res = await fetch(`${API}/refresh`, { method: 'POST', credentials: 'include' });
    if (res.status === 401) {
      // the session is over, whether it expired, was ended elsewhere or was replayed. Leave cleanly and do not call logout.
      forgetSession();
      tell('signed-out');
      return null;
    }
    if (!res.ok) return null;
    const { access_token } = (await res.json()) as { access_token: string };
    storeSession(access_token);
    return access_token;
  } catch {
    return null;
  }
}

// one refresh at a time per browser profile. Within a page every caller shares one promise. Across tabs a Web Lock makes the
// others wait and then take the token the first one stored. Pass the token that was refused so a waiting tab can tell a
// newer one from the one that failed.
// `force` skips the shortcut of taking a token another tab stored: the sign-in page uses it after a provider sign-in, when the
// refresh cookie is new and any token already stored belongs to whoever was signed in before.
export function refreshAccessToken(failedToken: string | null = null, force = false): Promise<string | null> {
  if (inFlight) return inFlight;
  const run = async (): Promise<string | null> => await exchange(failedToken, force);
  const started: Promise<string | null> =
    typeof navigator !== 'undefined' && navigator.locks
      ? (navigator.locks.request('phaemos-refresh', run) as unknown as Promise<string | null>)
      : run();
  const shared = started.finally(() => {
    inFlight = null;
  });
  inFlight = shared;
  return shared;
}

// every tab leaves when one signs out or loses its session
export function listenForSignOut(onSignOut: () => void): () => void {
  try {
    const channel = new BroadcastChannel(CHANNEL);
    channel.onmessage = (e) => {
      if (e.data === 'signed-out') onSignOut();
    };
    return () => channel.close();
  } catch {
    return () => undefined;
  }
}

// where to go after a provider sign-in that was started from a page other than the sign-in page (proving it is you again
// before deleting an account or turning on two-step sign-in). The provider sends the person back to /login, which cannot
// carry a page of its own, so the page is held in sessionStorage until the return and then removed. The tab holds it and it
// is never sent anywhere.
const RETURN_KEY = 'return_to';

export function rememberReturn(path: string): void {
  try {
    sessionStorage.setItem(RETURN_KEY, path);
  } catch {
    // storage blocked: the person lands on the overview and opens the page again
  }
}

export function takeReturn(): string | null {
  try {
    const value = sessionStorage.getItem(RETURN_KEY);
    sessionStorage.removeItem(RETURN_KEY);
    return value;
  } catch {
    return null;
  }
}

// sends the person to their provider to prove it is them again and back to `returnTo` (a dashboard path)
export function signInWithProviderAgain(provider: string, returnTo: string): void {
  rememberReturn(returnTo);
  // the address is on the API's origin, not a page of this app, so the rule against assign() for internal pages does not apply
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`${API}/${encodeURIComponent(provider)}`);
}

// sends the browser to an address the API gave (the provider's page), but only when lib/leave.ts allows it: the provider's own host
// for a provider the API lists or one of this site's two addresses. Anything else is refused with an error and nothing opens.
export const NOT_RECOGNISED = 'The provider address was not recognised';

export function leaveFor(address: string, providers: readonly string[]): void {
  if (!canLeaveFor(address, providers, [SPLIT.siteOrigin, SPLIT.appOrigin, window.location.origin].filter(Boolean))) {
    throw new Error(NOT_RECOGNISED);
  }
  window.location.assign(address);
}
