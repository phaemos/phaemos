-- migration 039: the anomaly change detector's state, per machine
-- the detector accumulates small deviations over time, so its state (about 1 kB of numbers) must survive between readings and be
-- shared by every worker. It lives on the device row beside stuck_state, read and written under the device lock an ingest post
-- already holds. Null means a fresh detector
SET lock_timeout = '3s';

SELECT 'ALTER TABLE devices ADD COLUMN IF NOT EXISTS detector_state JSONB'
WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'devices' AND column_name = 'detector_state'
) \gexec
