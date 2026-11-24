import axios from 'axios';
import { isLeaving, refreshAccessToken, tokenIsFresh } from './session';
import { carriesProof } from './proof';
import { errorInfo, shouldRenew } from './apiCode';
import { nextFor } from './publicPaths';
import { hasSignedInMarker } from './signedIn';
import { warnDeprecated } from './deprecation';
import type { Telemetry, TelemetryBucket } from '../types/index';

const api = axios.create({
  baseURL: `${process.env.NEXT_PUBLIC_API_URL}/api/v1`,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

// attach JWT token from localStorage on every request
api.interceptors.request.use(async (config) => {
  if (typeof window !== 'undefined') {
    let token = localStorage.getItem('token');
    // a request that carries a proof is never retried (a wrong proof counts toward the lock), so a token that has run out is
    // renewed before it is sent and not after it fails
    if (token && !tokenIsFresh(token, 5) && carriesProof(config.data, config.url ?? '', config.params)) {
      token = (await refreshAccessToken(token)) ?? token;
    }
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// renew the access token when a 401 comes back. The refresh token lives in an httpOnly cookie that the browser sends by
// itself. Every request that meets a 401 awaits the one shared refresh (lib/session.ts keeps it to one per browser profile)
// and is then retried once with the new token. A refresh the API refuses ends the session and leaves for the sign-in page.
const AUTH_PATHS = ['/auth/login', '/auth/refresh', '/auth/logout', '/auth/2fa/verify'];

api.interceptors.response.use(
  (response) => {
    // development only: a call to a route that has moved says so in the console
    warnDeprecated(response.config.method, (response.config.url ?? '').split('?')[0], response.headers as never, process.env.NODE_ENV === 'development');
    return response;
  },
  async (error) => {
    const original = error.config;
    const url: string = original?.url ?? '';
    // a 401 is a token that has run out unless its code says otherwise (a wrong sign-in, a two-step challenge that is gone, no refresh
    // cookie, a device key) and then it is renewed and the request sent again. A request that carries a proof is the exception and is
    // never sent twice. The decision is made from the error's code and never from its sentence.
    const proof = carriesProof(original?.data, url, original?.params);
    if (error.response?.status === 401 && original && !original._retry && !proof && shouldRenew(errorInfo(error).code) && !AUTH_PATHS.some((p) => url.includes(p))) {
      original._retry = true;
      const failed = typeof original.headers?.Authorization === 'string' ? original.headers.Authorization.replace(/^Bearer /, '') : null;
      const token = await refreshAccessToken(failed);
      if (token) {
        original.headers.Authorization = `Bearer ${token}`;
        return api(original);
      }
      // the session is gone when the API refused the refresh: forgetSession has then removed the token and the cookie, so the
      // sign-in page does not send this person straight back to the dashboard. A refresh that failed for another reason
      // (offline, a server error) leaves the cookie. Going to sign-in would then loop, so the error is shown instead.
      const signedOut = !hasSignedInMarker(document.cookie);
      if (signedOut && !isLeaving() && window.location.pathname !== '/login') {
        // the page they were on goes along as `next`, so signing in again brings them back to it (checked again on the way in)
        const next = nextFor(window.location.pathname, window.location.search);
        const login = new URL('/login', window.location.origin);
        if (next) login.searchParams.set('next', next);
        window.location.replace(login.href);
      }
    }
    return Promise.reject(error);
  },
);

export interface TelemetryQuery {
  limit?: number;
  fromTs?: string;
  toTs?: string;
  nodeType?: string;
  // seconds. When set the API returns one averaged row per bucket (TelemetryBucket) and ignores limit
  bucket?: number | null;
}

// GET /telemetry/{id}, shared by the chart and the polling hook so both build the query the same way
export async function getTelemetry<T extends Telemetry | TelemetryBucket = Telemetry>(deviceId: string, q: TelemetryQuery = {}): Promise<T[]> {
  const params: Record<string, string | number> = {};
  if (q.bucket) params.bucket = q.bucket;
  else if (q.limit !== undefined) params.limit = q.limit;
  if (q.fromTs) params.from = q.fromTs;
  if (q.toTs) params.to = q.toTs;
  if (q.nodeType) params.node_type = q.nodeType;
  const res = await api.get<T[]>(`/telemetry/${deviceId}`, { params });
  return res.data;
}

export default api;
