import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hasSignedInMarker } from './signedIn.ts';

test('the marker is found among other cookies and nothing else counts', () => {
  assert.equal(hasSignedInMarker('signed_in=1'), true);
  assert.equal(hasSignedInMarker('a=b; signed_in=1; c=d'), true);
  assert.equal(hasSignedInMarker('theme=dark'), false);
  assert.equal(hasSignedInMarker('signed_in=0'), false);
  assert.equal(hasSignedInMarker('xsigned_in=1'), false);
  // the old cookie, which carried a token, is no longer a sign-in
  assert.equal(hasSignedInMarker('token=abc.def.ghi'), false);
});
