-- Migration 006: webhook integrations
-- I use IF NOT EXISTS guards throughout so this migration is idempotent and
-- safe to rerun on a database that was partially migrated.

CREATE TABLE IF NOT EXISTS webhooks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(200) NOT NULL,
    url         TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    -- optional Jinja-style template; NULL means use the built-in default format
    template    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
