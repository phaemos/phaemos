'use client';

import { useRouter } from 'next/navigation';

export default function LogoutButton() {
  const router = useRouter();

  function handleLogout() {
    // I clear both storage locations so neither the axios interceptor nor
    // the edge middleware thinks the user is still authenticated.
    localStorage.removeItem('token');
    document.cookie = 'token=; path=/; max-age=0; SameSite=Strict';
    router.push('/login');
  }

  return (
    <button
      onClick={handleLogout}
      className="text-sm text-surface-600 dark:text-surface-400 hover:text-critical-600 dark:hover:text-critical-400 transition-colours"
    >
      Sign out
    </button>
  );
}
