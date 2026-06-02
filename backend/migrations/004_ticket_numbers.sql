-- Add a human-readable ticket number so support teams can reference tickets
-- as PHM-0001 instead of a UUID. SERIAL auto-increments from 1; the unique
-- index ensures no two tickets share the same number even under concurrent inserts.
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ticket_number SERIAL;
CREATE UNIQUE INDEX IF NOT EXISTS tickets_ticket_number_key ON tickets(ticket_number);
