// a create can be sent twice (a double click, a retry after a time-out). With an Idempotency-Key header a repeat of the same request gets the
// first answer back and makes nothing new. One key is made when a form opens and kept across every retry of that submission. It is replaced
// only once the create has succeeded or the form is opened again, because a failed create is never kept by the API and may use the same key;
// no import, so the tests can load it.

export const IDEMPOTENCY_HEADER = 'Idempotency-Key';

// 8 to 128 visible characters. A UUID is 36.
export function newIdempotencyKey(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string; getRandomValues?: (a: Uint8Array) => Uint8Array } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function idempotent(key: string): { headers: Record<string, string> } {
  return { headers: { [IDEMPOTENCY_HEADER]: key } };
}

export function validKey(key: string): boolean {
  return /^[\x21-\x7e]{8,128}$/.test(key);
}
