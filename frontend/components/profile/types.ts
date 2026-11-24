import { lookup } from '@/lib/lookup';

// the user as GET /auth/me and PATCH /auth/me answer (backend/app/schemas/user.py, UserResponse)
export interface UserProfile {
  id: string;
  name: string | null;
  email: string;
  role: string;
  phone_number: string | null;
  oauth_provider: string | null;
  totp_enabled: boolean;
  // false for an account that signs in through a provider. Absent from an API that predates it.
  has_password?: boolean;
  // false until the number on the account has been confirmed with a code. Alert texts go only to a confirmed number. Absent from an API
  // that predates it.
  phone_confirmed?: boolean;
  // true for 5 minutes after the person returned from their provider. Absent from an API that predates it.
  provider_signin_recent?: boolean;
}

// an account with a password proves itself with the password. A provider account has none.
export function hasPassword(user: UserProfile): boolean {
  return user.has_password ?? !user.oauth_provider;
}

export type UserChange = (patch: Partial<UserProfile>) => void;

// the readable names for the providers the API signs people in with
export const PROVIDER_NAMES: Record<string, string> = { google: 'Google', github: 'GitHub', microsoft: 'Microsoft' };

export function providerName(key: string | null): string {
  return key ? lookup(PROVIDER_NAMES, key) ?? key : '';
}
