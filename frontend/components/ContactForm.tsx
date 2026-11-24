'use client';

import { useState, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { track } from '@/lib/analytics';
import { markContactSent } from '@/lib/contactSent';
import { Turnstile } from '@marsidev/react-turnstile';
import type { TurnstileInstance } from '@marsidev/react-turnstile';
import Button from '@/components/ui/Button';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input, Textarea } from '@/components/ui/Input';

type Status = 'idle' | 'submitting' | 'success' | 'error';

export default function ContactForm() {
  const [name, setName]       = useState('');
  const [email, setEmail]     = useState('');
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [token, setToken]     = useState('');
  const [status, setStatus]   = useState<Status>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  const turnstileRef = useRef<TurnstileInstance>(null);
  const router = useRouter();

  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? '';
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? '';

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    // without a site key the widget is not shown, so there is no token to ask for;
    // the server decides whether that is allowed: development skips the check
    // and production refuses with a 503.
    if (siteKey && !token) {
      setErrorMsg('Complete the check above, then send.');
      return;
    }

    setStatus('submitting');
    setErrorMsg('');

    try {
      const res = await fetch(`${apiBase}/api/v1/contact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, subject, message, turnstile_token: token }),
      });

      if (res.status === 204) {
        // the thank-you page is shown only after the API has accepted a message, which this mark tells it
        markContactSent();
        track('contact_message_sent');
        setStatus('success');
        setName('');
        setEmail('');
        setSubject('');
        setMessage('');
        setToken('');
        turnstileRef.current?.reset();
        router.push('/contact/sent');
      } else if (res.status === 422) {
        const data = await res.json().catch(() => ({}));
        // a validation error returns a list of objects, which cannot be rendered
        const detail = typeof data?.detail === 'string'
          ? data.detail
          : 'Some details were not accepted. Check the form and try again.';
        setErrorMsg(detail);
        setStatus('error');
        turnstileRef.current?.reset();
      } else if (res.status === 503) {
        const data = await res.json().catch(() => ({}));
        setErrorMsg(
          typeof data?.detail === 'string'
            ? data.detail
            : 'The contact form is not available right now. Email contact@phaemos.com directly.',
        );
        setStatus('error');
        turnstileRef.current?.reset();
      } else if (res.status === 429) {
        setErrorMsg('Too many messages sent. Wait an hour before trying again.');
        setStatus('error');
      } else {
        setErrorMsg('The message did not send. Try again or email contact@phaemos.com.');
        setStatus('error');
        turnstileRef.current?.reset();
      }
    } catch {
      setErrorMsg('Could not reach the server. Check your connection and try again.');
      setStatus('error');
    }
  }

  if (status === 'success') {
    return (
      <div role="status" className="max-w-xl space-y-3">
        <h2 className="text-2xl font-semibold text-surface-900 dark:text-surface-50">Message sent</h2>
        <p className="text-surface-700 dark:text-surface-300">We will reply to the address you gave.</p>
        <Button variant="secondary" onClick={() => setStatus('idle')}>
          Send another message
        </Button>
      </div>
    );
  }

  const submitting = status === 'submitting';

  return (
    <form onSubmit={handleSubmit} className="max-w-xl space-y-5">
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <Input id="contact-name" label="Name" type="text" required autoComplete="name" value={name} onChange={e => setName(e.target.value)} />
        <Input id="contact-email" label="Email" type="email" required autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" hint="Only to reply to you." />
      </div>

      <Input id="contact-subject" label="Subject" type="text" required value={subject} onChange={e => setSubject(e.target.value)} />

      <Textarea id="contact-message" label="Message" required rows={6} value={message} onChange={e => setMessage(e.target.value)} className="resize-y" />

      {siteKey && (
        <Turnstile
          ref={turnstileRef}
          siteKey={siteKey}
          onSuccess={setToken}
          onError={() => { setToken(''); setErrorMsg('Security check failed. Refresh the page and try again.'); }}
          onExpire={() => setToken('')}
          options={{ theme: 'auto' }}
        />
      )}

      {errorMsg && <ErrorNotice message={errorMsg} />}

      <p className="text-base text-surface-700 dark:text-surface-300">
        Your message is sent to our mailbox as an email and the API does not store it, as the <Link href="/privacy" className="text-brand-700 underline underline-offset-2 hover:no-underline dark:text-brand-400">privacy notice</Link> explains.
      </p>

      <Button type="submit" pending={submitting} disabled={!!siteKey && !token}>
        Send message
      </Button>
    </form>
  );
}
