// every error the API sends has one shape: { code, detail, request_id } (docs/api-conventions.md). A page decides what to do from `code`,
// which does not change and shows `detail` as the sentence, which may be reworded at any time. `request_id` is shown in small text on a
// failed action so that a person can quote it. An answer with no code (a network failure, an older API) has only a status.

export interface ErrorInfo {
  status?: number;
  code?: string;
  detail?: string;
  requestId?: string;
}

interface Shape {
  response?: { status?: number; data?: unknown };
}

export function errorInfo(err: unknown): ErrorInfo {
  const res = (err as Shape | null)?.response;
  const data = res?.data;
  const body = data && typeof data === 'object' ? (data as Record<string, unknown>) : {};
  const text = (v: unknown) => (typeof v === 'string' && v.trim() ? v : undefined);
  return { status: res?.status, code: text(body.code), detail: text(body.detail), requestId: text(body.request_id) };
}

export const requestIdOf = (err: unknown): string | undefined => errorInfo(err).requestId;

// which field of a proof form an error is about. The proof codes are:
//   proof_required         a password is needed and was not sent        -> the password field
//   code_required          a two-step code is needed and was not sent   -> the code field
//   two_step_code_wrong    the two-step code is wrong                    -> the code field
//   password_wrong         the current password given is wrong           -> the password field
//   proof_wrong            the password or the code is wrong             -> both fields (the API does not say which)
//   provider_proof_required sign in through the provider again           -> the dialog, not a field
export type ProofField = 'password' | 'code' | 'both' | 'dialog';

export function proofField(code: string | undefined, asks: { password: boolean; code: boolean }): ProofField | null {
  switch (code) {
    case 'proof_required':
    case 'password_wrong':
    case 'no_password':
      return 'password';
    case 'code_required':
    case 'two_step_code_wrong':
      return 'code';
    case 'proof_wrong':
      return asks.password && asks.code ? 'both' : asks.code ? 'code' : 'password';
    case 'provider_proof_required':
      return 'dialog';
    default:
      return null;
  }
}

// a 401 that is only a token that has run out is renewed and the request is sent again. These 401s are not: they mean something else
// and renewing would change nothing or do harm (a wrong sign-in, a two-step challenge that is gone, no refresh cookie, a device key).
const NO_RENEW = new Set(['invalid_credentials', 'sign_in_again', 'refresh_missing', 'device_key_invalid']);

export function shouldRenew(code: string | undefined): boolean {
  return !(code && NO_RENEW.has(code));
}

// 429 codes: a slowdown on sign-in or proofs, a rate limit or a limit on one kind of action
export function isRateLimit(info: ErrorInfo): boolean {
  return info.status === 429;
}
