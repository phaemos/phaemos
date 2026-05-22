-- device-summary.sql
-- I use this query to get a quick overview of all devices: their current status,
-- last reading values and how recently they were seen.
-- Safe to run on production (read-only).

SELECT
    d.id,
    d.name,
    d.type,
    d.location,
    d.status,
    d.last_seen,
    EXTRACT(EPOCH FROM (NOW() - d.last_seen)) / 60 AS minutes_since_last_seen,
    t.temperature,
    t.humidity,
    t.vibration_x,
    t.anomaly_score,
    t.is_anomaly,
    t.recorded_at                           AS last_reading_at
FROM devices d
LEFT JOIN LATERAL (
    -- I use a lateral join to fetch only the most recent telemetry row per device
    -- without a slow correlated subquery.
    SELECT *
    FROM telemetry
    WHERE device_id = d.id
    ORDER BY recorded_at DESC
    LIMIT 1
) t ON TRUE
ORDER BY d.last_seen DESC NULLS LAST;
