-- Migration 009: per-user RBAC permissions column
-- Adds a nullable JSON column to users for resource-level overrides.
-- NULL means "use role defaults"; a JSON object overrides specific capabilities.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS permissions JSONB;
