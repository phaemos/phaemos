-- Migration 008: device tags (PostgreSQL ARRAY)
-- I use ARRAY rather than a join table because the tag set is small and
-- querying with `tag = ANY(tags)` is fast with a GIN index at this scale.

ALTER TABLE devices ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS ix_devices_tags ON devices USING GIN(tags);
