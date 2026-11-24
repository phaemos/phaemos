-- migration 019: why a webhook was switched off
-- delivery now checks each address again and switches off a webhook whose address is no longer
-- safe to call. The reason is kept here so an admin can see it.
-- conditional with a lock timeout, so a re-run on an up-to-date database takes no lock (ALTER TABLE takes an
-- exclusive lock even when the column exists).

SET lock_timeout = '5s';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'webhooks' AND column_name = 'disabled_reason'
    ) THEN
        ALTER TABLE webhooks ADD COLUMN disabled_reason TEXT;
    END IF;
END
$$;
