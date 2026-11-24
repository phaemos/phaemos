import { test } from 'node:test';
import assert from 'node:assert/strict';
import { routeProofError } from './proofErrors.ts';

function run(status: number, code: string | undefined, asks = { password: true, code: true }, headers: Record<string, string> = {}) {
  const out: Record<string, string> = {};
  const handled = routeProofError({ response: { status, data: { code, detail: `sentence for ${code}` }, headers } }, asks, {
    password: (t) => (out.password = t), code: (t) => (out.code = t), dialog: (t) => (out.dialog = t),
  }, 'fallback');
  return { handled, out };
}

test('a missing or wrong proof goes beside its field by code, whatever the sentence says', () => {
  assert.deepEqual(run(400, 'proof_required'), { handled: true, out: { password: 'sentence for proof_required' } });
  assert.deepEqual(run(400, 'code_required'), { handled: true, out: { code: 'sentence for code_required' } });
  assert.deepEqual(run(400, 'proof_wrong').out, { password: 'sentence for proof_wrong', code: 'sentence for proof_wrong' });
  assert.deepEqual(run(400, 'proof_wrong', { password: true, code: false }).out, { password: 'sentence for proof_wrong' });
  assert.deepEqual(run(400, 'provider_proof_required').out, { dialog: 'sentence for provider_proof_required' });
});

test('a 429 is said in the dialog with the wait the API gave', () => {
  const r = run(429, 'proof_rate_limited', undefined, { 'retry-after': '30' });
  assert.equal(r.handled, true);
  assert.equal(r.out.dialog, 'Too many attempts. Try again in 30 seconds.');
});

test('an error that is not about the proof is left to the caller', () => {
  for (const code of ['owns_machines', 'last_admin', 'token_limit', undefined]) {
    const r = run(409, code);
    assert.equal(r.handled, false, String(code));
    assert.deepEqual(r.out, {});
  }
});
