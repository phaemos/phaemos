-- migration 041: a machine's ambient reference on another node
-- another node in the same place whose air temperature the anomaly model uses as this machine's ambient reference, so a warmer
-- room is not read as a warmer machine. Null means none. Conditional, so a second run takes no lock
SET lock_timeout = '3s';

SELECT 'ALTER TABLE devices ADD COLUMN IF NOT EXISTS ambient_source_id UUID REFERENCES devices(id) ON DELETE SET NULL'
WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'devices' AND column_name = 'ambient_source_id'
) \gexec
