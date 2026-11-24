// what the profile page says when a provider sign-in that was started to link a provider comes back. The API sends the browser to
// /profile?linked=<provider> on success and /profile?link_error=<code> on a refusal. The codes are not fixed yet, so each is read
// by what it contains and an unknown one still gets a plain sentence.
// the names are looked up in a Map: the provider comes from the address and a plain object would answer for "constructor" with a
// function and print its body on the page
const NAMES: ReadonlyMap<string, string> = new Map([['google', 'Google'], ['github', 'GitHub']]);

export function linkMessage(search: string): { ok: boolean; text: string } | null {
  const params = new URLSearchParams(search);
  const linked = params.get('linked');
  if (linked) return { ok: true, text: `${NAMES.get(linked) ?? 'The provider'} is now linked. You can sign in with it or with your password.` };
  const error = params.get('link_error');
  if (error === null) return null;
  const code = error.toLowerCase();
  // the codes the API sends, then a reading of anything else
  if (code === 'address_mismatch') return { ok: false, text: 'The address at that provider is not the address of this account, so it was not linked.' };
  if (code === 'identity_in_use') return { ok: false, text: 'That provider account is already linked to another account.' };
  if (code === 'expired') return { ok: false, text: 'The link took too long or was started in another browser. Start again.' };
  if (code === 'provider_unverified') return { ok: false, text: 'The provider has not verified its email address, so it was not linked.' };
  if (code === 'cancelled') return { ok: false, text: 'You cancelled at the provider, so nothing was linked.' };
  if (code === 'failed') return { ok: false, text: 'The provider could not be linked. Try again.' };
  if (/unverified|verified/.test(code)) return { ok: false, text: 'The provider has not verified its email address, so it was not linked.' };
  if (/cancel|denied/.test(code)) return { ok: false, text: 'You cancelled at the provider, so nothing was linked.' };
  if (/mismatch|address|email/.test(code)) return { ok: false, text: 'The address at that provider is not the address of this account, so it was not linked.' };
  if (/already|in_use|identity|taken|another/.test(code)) return { ok: false, text: 'That provider account is already linked to another account.' };
  if (/expire|timeout|state|cookie/.test(code)) return { ok: false, text: 'The link took too long or was started in another browser. Start again.' };
  return { ok: false, text: 'The provider could not be linked. Try again.' };
}

// the address without those two parameters, so a reload does not say it again
export function withoutLinkParams(search: string): string {
  const params = new URLSearchParams(search);
  params.delete('linked');
  params.delete('link_error');
  const rest = params.toString();
  return rest ? `?${rest}` : '';
}
