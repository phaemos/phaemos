-- migration 025: the previous refresh token of a session
-- previous_jti and rotated_at let a refresh token that was just swapped be accepted again for a few seconds, so two
-- tabs refreshing together are not mistaken for a stolen copy. Conditional and with a lock timeout, as in 024.

SET lock_timeout = '5s';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'user_sessions' AND column_name = 'previous_jti'
    ) THEN
        ALTER TABLE user_sessions ADD COLUMN previous_jti VARCHAR(64);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'user_sessions' AND column_name = 'rotated_at'
    ) THEN
        ALTER TABLE user_sessions ADD COLUMN rotated_at TIMESTAMP WITH TIME ZONE;
    END IF;
END
$$;
