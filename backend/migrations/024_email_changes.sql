-- migration 024: limits and trust for email changes
-- email_since: when the current sign-in address became the account's. NULL means the address was never unconfirmed
-- (an invitation went to it or a provider verified it) and existing rows stay NULL. The email change notice goes only
-- to an address that has been the sign-in address for an hour or is NULL, so a stranger's address cannot be mailed
-- by changing an account to it.
-- email_changes: one row per change, counted to limit changes per hour and per day.
-- every statement is conditional, so a deploy that runs this file again takes no lock on an up-to-date database.
-- A change that has to wait gives up after 5 seconds instead of queueing every other statement behind it.

SET lock_timeout = '5s';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = 'email_since'
    ) THEN
        ALTER TABLE users ADD COLUMN email_since TIMESTAMP WITH TIME ZONE;
    END IF;
    IF to_regclass('email_changes') IS NULL THEN
        CREATE TABLE email_changes (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            changed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
    END IF;
    IF to_regclass('idx_email_changes_user_time') IS NULL THEN
        CREATE INDEX idx_email_changes_user_time ON email_changes (user_id, changed_at);
    END IF;
END
$$;
