-- migration 038: service accounts
-- users.is_service marks an account that belongs to an integration. It has a role and can own API tokens and it cannot sign in:
-- no password, provider link, two-step, session, invitation or reset link and the sign-in route answers for it exactly as for
-- an unknown address. Existing rows are not service accounts.
-- api_tokens.created_by is the account that made the token. For a token on a service account that is the admin who did, so the
-- audit trail and the token list can say who. It becomes NULL when that person is removed and the token lives on.
-- every statement is conditional, so a re-run on an up-to-date database changes nothing and a change that has to wait gives up
-- after 5 seconds. It needs the table owner and no superuser right.

SET lock_timeout = '5s';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = 'is_service'
    ) THEN
        ALTER TABLE users ADD COLUMN is_service BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    IF to_regclass('api_tokens') IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'api_tokens' AND column_name = 'created_by'
    ) THEN
        ALTER TABLE api_tokens ADD COLUMN created_by UUID REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END
$$;
