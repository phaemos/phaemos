'use client';

import Link from 'next/link';
import { Suspense, useState, useEffect, useRef } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { refreshAccessToken, storeSession, takeReturn } from '@/lib/session';
import { tooManyAttemptsMessage } from '@/lib/signInErrors';
import { parseRetryAfter } from '@/lib/retryAfter';
import Countdown from '@/components/ui/Countdown';
import Button, { LinkButton } from '@/components/ui/Button';
import { Input, PasswordInput } from '@/components/ui/Input';
import Logo from '@/components/ui/Logo';
import { appPath, siteHref } from '@/lib/links';
import { safeNextPath } from '@/lib/publicPaths';
import { hasSignedInMarker } from '@/lib/signedIn';
import { PROVIDER_LABELS, parseProviders } from '@/lib/providers';
import Spinner from '@/components/ui/Spinner';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const AUTH_API = `${API_URL}/api/v1/auth`;

// useSearchParams needs a Suspense boundary so the page can still be prerendered.
export default function LoginPage() {
  return (
    <div className="w-full max-w-sm space-y-6">
      <div>
        <Link href={siteHref('/')} className="inline-flex min-h-[44px] min-w-[44px] items-center gap-2.5 no-underline" aria-label="PHAEMOS home">
          <Logo size={36} />
        </Link>
        <p className="mt-2 text-base text-surface-600 dark:text-surface-400">PHAEMOS watches machines through sensor nodes and shows what they report.</p>
      </div>
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  // the OAuth callback returns here with a step marker, never a token in the URL.
  const params = useSearchParams();
  const step = params.get('step');
  // the page they asked for before being sent here. Checked again: only a dashboard path on this address is accepted.
  const destination = safeNextPath(params.get('next')) ?? appPath('/dashboard');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  // set once the first factor has passed for an account with two-factor
  // authentication. An empty string means the challenge is in the cookie the
  // OAuth callback set, so only the code needs sending.
  const [mfaToken, setMfaToken] = useState<string | null>(step === 'mfa' ? '' : null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [wait, setWait] = useState<{ seconds: number; key: number } | null>(null);
  // the providers the API has configured. Empty while loading and if the request fails, so no button is shown meanwhile.
  const [providers, setProviders] = useState<string[]>([]);
  // the OAuth hand-back is finishing in the background until it succeeds or fails
  const [finishing, setFinishing] = useState(step === 'oauth');

  // the hand-back is acted on once, although development mode runs the effect twice
  const handedBack = useRef(false);

  useEffect(() => {
    if (step === 'mfa') return;
    if (step === 'oauth') {
      // swap the refresh cookie the OAuth callback set for an access token.
      // one refresh at a time: the cookie works once. Development mode runs this effect twice
      refreshAccessToken(null, true).then((token) => {
        if (!token) throw new Error('refresh failed');
        if (handedBack.current) return;
        handedBack.current = true;
        // a provider sign-in that proves it is you again (deleting an account) comes back to the page that asked
        router.replace(safeNextPath(takeReturn()) ?? destination);
      }).catch(() => {
        setFinishing(false);
        setError('Sign-in did not finish. Try again.');
      });
      return;
    }
    // redirect immediately if already authenticated so logged-in users
    // do not see a blank flash of the login form before being sent away.
    if (hasSignedInMarker(document.cookie)) router.replace(destination);
  }, [router, step, destination]);

  useEffect(() => {
    let alive = true;
    fetch(`${AUTH_API}/providers`, { credentials: 'omit' })
      .then((res) => (res.ok ? res.json() : null))
      .then((body) => { if (alive) setProviders(parseProviders(body)); })
      .catch(() => { if (alive) setProviders([]); });
    return () => { alive = false; };
  }, []);

  // a 429 says how long to wait in Retry-After. It is shown as a count-down that is announced once. An address the API has never heard of
  // is counted and answered exactly like a known one, so nothing here depends on which it was. The form stays usable: only the submit
  // button waits and the person can still correct what they typed.
  async function slowDown(res: Response) {
    const seconds = parseRetryAfter(res.headers.get('retry-after'));
    if (seconds && seconds > 0) {
      setError('');
      setWait({ seconds, key: Date.now() });
    } else {
      setError(tooManyAttemptsMessage(await res.json().catch(() => null)));
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      // credentials: 'include' lets the browser keep the httpOnly refresh cookie.
      const res = await fetch(`${AUTH_API}/login`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (res.status === 429) {
        await slowDown(res);
        return;
      }

      if (!res.ok) {
        setError('Invalid email or password.');
        return;
      }

      const body = await res.json();
      if (body.mfa_required) {
        setMfaToken(body.mfa_token);
        setPassword('');
        return;
      }

      storeSession(body.access_token);
      router.replace(destination);
    } catch {
      setError('Could not reach the server. Check your connection.');
    } finally {
      setLoading(false);
    }
  }

  async function handleCode(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const res = await fetch(`${AUTH_API}/2fa/verify`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, mfa_token: mfaToken || null }),
      });

      if (res.status === 429) {
        await slowDown(res);
        return;
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        // the second step is wrong (two_step_code_wrong) as opposed to a challenge that is gone or expired (sign_in_again). By code, not by sentence.
        if (body?.code === 'two_step_code_wrong' || body?.code === 'proof_wrong' || body?.code === 'code_required') {
          setError('That code did not work. Wait for the next one and try again.');
        } else {
          // the challenge expired or was refused, so the sign-in starts over.
          setMfaToken(null);
          setError('Sign-in expired. Please sign in again.');
        }
        setCode('');
        return;
      }

      const { access_token } = await res.json();
      storeSession(access_token);
      router.replace(destination);
    } catch {
      setError('Could not reach the server. Check your connection.');
    } finally {
      setLoading(false);
    }
  }

  // a live region that takes no room until there is something to say, so the form has no empty gap
  const errorSlot = (
    <p role="alert" className="text-base font-medium text-critical-800 empty:hidden dark:text-critical-300">{error}</p>
  );

  return (
    <div className="rounded-lg border border-surface-200 bg-surface-0 p-6 dark:border-surface-800 dark:bg-surface-900">
      <h1 className="mb-4 text-xl font-semibold tracking-tight text-surface-900 dark:text-surface-50">Sign in</h1>

      {finishing ? (
        <Spinner label="Finishing sign-in" />
      ) : mfaToken !== null ? (
        <form onSubmit={handleCode} className="space-y-4">
          <Input
            label="Authentication code"
            hint="Enter the 6-digit code from your authenticator app."
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            required
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            className="num tracking-widest"
          />
          {errorSlot}
          {wait && <Countdown seconds={wait.seconds} runKey={wait.key} lead="Too many attempts." onDone={() => setWait(null)} />}
          <Button type="submit" pending={loading} disabled={code.length !== 6 || Boolean(wait)} className="w-full">Verify</Button>
          <Button
            variant="ghost"
            className="w-full"
            onClick={() => { setMfaToken(null); setCode(''); setError(''); router.replace('/login'); }}
          >
            Use a different account
          </Button>
        </form>
      ) : (
        <>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            <PasswordInput label="Password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            {errorSlot}
            {wait && <Countdown seconds={wait.seconds} runKey={wait.key} lead="Too many sign-in attempts." onDone={() => setWait(null)} />}
            <Button type="submit" pending={loading} disabled={Boolean(wait)} className="w-full">Sign in</Button>
          </form>

          {providers.length > 0 && (
            <>
              <div className="my-5 flex items-center gap-3 text-base text-surface-700 dark:text-surface-300">
                <span className="h-px flex-1 bg-surface-200 dark:bg-surface-800" />
                or
                <span className="h-px flex-1 bg-surface-200 dark:bg-surface-800" />
              </div>

              <div className="space-y-2">
                {providers.map((p) => (
                  <LinkButton key={p} external target="_self" rel="" href={`${AUTH_API}/${p}`} variant="secondary" className="w-full">
                    Continue with {PROVIDER_LABELS[p]}
                  </LinkButton>
                ))}
              </div>
            </>
          )}

          <p className="mt-5 text-base text-surface-600 dark:text-surface-400">Accounts are made by invitation. To make yours, open the link in your invitation email.</p>
          <p className="mt-3 text-base text-surface-600 dark:text-surface-400">Forgotten your password? Ask an administrator to send you a reset link.</p>
          <p className="mt-3 text-base text-surface-600 dark:text-surface-400">
            How we use your data is in the <Link href={siteHref('/privacy')} className="text-brand-700 underline underline-offset-2 hover:no-underline dark:text-brand-400">privacy notice</Link>.
          </p>
        </>
      )}
    </div>
  );
}
