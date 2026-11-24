// a request that carries a proof (a password or a two-step code) must never be sent twice. Wrong proofs count toward the account
// lock, so a client that renewed the access token and retried on a 401 would count one wrong guess twice. This says which
// requests those are. lib/api.ts renews the token before sending one that carries a proof and never retries it after a 401.
const PROOF_FIELDS = ['password', 'current_password', 'old_password', 'new_password', 'code'];

export function carriesProof(data: unknown, url = '', params: unknown = undefined): boolean {
  let body: unknown = data;
  if (typeof data === 'string') {
    try {
      body = JSON.parse(data);
    } catch {
      body = null;
    }
  }
  if (body && typeof body === 'object' && PROOF_FIELDS.some((f) => f in (body as Record<string, unknown>))) return true;
  // an older form puts the code in the query string
  if (/[?&]code=/.test(url)) return true;
  return Boolean(params && typeof params === 'object' && 'code' in (params as Record<string, unknown>));
}
