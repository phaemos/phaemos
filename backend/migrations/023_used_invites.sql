-- migration 023: invitations that have been used
-- an invitation token is not stored, so it was refused only while an account with its email existed. Deleting that
-- account inside the 48 hours made the same link work again. Each accepted invitation is now recorded by the hash of
-- its token and refused a second time. The clean-up job can delete rows older than the token's life:
--   DELETE FROM used_invites WHERE used_at < now() - interval '3 days';
-- conditional with a lock timeout, so a re-run takes no lock.

SET lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('used_invites') IS NULL THEN
        CREATE TABLE used_invites (
            token_hash VARCHAR(64) PRIMARY KEY,
            used_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    END IF;
END
$$;
