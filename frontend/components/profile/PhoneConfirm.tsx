'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { errorInfo } from '@/lib/apiCode';
import RequestRef from '@/components/ui/RequestRef';
import { describeApiError } from '@/lib/apiError';
import { retryAfterOf } from '@/lib/retryAfter';
import Button from '@/components/ui/Button';
import Countdown from '@/components/ui/Countdown';
import { Input } from '@/components/ui/Input';
import type { UserChange, UserProfile } from './types';

// confirming the number on the account. Alert texts go only to a confirmed number and saving a number (a new one or the same one again)
// leaves it unconfirmed. POST /auth/me/phone/send-code takes no body and POST /auth/me/phone/confirm takes { code } of six digits;
// every answer the API can give is said in words:
//   200 { sent: true }   a code is on its way and lasts 10 minutes
//   200 { sent: false }  development with no text service: nothing was sent
//   400                  no number on the account (send) or a wrong, expired or earlier code (confirm). Five wrong tries end the code.
//   429                  too many codes (Retry-After says how long)
//   502                  the text service refused the message
//   503                  this server has no text service
export default function PhoneConfirm({ user, onChange }: { user: UserProfile; onChange: UserChange }) {
  const [sent, setSent] = useState<'no' | 'yes' | 'dev'>('no');
  const [code, setCode] = useState('');
  const [codeError, setCodeError] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const [wait, setWait] = useState<{ seconds: number; key: number } | null>(null);
  const [sending, setSending] = useState(false);
  const [confirming, setConfirming] = useState(false);

  // a number is on the account but the API has not said whether it is confirmed: nothing is claimed
  if (!user.phone_number || user.phone_confirmed === undefined) return null;

  if (user.phone_confirmed) {
    return (
      <p className="max-w-[72ch] text-base text-surface-900 dark:text-surface-50">
        <strong className="font-semibold">Confirmed.</strong> Text alerts for machines you own can reach this number, when text alerts are switched on.
      </p>
    );
  }

  async function sendCode() {
    setError('');
    setReference(null);
    setMessage('');
    setCodeError('');
    setSending(true);
    try {
      const { data } = await api.post<{ sent?: boolean; expires_in_seconds?: number }>('/auth/me/phone/send-code');
      if (data.sent === false) {
        setSent('dev');
        setMessage('No text was sent, because this server has no text service set up. That happens in development. Text alerts cannot reach this number.');
      } else {
        setSent('yes');
        const minutes = Math.round((data.expires_in_seconds ?? 600) / 60);
        setMessage(`A code is on its way to ${user.phone_number}. It works for ${minutes} minutes.`);
      }
    } catch (err) {
      const info = errorInfo(err);
      const seconds = retryAfterOf(err);
      // what to do comes from the code (docs/api-conventions.md). The status is only the fallback for an answer with no code.
      const code = info.code ?? (info.status === 429 ? 'phone_codes_limit' : info.status === 502 ? 'text_not_sent' : info.status === 503 ? 'texts_not_set_up' : info.status === 400 ? 'phone_missing' : '');
      if (info.status === 429 && seconds) setWait({ seconds, key: Date.now() });
      else if (info.status === 429) setError('Too many codes have been sent. Try again later.');
      else if (code === 'phone_missing') setError('Save a number first, then ask for a code.');
      else if (code === 'text_not_sent') setError('The text service refused the message. Check the number and try again in a moment.');
      else if (code === 'texts_not_set_up') setError('Texts are not set up on this server, so a code cannot be sent. Text alerts cannot reach this number until they are.');
      else {
        setError(info.detail ?? describeApiError(err, 'The code'));
        setReference(info.requestId ?? null);
      }
    } finally {
      setSending(false);
    }
  }

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setCodeError('');
    if (code.length !== 6) {
      setCodeError('Enter the 6 digits from the text.');
      return;
    }
    setConfirming(true);
    try {
      await api.post('/auth/me/phone/confirm', { code });
      setCode('');
      setSent('no');
      setMessage('');
      onChange({ phone_confirmed: true });
    } catch (err) {
      const info = errorInfo(err);
      const seconds = retryAfterOf(err);
      if (info.status === 429 && seconds) setWait({ seconds, key: Date.now() });
      else if (info.code === 'phone_code_wrong' || (!info.code && info.status === 400)) setCodeError('That code is wrong or has expired. After five wrong tries a new code is needed.');
      else {
        setError(info.detail ?? describeApiError(err, 'The confirmation'));
        setReference(info.requestId ?? null);
      }
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="max-w-md space-y-3">
      <p className="text-base text-surface-900 dark:text-surface-50">
        <strong className="font-semibold">Not confirmed.</strong> Text alerts do not go to this number until you confirm it with a code we text to it.
      </p>
      {sent === 'yes' && (
        <form onSubmit={confirm} noValidate className="space-y-3">
          <Input label="Code from the text" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => { setCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setCodeError(''); }} error={codeError || undefined} className="num w-40 tracking-widest" wrapperClassName="min-h-[100px]" />
          <div className="flex flex-wrap gap-3">
            <Button type="submit" pending={confirming}>Confirm number</Button>
            <Button variant="secondary" onClick={sendCode} pending={sending} disabled={Boolean(wait)}>Send a new code</Button>
          </div>
        </form>
      )}
      {sent !== 'yes' && (
        <Button variant="secondary" onClick={sendCode} pending={sending} disabled={Boolean(wait)}>Send code</Button>
      )}
      {wait && <Countdown seconds={wait.seconds} runKey={wait.key} lead="Too many codes." onDone={() => setWait(null)} />}
      <p role="status" className="min-h-5 text-base text-surface-900 dark:text-surface-50">{message}</p>
      <p role="alert" className="min-h-5 text-base font-medium text-critical-800 dark:text-critical-300">{error}</p>
      {error && <RequestRef id={reference} />}
    </div>
  );
}
