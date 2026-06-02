-- 003_multi_tenant.sql
-- Run with: psql $DATABASE_URL -f migrations/003_multi_tenant.sql
--
-- I use IF NOT EXISTS guards so this script is idempotent - safe to run more than once.

-- ---------------------------------------------------------------------------
-- devices: multi-tenant ownership column
-- I keep owner_id nullable so pre-existing devices stay valid after the migration.
-- Unowned devices (owner_id IS NULL) are treated as shared/unassigned and are
-- visible to all technicians, not just admins.
-- ON DELETE SET NULL means deleting a user orphans their devices rather than
-- cascading the delete, which would be a data-loss risk.
-- ---------------------------------------------------------------------------
ALTER TABLE devices
    ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE SET NULL;
