// the dashboard's own cookie says only that someone is signed in. It holds no credential: the access token stays in memory and
// localStorage and the refresh token is an httpOnly cookie that only the API reads. The proxy needs to know whether to show a page
// or send the visitor to sign-in and a marker is enough for that. The API checks the real token on every request, so a person who
// forges the marker sees an empty page shell and nothing else.
export const SIGNED_IN_COOKIE = 'signed_in';
export const SIGNED_IN_MAX_AGE = 60 * 60 * 24;

// the old cookie carried the access token itself. It is still expired on every sign-in and sign-out so that no copy lingers.
export const LEGACY_TOKEN_COOKIE = 'token';

export function hasSignedInMarker(cookieString: string): boolean {
  return new RegExp(`(?:^|; )${SIGNED_IN_COOKIE}=1(?:;|$)`).test(cookieString);
}
