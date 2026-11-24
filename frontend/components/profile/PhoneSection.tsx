'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { apiDetail } from '@/lib/apiDetail';
import { describeApiError } from '@/lib/apiError';
import { PHONE_HINT, cleanPhone, phoneProblem } from '@/lib/phone';
import Button from '@/components/ui/Button';
import { Input, PasswordInput } from '@/components/ui/Input';
import Section, { FormMessage } from './Section';
import PhoneConfirm from './PhoneConfirm';
import { hasPassword, type UserChange, type UserProfile } from './types';
import { errorInfo } from '@/lib/apiCode';
import { routeProofError } from '@/lib/proofErrors';

// the number critical alerts are texted to. The API accepts an empty value or international form and answers 422 with
// its own message otherwise, which is shown as the field error. An empty value clears the number. Changing the number needs the
// same proof as changing the email, because critical alert texts go to it: the password (and a current code when two-step is
// on) or for a provider account a return from the provider in the last 5 minutes, which the API's message then asks for.
export default function PhoneSection({ user, onChange }: { user: UserProfile; onChange: UserChange }) {
  const [phone, setPhone] = useState(user.phone_number ?? '');
  const [fieldError, setFieldError] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [codeError, setCodeError] = useState('');
  const withPassword = hasPassword(user);
  // the same number written another way (spaces, hyphens) is not a change and needs no proof
  const changed = cleanPhone(phone) !== cleanPhone(user.phone_number ?? '');
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setReference(null);
    setOk('');
    const problem = phoneProblem(phone);
    setFieldError(problem ?? '');
    setPasswordError('');
    setCodeError('');
    if (problem) return;
    if (changed && withPassword && !password) {
      setPasswordError('Enter your current password to change your number.');
      return;
    }
    if (changed && user.totp_enabled && code.length !== 6) {
      setCodeError('Enter the 6 digits from your authenticator app.');
      return;
    }
    setPending(true);
    try {
      const body: Record<string, string> = { phone_number: phone };
      if (changed && withPassword) body.current_password = password;
      if (changed && user.totp_enabled) body.code = code;
      const { data } = await api.patch<UserProfile>('/auth/me', body);
      onChange(data);
      setPhone(data.phone_number ?? '');
      setPassword('');
      setCode('');
      setOk(data.phone_number ? (changed ? 'Saved. The number is not confirmed yet, so text alerts do not go to it. Ask for a code below.' : 'Saved.') : 'Number removed. We will not send you text alerts.');
    } catch (err) {
      const info = errorInfo(err);
      const handled = routeProofError(err, { password: withPassword, code: Boolean(user.totp_enabled) }, { password: setPasswordError, code: setCodeError, dialog: setError }, 'That did not work.');
      if (!handled) {
        // a 422 is about the number itself and is said beside it. Anything else is said under the form with the request reference.
        if (info.status === 422 && info.detail) setFieldError(info.detail);
        else {
          setError(info.detail ?? describeApiError(err, 'Your number'));
          setReference(info.requestId ?? null);
        }
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Section id="phone" title="Phone number for text alerts" description="Kept on your account. When text alerts are switched on, we text this number about a critical alert on a machine you own. Nothing is texted while they are off.">
      <form onSubmit={save} noValidate className="max-w-md space-y-4">
        <Input label="Phone number" type="tel" autoComplete="tel" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} hint={PHONE_HINT} error={fieldError || undefined} wrapperClassName="min-h-[150px]" className="num" />
        {changed && withPassword && (
          <PasswordInput label="Current password" hint="Needed to change your number, because alert texts go to it." autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} error={passwordError || undefined} wrapperClassName="min-h-[124px]" />
        )}
        {changed && user.totp_enabled && (
          <Input label="Code from your authenticator app" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} error={codeError || undefined} className="num w-40 tracking-widest" wrapperClassName="min-h-[100px]" />
        )}
        {changed && !withPassword && <p className="text-base text-surface-700 dark:text-surface-300">This account signs in through a provider, so changing the number needs a sign-in with that provider in the last 5 minutes. If it is refused, sign in again and then save.</p>}
        <Button type="submit" pending={pending}>Save number</Button>
        <FormMessage ok={ok} error={error} requestId={reference} />
      </form>
      {!changed && <div className="mt-4"><PhoneConfirm user={user} onChange={onChange} /></div>}
    </Section>
  );
}
