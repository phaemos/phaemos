-- migration 040: a person's verdict on a machine alert
-- true when a person confirmed the alert as a real fault, false when they said it was not one and null while nobody has said.
-- The anomaly model's training leaves out the readings taken while a model alert was open only when that alert was confirmed,
-- so an unconfirmed alert can no longer keep a machine from being retrained on a changed normal. Conditional, so a second run
-- takes no lock
SET lock_timeout = '3s';

SELECT 'ALTER TABLE alerts ADD COLUMN IF NOT EXISTS fault_confirmed BOOLEAN'
WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'alerts' AND column_name = 'fault_confirmed'
) \gexec
