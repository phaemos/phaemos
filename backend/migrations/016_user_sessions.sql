-- migration 016: server-side sign-in sessions
-- each refresh token now names a row here, so signing out ends that one session and a copied
-- refresh token stops working. The token is swapped for a new one on every use (current_jti) and
-- presenting an older one is treated as theft and revokes the session.
-- the clean-up job should delete expired rows. A revoked row is kept until it expires so a token
-- that was stolen before the revoke is still seen as revoked:
--   DELETE FROM user_sessions WHERE expires_at < now() - interval '1 day';
--
-- deploy.sh and `make migrate` run every file on every deploy. Each statement is conditional, so a database that is
-- up to date is only read and no lock is taken and lock_timeout makes a change that has to wait give up after
-- 5 seconds instead of queueing every other statement behind it.

SET lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('user_sessions') IS NULL THEN
        CREATE TABLE user_sessions (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            current_jti  VARCHAR(64) NOT NULL,
            created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            last_used_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            expires_at   TIMESTAMP WITH TIME ZONE NOT NULL,
            revoked_at   TIMESTAMP WITH TIME ZONE
        );
    END IF;
    IF to_regclass('idx_user_sessions_user') IS NULL THEN
        CREATE INDEX idx_user_sessions_user ON user_sessions (user_id);
    END IF;
    IF to_regclass('idx_user_sessions_expires') IS NULL THEN
        CREATE INDEX idx_user_sessions_expires ON user_sessions (expires_at);
    END IF;
END
$$;
