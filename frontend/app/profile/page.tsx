'use client';

import { useState, useEffect, useRef } from 'react';
import api from '../../lib/api';
import { useToast } from '../../hooks/useToast';

interface UserProfile {
  id: string;
  name: string | null;
  email: string;
  role: string;
  phone_number: string | null;
  oauth_provider: string | null;
  totp_enabled: boolean;
}

type Section = 'profile' | 'security' | 'twofa' | 'data';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export default function ProfilePage() {
  const { addToast } = useToast();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeSection, setActiveSection] = useState<Section>('profile');

  // Profile edit state
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [profileSaving, setProfileSaving] = useState(false);

  // Password state
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordSaving, setPasswordSaving] = useState(false);

  // 2FA state
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [tfaSaving, setTfaSaving] = useState(false);

  // Delete account state
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const deleteInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get<UserProfile>('/auth/me')
      .then(({ data }) => {
        setUser(data);
        setName(data.name ?? '');
        setEmail(data.email);
        setPhone(data.phone_number ?? '');
      })
      .catch(() => addToast('error', 'Failed to load profile.'))
      .finally(() => setLoading(false));
  }, [addToast]);

  // ── Profile update ────────────────────────────────────────────────────────────

  async function handleProfileSave(e: React.FormEvent) {
    e.preventDefault();
    setProfileSaving(true);
    try {
      const { data } = await api.patch<UserProfile>('/auth/me', {
        name: name || null,
        email,
        phone_number: phone || null,
      });
      setUser(data);
      addToast('success', 'Profile updated.');
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        .response?.data?.detail ?? 'Failed to update profile.';
      addToast('error', msg);
    } finally {
      setProfileSaving(false);
    }
  }

  // ── Password change ───────────────────────────────────────────────────────────

  async function handlePasswordChange(e: React.FormEvent) {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      addToast('error', 'New passwords do not match.');
      return;
    }
    setPasswordSaving(true);
    try {
      await api.post('/auth/change-password', {
        old_password: oldPassword,
        new_password: newPassword,
      });
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
      addToast('success', 'Password changed.');
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        .response?.data?.detail ?? 'Failed to change password.';
      addToast('error', msg);
    } finally {
      setPasswordSaving(false);
    }
  }

  // ── 2FA enable ────────────────────────────────────────────────────────────────

  async function handle2faEnable() {
    setTfaSaving(true);
    try {
      const { data } = await api.post<{ qr_code: string; secret: string }>('/auth/2fa/enable');
      setQrCode(data.qr_code);
      setTotpCode('');
    } catch {
      addToast('error', 'Failed to start 2FA setup.');
    } finally {
      setTfaSaving(false);
    }
  }

  async function handle2faConfirm(e: React.FormEvent) {
    e.preventDefault();
    setTfaSaving(true);
    try {
      await api.post(`/auth/2fa/confirm?code=${encodeURIComponent(totpCode)}`);
      setUser(prev => prev ? { ...prev, totp_enabled: true } : prev);
      setQrCode(null);
      setTotpCode('');
      addToast('success', '2FA enabled.');
    } catch {
      addToast('error', 'Invalid code - try again.');
    } finally {
      setTfaSaving(false);
    }
  }

  async function handle2faDisable(e: React.FormEvent) {
    e.preventDefault();
    setTfaSaving(true);
    try {
      await api.post(`/auth/2fa/disable?code=${encodeURIComponent(disableCode)}`);
      setUser(prev => prev ? { ...prev, totp_enabled: false } : prev);
      setDisableCode('');
      addToast('success', '2FA disabled.');
    } catch {
      addToast('error', 'Invalid code - could not disable 2FA.');
    } finally {
      setTfaSaving(false);
    }
  }

  // ── GDPR export ───────────────────────────────────────────────────────────────

  function handleExport() {
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    const url = `${API_BASE}/api/v1/auth/me/export`;
    const a = document.createElement('a');
    a.href = token ? `${url}?token=${token}` : url;
    a.download = 'phaemos-data-export.json';
    a.click();
  }

  // ── Delete account ────────────────────────────────────────────────────────────

  async function handleDeleteAccount() {
    try {
      await api.delete('/auth/me');
      localStorage.removeItem('token');
      window.location.href = '/';
    } catch {
      addToast('error', 'Failed to delete account.');
    }
  }

  // ── Render helpers ────────────────────────────────────────────────────────────

  const navItems: { key: Section; label: string }[] = [
    { key: 'profile',  label: 'Profile' },
    { key: 'security', label: 'Security' },
    { key: 'twofa',    label: 'Two-Factor Auth' },
    { key: 'data',     label: 'Your Data' },
  ];

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-950 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-950 text-surface-100 p-6">
      <div className="max-w-3xl mx-auto">
        <h1 className="text-2xl font-semibold mb-6">Account</h1>

        {/* Section nav */}
        <nav className="flex gap-1 mb-8 border-b border-surface-800 pb-0">
          {navItems.map(item => (
            <button
              key={item.key}
              onClick={() => setActiveSection(item.key)}
              className={[
                'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
                activeSection === item.key
                  ? 'border-primary-500 text-primary-400'
                  : 'border-transparent text-surface-400 hover:text-surface-200',
              ].join(' ')}
            >
              {item.label}
            </button>
          ))}
        </nav>

        {/* ── Profile section ── */}
        {activeSection === 'profile' && (
          <section>
            <h2 className="text-lg font-medium mb-4">Profile details</h2>
            <form onSubmit={handleProfileSave} className="space-y-4 max-w-md">
              <div>
                <label className="block text-sm text-surface-400 mb-1">Display name</label>
                <input
                  type="text"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Your name"
                  className="w-full bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-primary-500"
                />
              </div>
              <div>
                <label className="block text-sm text-surface-400 mb-1">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                  className="w-full bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-primary-500"
                />
              </div>
              <div>
                <label className="block text-sm text-surface-400 mb-1">Phone number</label>
                <input
                  type="tel"
                  value={phone}
                  onChange={e => setPhone(e.target.value)}
                  placeholder="+44 7700 000000"
                  className="w-full bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-primary-500"
                />
              </div>
              {user?.oauth_provider && (
                <p className="text-xs text-surface-500">
                  Connected via {user.oauth_provider}. Email changes are managed through your provider.
                </p>
              )}
              <button
                type="submit"
                disabled={profileSaving}
                className="px-4 py-2 bg-primary-600 hover:bg-primary-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
              >
                {profileSaving ? 'Saving...' : 'Save changes'}
              </button>
            </form>

            {/* OAuth social login */}
            <div className="mt-8 pt-6 border-t border-surface-800">
              <h3 className="text-sm font-medium text-surface-300 mb-3">Connect social accounts</h3>
              <div className="flex flex-wrap gap-3">
                <a
                  href={`${API_BASE}/api/v1/auth/google`}
                  className="flex items-center gap-2 px-4 py-2 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-sm transition-colors"
                >
                  <span>G</span> Google
                </a>
                <a
                  href={`${API_BASE}/api/v1/auth/github`}
                  className="flex items-center gap-2 px-4 py-2 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-sm transition-colors"
                >
                  <span>GH</span> GitHub
                </a>
                <a
                  href={`${API_BASE}/api/v1/auth/apple`}
                  className="flex items-center gap-2 px-4 py-2 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-sm transition-colors"
                >
                  <span>A</span> Apple
                </a>
              </div>
            </div>
          </section>
        )}

        {/* ── Security section ── */}
        {activeSection === 'security' && (
          <section>
            <h2 className="text-lg font-medium mb-4">Change password</h2>
            {user?.oauth_provider ? (
              <p className="text-sm text-surface-400">
                Your account uses {user.oauth_provider} for authentication. Password login is not enabled.
              </p>
            ) : (
              <form onSubmit={handlePasswordChange} className="space-y-4 max-w-md">
                <div>
                  <label className="block text-sm text-surface-400 mb-1">Current password</label>
                  <input
                    type="password"
                    value={oldPassword}
                    onChange={e => setOldPassword(e.target.value)}
                    required
                    autoComplete="current-password"
                    className="w-full bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-primary-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-surface-400 mb-1">New password</label>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={e => setNewPassword(e.target.value)}
                    required
                    autoComplete="new-password"
                    minLength={8}
                    className="w-full bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-primary-500"
                  />
                  <p className="mt-1 text-xs text-surface-500">Min. 8 characters, one uppercase, one digit.</p>
                </div>
                <div>
                  <label className="block text-sm text-surface-400 mb-1">Confirm new password</label>
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={e => setConfirmPassword(e.target.value)}
                    required
                    autoComplete="new-password"
                    className="w-full bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-primary-500"
                  />
                </div>
                <button
                  type="submit"
                  disabled={passwordSaving}
                  className="px-4 py-2 bg-primary-600 hover:bg-primary-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
                >
                  {passwordSaving ? 'Updating...' : 'Update password'}
                </button>
              </form>
            )}
          </section>
        )}

        {/* ── 2FA section ── */}
        {activeSection === 'twofa' && (
          <section>
            <h2 className="text-lg font-medium mb-2">Two-factor authentication</h2>
            <p className="text-sm text-surface-400 mb-6">
              {user?.totp_enabled
                ? 'Two-factor authentication is currently enabled.'
                : 'Add an extra layer of security using an authenticator app (e.g. Google Authenticator, Authy).'}
            </p>

            {!user?.totp_enabled && !qrCode && (
              <button
                onClick={handle2faEnable}
                disabled={tfaSaving}
                className="px-4 py-2 bg-primary-600 hover:bg-primary-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
              >
                {tfaSaving ? 'Loading...' : 'Enable 2FA'}
              </button>
            )}

            {!user?.totp_enabled && qrCode && (
              <div className="space-y-4 max-w-md">
                <p className="text-sm text-surface-300">
                  Scan this QR code with your authenticator app, then enter the 6-digit code below to confirm.
                </p>
                {/* next/image does not support data: URIs - base64 QR codes must use <img> */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`data:image/png;base64,${qrCode}`}
                  alt="2FA QR code"
                  className="w-48 h-48 rounded-lg"
                />
                <form onSubmit={handle2faConfirm} className="space-y-3">
                  <input
                    type="text"
                    value={totpCode}
                    onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="000000"
                    maxLength={6}
                    className="w-40 bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm text-center tracking-widest focus:outline-none focus:border-primary-500"
                  />
                  <div className="flex gap-2">
                    <button
                      type="submit"
                      disabled={tfaSaving || totpCode.length < 6}
                      className="px-4 py-2 bg-success-600 hover:bg-success-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
                    >
                      {tfaSaving ? 'Verifying...' : 'Confirm'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setQrCode(null); setTotpCode(''); }}
                      className="px-4 py-2 bg-surface-700 hover:bg-surface-600 rounded-lg text-sm font-medium transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              </div>
            )}

            {user?.totp_enabled && (
              <div className="space-y-4 max-w-md">
                <div className="flex items-center gap-2 text-success-400 text-sm">
                  <span className="w-2 h-2 rounded-full bg-success-400 inline-block" />
                  2FA is active
                </div>
                <form onSubmit={handle2faDisable} className="space-y-3">
                  <p className="text-sm text-surface-400">Enter your current authenticator code to disable 2FA.</p>
                  <input
                    type="text"
                    value={disableCode}
                    onChange={e => setDisableCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="000000"
                    maxLength={6}
                    className="w-40 bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm text-center tracking-widest focus:outline-none focus:border-primary-500"
                  />
                  <button
                    type="submit"
                    disabled={tfaSaving || disableCode.length < 6}
                    className="px-4 py-2 bg-critical-600 hover:bg-critical-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
                  >
                    {tfaSaving ? 'Disabling...' : 'Disable 2FA'}
                  </button>
                </form>
              </div>
            )}
          </section>
        )}

        {/* ── Data section ── */}
        {activeSection === 'data' && (
          <section className="space-y-8">
            {/* GDPR export */}
            <div>
              <h2 className="text-lg font-medium mb-2">Export your data</h2>
              <p className="text-sm text-surface-400 mb-4">
                Download a JSON file containing your profile, devices, and tickets in a portable format.
              </p>
              <button
                onClick={handleExport}
                className="px-4 py-2 bg-surface-700 hover:bg-surface-600 rounded-lg text-sm font-medium transition-colors"
              >
                Download data export
              </button>
            </div>

            {/* Delete account */}
            <div className="pt-6 border-t border-surface-800">
              <h2 className="text-lg font-medium text-critical-400 mb-2">Delete account</h2>
              <p className="text-sm text-surface-400 mb-4">
                Permanently deletes your account and anonymises your tickets. This cannot be undone.
              </p>
              {!showDeleteConfirm ? (
                <button
                  onClick={() => {
                    setShowDeleteConfirm(true);
                    setTimeout(() => deleteInputRef.current?.focus(), 50);
                  }}
                  className="px-4 py-2 bg-critical-700 hover:bg-critical-600 rounded-lg text-sm font-medium transition-colors"
                >
                  Delete my account
                </button>
              ) : (
                <div className="space-y-3 max-w-md">
                  <p className="text-sm text-surface-300">
                    Type <strong className="text-critical-400">DELETE</strong> to confirm.
                  </p>
                  <input
                    ref={deleteInputRef}
                    type="text"
                    value={deleteConfirmText}
                    onChange={e => setDeleteConfirmText(e.target.value)}
                    placeholder="DELETE"
                    className="w-full bg-surface-800 border border-critical-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-critical-500"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={handleDeleteAccount}
                      disabled={deleteConfirmText !== 'DELETE'}
                      className="px-4 py-2 bg-critical-600 hover:bg-critical-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
                    >
                      Confirm delete
                    </button>
                    <button
                      onClick={() => { setShowDeleteConfirm(false); setDeleteConfirmText(''); }}
                      className="px-4 py-2 bg-surface-700 hover:bg-surface-600 rounded-lg text-sm font-medium transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
