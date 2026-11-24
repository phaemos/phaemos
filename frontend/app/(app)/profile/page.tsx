'use client';

import { useEffect, useState } from 'react';
import { useApiResource } from '@/hooks/useApiResource';
import ErrorNotice from '@/components/ui/ErrorNotice';
import PageHeader from '@/components/ui/PageHeader';
import { SkeletonRows } from '@/components/ui/Skeleton';
import AccountSection from '@/components/profile/AccountSection';
import PhoneSection from '@/components/profile/PhoneSection';
import PasswordSection from '@/components/profile/PasswordSection';
import TwoStepSection from '@/components/profile/TwoStepSection';
import ProvidersSection from '@/components/profile/ProvidersSection';
import SessionsSection from '@/components/profile/SessionsSection';
import TokensSection from '@/components/profile/TokensSection';
import { DeleteSection, ExportSection } from '@/components/profile/DataSection';
import type { UserProfile } from '@/components/profile/types';

// one page with a headed section for each thing a person can change. The sections are short and a person who
// comes to change one usually looks over the others, so they are not hidden behind tabs. Deleting the account is last.
export default function ProfilePage() {
  const { data, error, loading, retry } = useApiResource<UserProfile>('/auth/me', { what: 'Your profile' });

  return (
    <div className="max-w-2xl space-y-8">
      <PageHeader title="Profile" description="Your account, how you sign in and your data." />
      {loading && !data ? (
        <SkeletonRows rows={6} label="Loading your profile" />
      ) : error && !data ? (
        <ErrorNotice message={error} onRetry={retry} />
      ) : data ? (
        <Body initial={data} />
      ) : null}
    </div>
  );
}

// the forms start from the loaded user and keep their own copy, so a save updates the sections that read it
function Body({ initial }: { initial: UserProfile }) {
  const [user, setUser] = useState(initial);
  const change = (patch: Partial<UserProfile>) => setUser((u) => ({ ...u, ...patch }));

  // the sections appear after the profile has loaded, so an address like /profile#delete (where a provider sign-in sends the
  // person back to) has nothing to land on until now
  useEffect(() => {
    const id = window.location.hash.slice(1);
    if (id) document.getElementById(id)?.scrollIntoView();
  }, []);

  return (
    <div>
      <AccountSection user={user} onChange={change} />
      <PhoneSection user={user} onChange={change} />
      <PasswordSection user={user} />
      <TwoStepSection user={user} onChange={change} />
      <ProvidersSection user={user} />
      <SessionsSection />
      <TokensSection user={user} />
      <ExportSection />
      <DeleteSection user={user} />
    </div>
  );
}
