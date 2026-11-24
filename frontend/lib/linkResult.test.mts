import { test } from 'node:test';
import assert from 'node:assert/strict';
import { linkMessage, withoutLinkParams } from './linkResult.ts';

test('a successful link is said plainly', () => {
  assert.deepEqual(linkMessage('?linked=google'), { ok: true, text: 'Google is now linked. You can sign in with it or with your password.' });
  assert.equal(linkMessage('?linked=github')?.ok, true);
});

test('each refusal has a sentence and an unknown code is tolerated', () => {
  assert.match(linkMessage('?link_error=address_mismatch')?.text ?? '', /not the address of this account/);
  assert.match(linkMessage('?link_error=already_linked')?.text ?? '', /already linked/);
  assert.match(linkMessage('?link_error=link_expired')?.text ?? '', /too long/);
  assert.match(linkMessage('?link_error=identity_in_use')?.text ?? '', /already linked/);
  assert.match(linkMessage('?link_error=expired')?.text ?? '', /too long/);
  assert.match(linkMessage('?link_error=provider_unverified')?.text ?? '', /not verified/);
  assert.match(linkMessage('?link_error=cancelled')?.text ?? '', /cancelled/);
  assert.match(linkMessage('?link_error=failed')?.text ?? '', /could not be linked/);
  assert.equal(linkMessage('?link_error=zzz')?.ok, false);
  assert.equal(linkMessage('?link_error=')?.ok, false);
});

test('nothing to say without the parameters and they are taken out of the address', () => {
  assert.equal(linkMessage(''), null);
  assert.equal(linkMessage('?tab=x'), null);
  assert.equal(withoutLinkParams('?linked=google&tab=x'), '?tab=x');
  assert.equal(withoutLinkParams('?link_error=a'), '');
});

test('a provider name that is a property of every object is not looked up as one', () => {
  for (const name of ['constructor', 'toString', '__proto__', 'hasOwnProperty']) {
    const text = linkMessage(`?linked=${name}`)?.text ?? '';
    assert.equal(text, 'The provider is now linked. You can sign in with it or with your password.', name);
    assert.ok(!/function|native code/.test(text));
  }
});
