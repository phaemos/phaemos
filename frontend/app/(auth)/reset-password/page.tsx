'use client';

import { useEffect, useRef, useState } from 'react';
import { passwordProblem, passwordRules } from '@/lib/password';
import { tooManyAttemptsMessage } from '@/lib/signInErrors';
import { parseRetryAfter } from '@/lib/retryAfter';
import { readInviteToken } from '@/lib/inviteToken';
import Countdown from '@/components/ui/Countdown';
import Button, { LinkButton } from '@/components/ui/Button';
import { PasswordInput } from '@/components/ui/Input';
import Logo from '@/components/ui/Logo';
import { StatusShape } from '@/components/ui/StatusBadge';
import { siteHref } from '@/lib/links';
import Link from 'next/link';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

type Phase = 'reading' | 'form' | 'missing' | 'done' | 'dead';

// an administrator sends a reset link to the person's own address (there is no "forgot password" request yet). The link carries its one-time
// token after #token=, which a browser never sends to a server and only the fragment is accepted. The token is read once, kept in memory,
// removed from the address bar and sent only in the body of POST /auth/reset-password. Every refusal (bad, used, expired, deactivated) is the
// same 400, so the page says one thing for all of them: the link is no good and a new one has to be asked for.
export default function ResetPasswordPage() {
  const [token, setToken] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('reading');
  const [password, setPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [formError, setFormError] = useState('');
  const [pending, setPending] = useState(false);
  const [wait, setWait] = useState<{ seconds: number; key: number } | null>(null);
  const holding = useRef(false);

  useEffect(() => {
    const read = () => {
      const { token: found, legacyQuery, cleaned } = readInviteToken(window.location.pathname, window.location.search, window.location.hash);
      if (found) {
        holding.current = true;
        setToken(found);
        setPhase('form');
        window.history.replaceState(null, '', cleaned);
      } else if (legacyQuery) {
        // a token in the query string reached the web server, so only the fragment is accepted: the link is no good
        window.history.replaceState(null, '', cleaned);
        setPhase('dead');
      } else if (!holding.current) {
        setPhase((p) => (p === 'reading' ? 'missing' : p));
      }
    };
    read();
    // pasting the whole link into a tab that already shows this page only changes the fragment
    window.addEventListener('hashchange', read);
    return () => window.removeEventListener('hashchange', read);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setFormError('');
    const problem = passwordProblem(password) ?? '';
    setPasswordError(problem);
    if (problem || !token) return;
    setPending(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/reset-password`, {
        method: 'POST',
        credentials: 'omit',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, password }),
      });
      if (res.status === 204 || res.ok) {
        setToken(null);
        setPassword('');
        setPhase('done');
        return;
      }
      const body = await res.json().catch(() => null);
      if (res.status === 429) {
        const seconds = parseRetryAfter(res.headers.get('retry-after'));
        if (seconds && seconds > 0) setWait({ seconds, key: Date.now() });
        else setFormError(tooManyAttemptsMessage(body));
      } else if (body?.code === 'reset_link_invalid') {
        // every refusal of the link (bad, used, expired, deactivated) is this one code
        setToken(null);
        setPhase('dead');
      } else if (res.status === 400 || res.status === 422) {
        // the link is fine and the password was not: the API says which rule it broke (a common password, for one)
        setPasswordError(typeof body?.detail === 'string' ? body.detail : 'That password was not accepted. Choose another.');
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
        <p className="mt-2 text-base text-surface-600 dark:text-surface-400">An administrator sent you this link so you can choose a new password.</p>
      </div>

      <div className="rounded-lg border border-surface-200 bg-surface-0 p-6 dark:border-surface-800 dark:bg-surface-900">
        <h1 className="mb-4 text-xl font-semibold tracking-tight text-surface-900 dark:text-surface-50">Choose a new password</h1>

        {phase === 'reading' && <p role="status" className="text-base text-surface-600 dark:text-surface-400">Checking the link</p>}

        {phase === 'form' && (
          <form onSubmit={submit} noValidate className="space-y-4">
            <div>
              <PasswordInput label="New password" required autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} error={passwordError || undefined} wrapperClassName="min-h-[100px]" />
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
            {wait && <Countdown seconds={wait.seconds} runKey={wait.key} lead="Too many attempts." onDone={() => setWait(null)} />}
            <p className="text-base text-surface-700 dark:text-surface-300">Every device signed in to your account is signed out when you save. If you use two-step sign-in it stays on.</p>
            <Button type="submit" pending={pending} disabled={Boolean(wait)} className="w-full">Save password</Button>
          </form>
        )}

        {phase === 'done' && (
          <div role="status" className="space-y-4">
            <p className="text-base text-surface-900 dark:text-surface-50">Your password is changed. Sign in with it.</p>
            <LinkButton href="/login" className="w-full">Go to sign in</LinkButton>
          </div>
        )}

        {phase === 'missing' && (
          <div role="alert" className="space-y-4">
            <p className="text-base text-surface-900 dark:text-surface-50">This page needs the link from your reset email. That link is missing here. Open the link in the email again.</p>
            <LinkButton href="/login" variant="secondary" className="w-full">Go to sign in</LinkButton>
          </div>
        )}

        {phase === 'dead' && (
          <div role="alert" className="space-y-4">
            <p className="text-base text-surface-900 dark:text-surface-50">This reset link is invalid or has expired. A link works once and lasts 2 hours. Ask an administrator to send you a new one.</p>
            <LinkButton href="/login" variant="secondary" className="w-full">Go to sign in</LinkButton>
          </div>
        )}
      </div>
    </div>
  );
}
