-- migration 032: account controls, invitations in their own table and room for encrypted two-step secrets
-- users.is_active and users.deactivated_at: an admin can deactivate an account, which ends its sessions and stops it
--   signing in. Existing rows are active.
-- users.totp_secret becomes TEXT. A secret is now stored encrypted (`enc:v1:` and a token), which is longer than the
--   64 characters a plain secret needed. The rows themselves are encrypted by the API, which holds the key: it does
--   so at every start and `python -m app.scripts.encrypt_two_step_secrets` does it by hand. Both are safe to repeat.
-- invitations: one row for each invitation, holding the hash of its token (never the token), the role, who sent it
--   and when it expires, was used or was cancelled, so an admin can list and cancel one.
-- every statement is conditional, so a re-run on an up-to-date database takes no lock and a change that has to wait gives
-- up after 5 seconds instead of queueing every other statement behind it. It needs the table owner and no elevated right.

SET lock_timeout = '5s';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = 'is_active'
    ) THEN
        ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = 'deactivated_at'
    ) THEN
        ALTER TABLE users ADD COLUMN deactivated_at TIMESTAMP WITH TIME ZONE;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = 'totp_secret'
          AND data_type <> 'text'
    ) THEN
        ALTER TABLE users ALTER COLUMN totp_secret TYPE TEXT;
    END IF;
    IF to_regclass('invitations') IS NULL THEN
        CREATE TABLE invitations (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            token_hash   VARCHAR(64) NOT NULL UNIQUE,
            email        VARCHAR(150) NOT NULL,
            role         VARCHAR(20) NOT NULL,
            invited_by   UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            expires_at   TIMESTAMP WITH TIME ZONE NOT NULL,
            used_at      TIMESTAMP WITH TIME ZONE,
            cancelled_at TIMESTAMP WITH TIME ZONE
        );
    END IF;
    IF to_regclass('idx_invitations_email') IS NULL THEN
        CREATE INDEX idx_invitations_email ON invitations (email);
    END IF;
END
$$;
