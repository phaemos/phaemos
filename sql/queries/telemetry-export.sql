-- telemetry-export.sql
-- I use this query to export all telemetry data to a CSV file for ML model training.
-- Run from psql: \copy (SELECT ...) TO '/tmp/telemetry.csv' WITH CSV HEADER
-- Or: psql $DATABASE_URL -f sql/queries/telemetry-export.sql
--
-- Dependencies: devices and telemetry tables must exist.
-- Safe to run on production (read-only).

SELECT
    t.id,
    d.name                AS device_name,
    d.type                AS device_type,
    d.location,
    t.temperature,
    t.humidity,
    t.vibration_x,
    t.vibration_y,
    t.vibration_z,
    t.light_level,
    t.anomaly_score,
    t.is_anomaly,
    t.recorded_at
FROM telemetry t
JOIN devices d ON d.id = t.device_id
ORDER BY t.recorded_at ASC;
