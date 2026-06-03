'use client';

import { useState, useRef } from 'react';
import { Turnstile } from '@marsidev/react-turnstile';
import type { TurnstileInstance } from '@marsidev/react-turnstile';

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

  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? '';
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? '';

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (!token) {
      setErrorMsg('Please complete the security check before sending.');
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
        setStatus('success');
        setName('');
        setEmail('');
        setSubject('');
        setMessage('');
        setToken('');
        turnstileRef.current?.reset();
      } else if (res.status === 422) {
        const data = await res.json().catch(() => ({}));
        const detail = data?.detail ?? 'Security check failed. Please try again.';
        setErrorMsg(detail);
        setStatus('error');
        turnstileRef.current?.reset();
      } else if (res.status === 429) {
        setErrorMsg('Too many messages sent. Please wait an hour before trying again.');
        setStatus('error');
      } else {
        setErrorMsg('Something went wrong. Please try again or email contact@phaemos.com directly.');
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
      <div className="rounded-xl border border-green-200 dark:border-green-900 bg-green-50 dark:bg-green-950/30 p-6 text-center space-y-2">
        <p className="text-lg font-semibold text-green-700 dark:text-green-400">Message sent</p>
        <p className="text-sm text-green-600 dark:text-green-500">
          We aim to reply within 5 working days. Keep an eye on the email you provided.
        </p>
        <button
          onClick={() => setStatus('idle')}
          className="mt-2 text-sm text-green-700 dark:text-green-400 underline underline-offset-2 hover:no-underline"
        >
          Send another message
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div className="space-y-1.5">
          <label htmlFor="contact-name" className="block text-sm font-medium text-surface-700 dark:text-surface-300">
            Name <span className="text-red-500">*</span>
          </label>
          <input
            id="contact-name"
            type="text"
            required
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Your name"
            className="w-full rounded-lg border border-surface-300 dark:border-surface-700 bg-white dark:bg-surface-900 px-3 py-2 text-sm text-surface-900 dark:text-surface-50 placeholder-surface-400 focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="contact-email" className="block text-sm font-medium text-surface-700 dark:text-surface-300">
            Email <span className="text-red-500">*</span>
          </label>
          <input
            id="contact-email"
            type="email"
            required
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-lg border border-surface-300 dark:border-surface-700 bg-white dark:bg-surface-900 px-3 py-2 text-sm text-surface-900 dark:text-surface-50 placeholder-surface-400 focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="contact-subject" className="block text-sm font-medium text-surface-700 dark:text-surface-300">
          Subject <span className="text-red-500">*</span>
        </label>
        <input
          id="contact-subject"
          type="text"
          required
          value={subject}
          onChange={e => setSubject(e.target.value)}
          placeholder="What is this about?"
          className="w-full rounded-lg border border-surface-300 dark:border-surface-700 bg-white dark:bg-surface-900 px-3 py-2 text-sm text-surface-900 dark:text-surface-50 placeholder-surface-400 focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="contact-message" className="block text-sm font-medium text-surface-700 dark:text-surface-300">
          Message <span className="text-red-500">*</span>
        </label>
        <textarea
          id="contact-message"
          required
          rows={5}
          value={message}
          onChange={e => setMessage(e.target.value)}
          placeholder="Describe your enquiry in as much detail as you can..."
          className="w-full rounded-lg border border-surface-300 dark:border-surface-700 bg-white dark:bg-surface-900 px-3 py-2 text-sm text-surface-900 dark:text-surface-50 placeholder-surface-400 focus:outline-none focus:ring-2 focus:ring-brand-500 resize-y"
        />
      </div>

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

      {errorMsg && (
        <p className="text-sm text-red-600 dark:text-red-400" role="alert">{errorMsg}</p>
      )}

      <button
        type="submit"
        disabled={status === 'submitting' || (!!siteKey && !token)}
        className="w-full sm:w-auto px-6 py-2.5 rounded-lg bg-brand-600 hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
      >
        {status === 'submitting' ? 'Sending...' : 'Send message'}
      </button>
    </form>
  );
}
