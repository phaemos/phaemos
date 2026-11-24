'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { errorInfo } from '@/lib/apiCode';
import { describeApiError } from '@/lib/apiError';
import { lockedMessage } from '@/lib/signInErrors';
import { TOKENS_REVOKED_NOTE } from '@/lib/tokenScopes';
import { passwordProblem, passwordRules } from '@/lib/password';
import Button from '@/components/ui/Button';
import { Input, PasswordInput } from '@/components/ui/Input';
import { StatusShape } from '@/components/ui/StatusBadge';
import Section, { FormMessage } from './Section';
import { providerName, type UserProfile } from './types';

// POST /auth/change-password with { old_password, new_password }. The API then ends every other session.
export default function PasswordSection({ user }: { user: UserProfile }) {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<{ old?: string; next?: string; confirm?: string }>({});
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (user.oauth_provider) {
    return (
      <Section id="password" title="Password">
        <p className="max-w-[72ch] text-base text-surface-700 dark:text-surface-300">You sign in with {providerName(user.oauth_provider)}, so we do not offer a password change for this account.</p>
      </Section>
    );
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setReference(null);
    setOk('');
    const next: typeof errors = {};
    if (!oldPassword) next.old = 'Enter your current password.';
    const problem = passwordProblem(newPassword);
    if (problem) next.next = problem;
    if (confirm !== newPassword) next.confirm = 'The two passwords do not match.';
    setErrors(next);
    if (Object.keys(next).length) return;

    setPending(true);
    try {
      await api.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword });
      setOldPassword('');
      setNewPassword('');
      setConfirm('');
      setOk('Password changed. Every other session was signed out.');
    } catch (err) {
      const info = errorInfo(err);
      const locked = lockedMessage(err);
      if (locked) setError(locked);
      // the current password was wrong (password_wrong) or the new one is refused (a common password, too short): beside each
      else if (info.code === 'password_wrong' || info.code === 'proof_wrong' || info.code === 'proof_required') setErrors({ old: info.detail });
      else if (info.status === 400 && info.detail) setErrors({ next: info.detail });
      else {
        setError(info.detail ?? describeApiError(err, 'The password change'));
        setReference(info.requestId ?? null);
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Section id="password" title="Password">
      <form onSubmit={save} noValidate className="max-w-md space-y-4">
        <PasswordInput label="Current password" required autoComplete="current-password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} error={errors.old} wrapperClassName="min-h-[100px]" />
        <div>
          <PasswordInput label="New password" required autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} error={errors.next} wrapperClassName="min-h-[100px]" />
          <ul aria-label="Password rules" className="mt-1 space-y-1 text-base text-surface-700 dark:text-surface-300">
            {passwordRules(newPassword).map((r) => (
              <li key={r.id} className="flex items-center gap-2">
                <StatusShape shape={r.met ? 'circle' : 'ring'} />
                <span>{r.text}<span className="sr-only">{r.met ? ', met' : ', not met'}</span></span>
              </li>
            ))}
          </ul>
        </div>
        <PasswordInput label="Confirm new password" required autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} error={errors.confirm} wrapperClassName="min-h-[100px]" />
        <p className="text-base text-surface-700 dark:text-surface-300">Changing your password signs out your other sessions. {TOKENS_REVOKED_NOTE}</p>
        <Button type="submit" pending={pending}>Change password</Button>
        <FormMessage ok={ok} error={error} requestId={reference} />
      </form>
    </Section>
  );
}
