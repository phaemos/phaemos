-- migration 036: webhook format, signing secret and delivery state
-- format: 'chat' (a message for Slack, Discord or Teams, as before) or 'json' (the signed event body)
-- secret: the signing secret of a json webhook, encrypted by the application. Never read back by any route
-- last_delivery_at, last_status, last_error, consecutive_failures: kept by the delivery itself
-- every step is sent only when a catalogue check says it is needed, so a second run takes no lock
SET lock_timeout = '3s';

SELECT $q$
ALTER TABLE webhooks
    ADD COLUMN IF NOT EXISTS format               VARCHAR(10) NOT NULL DEFAULT 'chat',
    ADD COLUMN IF NOT EXISTS secret               TEXT,
    ADD COLUMN IF NOT EXISTS last_delivery_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_status          INTEGER,
    ADD COLUMN IF NOT EXISTS last_error           VARCHAR(40),
    ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'webhooks'
      AND column_name IN ('format', 'secret', 'last_delivery_at', 'last_status', 'last_error', 'consecutive_failures')
) < 6 \gexec
