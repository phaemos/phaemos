-- migration 035: access tokens for scripts and the command line tool
-- one row for each token: the public id (the lookup), the account, a name the person chose, a scope (read, operate or admin),
-- the keyed hash of the secret (never the secret), the account's token_version when it was made and when it was made, used last,
-- expires or was revoked. A deactivated or removed account loses its tokens (the rows go with the account).
-- every statement is conditional, so a re-run on an up-to-date database changes nothing and a change that has to wait gives up
-- after 5 seconds instead of queueing every other statement behind it. It needs the table owner and no superuser right.

SET lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('api_tokens') IS NULL THEN
        CREATE TABLE api_tokens (
            id            VARCHAR(12) PRIMARY KEY,
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name          VARCHAR(60) NOT NULL,
            scope         VARCHAR(10) NOT NULL CHECK (scope IN ('read', 'operate', 'admin')),
            secret_hash   VARCHAR(64) NOT NULL,
            token_version INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            expires_at    TIMESTAMP WITH TIME ZONE NOT NULL,
            last_used_at  TIMESTAMP WITH TIME ZONE,
            revoked_at    TIMESTAMP WITH TIME ZONE
        );
    END IF;
    IF to_regclass('idx_api_tokens_user') IS NULL THEN
        CREATE INDEX idx_api_tokens_user ON api_tokens (user_id);
    END IF;
END
$$;
