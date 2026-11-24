-- migration 022: what a session records
-- label: a coarse description of the browser, so a person can tell their sessions apart in a list.
-- provider_signin_at: when this session came back from the sign-in provider. It replaces the same time that
-- was kept on the user (migration 018), which any other session of that account could use. Only the session that
-- made the return counts as proof of ownership now.
-- every statement is conditional and there is a lock timeout, so a re-run takes no lock on an up-to-date database
-- and a change that has to wait gives up after 5 seconds. Without this a wait behind a reader on users queued the
-- sign-in queries behind it.

SET lock_timeout = '5s';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'user_sessions' AND column_name = 'label'
    ) THEN
        ALTER TABLE user_sessions ADD COLUMN label VARCHAR(80);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'user_sessions' AND column_name = 'provider_signin_at'
    ) THEN
        ALTER TABLE user_sessions ADD COLUMN provider_signin_at TIMESTAMP WITH TIME ZONE;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = 'provider_signin_at'
    ) THEN
        ALTER TABLE users DROP COLUMN provider_signin_at;
    END IF;
END
$$;
