-- migration 010: session and one-time code columns for sign-in
-- token_version: every token carries it, so raising it ends all of a user's sessions.
-- totp_last_step: the last accepted one-time code step, so no code is accepted twice.
-- every statement is guarded, so re-running the file is safe. `make migrate`
-- applies it to a running database; a fresh database gets it at startup.

ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_last_step BIGINT;
