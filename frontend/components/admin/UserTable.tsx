'use client';

// TODO: implement this component - it needs the GET /api/v1/auth/users admin
// endpoint which requires an admin-scoped JWT. Wire up once the auth middleware
// exposes a /users list route with appropriate role guard.

// I stub this now so the admin page imports and renders without errors while
// the backend endpoint is still being built.

export default function UserTable() {
  return (
    <div className="rounded-xl border border-gray-700 bg-white/5 p-6 text-gray-400 text-sm">
      User management table - TODO: implement
    </div>
  );
}
