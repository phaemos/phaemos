-- anomaly-report.sql
-- I use this query to get a summary of anomaly events per device over a given period.
-- Useful for reviewing ML model performance and identifying problem machines.
-- Safe to run on production (read-only).
--
-- Adjust the interval filter as needed.

SELECT
    d.name                                  AS device_name,
    d.location,
    COUNT(*)                                AS total_readings,
    SUM(CASE WHEN t.is_anomaly THEN 1 ELSE 0 END) AS anomaly_count,
    ROUND(
        100.0 * SUM(CASE WHEN t.is_anomaly THEN 1 ELSE 0 END) / COUNT(*),
        2
    )                                       AS anomaly_rate_pct,
    MAX(t.anomaly_score)                    AS max_anomaly_score,
    MIN(t.recorded_at)                      AS first_reading,
    MAX(t.recorded_at)                      AS last_reading
FROM telemetry t
JOIN devices d ON d.id = t.device_id
WHERE t.recorded_at >= NOW() - INTERVAL '7 days'
GROUP BY d.id, d.name, d.location
ORDER BY anomaly_count DESC;
