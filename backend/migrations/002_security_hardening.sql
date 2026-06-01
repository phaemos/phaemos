-- 002_security_hardening.sql
-- Run with: psql $DATABASE_URL -f migrations/002_security_hardening.sql
--
-- I use IF NOT EXISTS / IF EXISTS guards throughout so this script is
-- idempotent - safe to run more than once on an existing database.

-- ---------------------------------------------------------------------------
-- users: brute-force lockout columns
-- I track failed_login_attempts so the login route can lock an account after
-- 5 consecutive failures without having to store state in Redis or memory.
-- locked_until stores the absolute UTC timestamp when the lock expires so any
-- backend instance can evaluate it without coordination.
-- ---------------------------------------------------------------------------
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP WITH TIME ZONE;
