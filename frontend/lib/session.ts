// the access token lives in localStorage for API calls and in a plain cookie so
// the edge middleware can guard pages. The refresh token stays in an httpOnly
// cookie that only the API can read.
export function storeSession(accessToken: string): void {
  localStorage.setItem('token', accessToken);
  document.cookie = `token=${accessToken}; path=/; max-age=${60 * 60 * 24}; SameSite=Strict`;
}
