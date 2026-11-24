'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { passwordProblem, passwordRules } from '@/lib/password';
import { apiDetail } from '@/lib/apiDetail';
import { tooManyAttemptsMessage } from '@/lib/signInErrors';
import Button, { LinkButton } from '@/components/ui/Button';
import { Input, PasswordInput } from '@/components/ui/Input';
import Logo from '@/components/ui/Logo';
import { readInviteToken } from '@/lib/inviteToken';
import { tokenExpiry } from '@/lib/session';
import { serverNow } from '@/lib/serverClock';
import { appPath, siteHref } from '@/lib/links';
import { StatusShape } from '@/components/ui/StatusBadge';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

type Phase = 'reading' | 'form' | 'missing' | 'done' | 'bad-token' | 'exists';

// the invitation email links here with #token= (only the fragment is accepted). The token is read once, kept in memory, removed from the address
// bar and sent only in the body of POST /auth/accept-invite. It is never logged, stored or put in a link.
export default function AcceptInvitePage() {
  const [token, setToken] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('reading');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [nameError, setNameError] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [formError, setFormError] = useState('');
  const [pending, setPending] = useState(false);
  const [createdEmail, setCreatedEmail] = useState('');
  // a token is held (and its check may be in flight): the second run of the effect in development finds none in the address
  const holding = useRef(false);

  // reading the address is synchronising with an external system. It has to happen after mount because the
  // server render has no address to read.
  useEffect(() => {
    const read = () => {
      const { token: found, legacyQuery, cleaned } = readInviteToken(window.location.pathname, window.location.search, window.location.hash);
      if (found) {
        // check the link before asking for a name and a password. First by the expiry the link carries: a link that is not a link
        // or whose time has passed, is dead whatever else is true of it.
        holding.current = true;
        const exp = tokenExpiry(found);
        // a link that is not a link at all is dead at once. Whether its time has passed is the API's to say (a browser clock can be
        // wrong) and the expiry in the link is only a fallback when the API cannot be asked.
        const garbled = exp === null;
        setToken(garbled ? null : found);
        if (garbled) {
          setPhase('bad-token');
        } else {
          // POST /auth/invite/check tells a link that is fine from one that has run out or was used already. The form waits for
          // its answer. An API without the route (or one that cannot be reached) leaves the form and the link is then found out
          // when the form is sent.
          setPhase('reading');
          fetch(`${API_URL}/api/v1/auth/invite/check`, { method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: found }) })
            .then(async (res) => (res.ok ? ((await res.json().catch(() => null)) as { status?: string } | null) : null))
            .then((body) => {
              if (body?.status === 'used') { setToken(null); setPhase('exists'); }
              else if (body?.status === 'expired') { setToken(null); setPhase('bad-token'); }
              else if (body?.status !== 'valid' && exp !== null && exp * 1000 < serverNow()) { setToken(null); setPhase('bad-token'); }
              else setPhase('form');
            })
            .catch(() => {
              // the API could not be asked: fall back to the expiry in the link, on the server's clock
              if (exp !== null && exp * 1000 < serverNow()) { setToken(null); setPhase('bad-token'); } else setPhase('form');
            });
        }
        // take the token out of the address bar and the history entry, from the fragment and from the query
        window.history.replaceState(null, '', cleaned);
      } else if (legacyQuery) {
        // a token in the query string reached the web server and only the fragment is accepted now: the link is dead
        window.history.replaceState(null, '', cleaned);
        setPhase('bad-token');
      } else {
        // development mode runs this effect twice. The second run finds no token because the first removed it, so a
        // token already held is kept.
        if (!holding.current) setPhase((p) => (p === 'reading' ? 'missing' : p));
      }
    };
    read();
    // pasting the full link into a tab that already shows this page only changes the fragment, which does not reload it
    window.addEventListener('hashchange', read);
    return () => window.removeEventListener('hashchange', read);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setFormError('');
    const nErr = name.trim() ? '' : 'Enter your name.';
    const pErr = passwordProblem(password) ?? '';
    setNameError(nErr);
    setPasswordError(pErr);
    if (nErr || pErr || !token) return;

    setPending(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/accept-invite`, {
        method: 'POST',
        credentials: 'omit',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, name: name.trim(), password }),
      });
      if (res.ok) {
        const user = await res.json().catch(() => null);
        setCreatedEmail(typeof user?.email === 'string' ? user.email : '');
        setToken(null);
        setPassword('');
        setPhase('done');
        return;
      }
      const body = await res.json().catch(() => null);
      if (res.status === 429) {
        setFormError(tooManyAttemptsMessage(body));
      } else if (body?.code === 'account_exists' || body?.code === 'invitation_used') {
        // the account is already made: the link cannot be used again
        setToken(null);
        setPhase('exists');
      } else if (res.status === 400 || body?.code === 'invitation_invalid') {
        // the token is not valid or has expired or is not an invitation
        setToken(null);
        setPhase('bad-token');
      } else if (res.status === 422) {
        setPasswordError(apiDetail({ response: { status: 422, data: body } }) ?? 'The details were not accepted. Check them and try again.');
      } else {
        setFormError(`The server had a problem with that. Try again in a moment.${typeof body?.request_id === 'string' ? ` Reference ${body.request_id}.` : ''}`);
      }
    } catch {
      setFormError('Could not reach the server. Check your connection.');
    } finally {
      setPending(false);
    }
  }

  const rules = passwordRules(password);

  return (
    <div className="w-full max-w-sm space-y-6">
      {/* the link carries a secret, so the page asks the browser not to pass its address on */}
      <meta name="referrer" content="no-referrer" />
      <div>
        <Link href={siteHref('/')} className="inline-flex min-h-[44px] min-w-[44px] items-center gap-2.5 no-underline" aria-label="PHAEMOS home">
          <Logo size={36} />
        </Link>
        <p className="mt-2 text-base text-surface-600 dark:text-surface-400">You were invited to PHAEMOS. Choose a password to finish setting up your account.</p>
      </div>

      <div className="rounded-lg border border-surface-200 bg-surface-0 p-6 dark:border-surface-800 dark:bg-surface-900">
        <h1 className="mb-4 text-xl font-semibold tracking-tight text-surface-900 dark:text-surface-50">Accept your invitation</h1>

        {phase === 'reading' && <p role="status" className="text-base text-surface-600 dark:text-surface-400">Checking the link</p>}

        {phase === 'form' && (
          <form onSubmit={submit} noValidate className="space-y-4">
            <Input label="Your name" required autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} error={nameError || undefined} wrapperClassName="min-h-[100px]" />
            <div>
              <PasswordInput
                label="Password"
                required
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                error={passwordError || undefined}
                wrapperClassName="min-h-[100px]"
              />
              <ul aria-label="Password rules" className="mt-1 space-y-1 text-base text-surface-700 dark:text-surface-300">
                {rules.map((r) => (
                  <li key={r.id} className="flex items-center gap-2">
                    <StatusShape shape={r.met ? 'circle' : 'ring'} />
                    <span>{r.text}<span className="sr-only">{r.met ? ', met' : ', not met'}</span></span>
                  </li>
                ))}
              </ul>
            </div>
            <p role="alert" className="text-base font-medium text-critical-800 empty:hidden dark:text-critical-300">{formError}</p>
            <p className="text-base text-surface-700 dark:text-surface-300">
              By creating an account you agree to the <Link href={siteHref('/terms')} className="text-brand-700 underline underline-offset-2 hover:no-underline dark:text-brand-400">terms of use</Link>. How we use your data is in the <Link href={siteHref('/privacy')} className="text-brand-700 underline underline-offset-2 hover:no-underline dark:text-brand-400">privacy notice</Link>.
            </p>
            <Button type="submit" pending={pending} className="w-full">Create account</Button>
          </form>
        )}

        {phase === 'done' && (
          <div role="status" className="space-y-4">
            <p className="text-base text-surface-900 dark:text-surface-50">
              Your account{createdEmail ? <> for <span className="font-medium">{createdEmail}</span></> : null} is ready. Sign in with that email and the password you just chose.
            </p>
            <LinkButton href="/login" className="w-full">Go to sign in</LinkButton>
          </div>
        )}

        {phase === 'missing' && (
          <div role="alert" className="space-y-4">
            <p className="text-base text-surface-900 dark:text-surface-50">This page needs the link from your invitation email. That link is missing here. Open the link in the email again. If it still does not work ask your administrator to send a new invitation.</p>
            <LinkButton href="/login" variant="secondary" className="w-full">Go to sign in</LinkButton>
          </div>
        )}

        {phase === 'bad-token' && (
          <div role="alert" className="space-y-4">
            <p className="text-base text-surface-900 dark:text-surface-50">This invitation link is not valid or has expired. A link lasts 48 hours. Ask your administrator to send a new invitation.</p>
            <LinkButton href="/login" variant="secondary" className="w-full">Go to sign in</LinkButton>
          </div>
        )}

        {phase === 'exists' && (
          <div role="alert" className="space-y-4">
            <p className="text-base text-surface-900 dark:text-surface-50">An account for this invitation already exists, so the link cannot be used again. Sign in instead. A lost password cannot be reset from the dashboard. Whoever runs this installation can set a temporary password for you.</p>
            <LinkButton href="/login" className="w-full">Go to sign in</LinkButton>
          </div>
        )}
      </div>
    </div>
  );
}
