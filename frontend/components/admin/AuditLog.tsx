'use client';

// TODO: implement this component - it needs the GET /api/v1/audit admin
// endpoint which should return a paginated list of audit events (user logins,
// config changes, alert acknowledgements). Wire up once that route exists and
// the admin role guard is in place.

// I stub this now so the admin layout compiles and the audit section occupies
// its designated grid slot even before the backend work is done.

export default function AuditLog() {
  return (
    <div className="rounded-xl border border-gray-700 bg-white/5 p-6 text-gray-400 text-sm">
      Audit log table - TODO: implement
    </div>
  );
}
