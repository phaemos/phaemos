-- demo-devices.sql
-- I use this script to insert demo devices and alert rules for local development and demos.
-- Run ONLY on a local or development database - never on production.
--
-- Prerequisites: the devices, alert_rules tables must exist.
-- Idempotent: uses INSERT ... ON CONFLICT DO NOTHING so it is safe to run multiple times.

BEGIN;

-- I insert three demo devices representing different machine types.
INSERT INTO devices (id, name, location, type, api_key, status)
VALUES
    ('11111111-1111-1111-1111-111111111111', 'Motor A',       'Factory Floor',  'esp32',   'demo-key-motor-a',   'online'),
    ('22222222-2222-2222-2222-222222222222', 'Pump Unit 1',   'Pump Room',      'esp32',   'demo-key-pump-1',    'offline'),
    ('33333333-3333-3333-3333-333333333333', 'Conveyor Belt', 'Warehouse',      'arduino', 'demo-key-conveyor',  'warning')
ON CONFLICT (id) DO NOTHING;

-- I insert alert rules for each demo device.
INSERT INTO alert_rules (device_id, metric, condition, threshold, severity)
VALUES
    -- Motor A: alert if temperature exceeds 80C
    ('11111111-1111-1111-1111-111111111111', 'temperature', 'gt', 80.0, 'warning'),
    -- Motor A: alert if vibration_x exceeds 5g (bearing failure indicator)
    ('11111111-1111-1111-1111-111111111111', 'vibration_x', 'gt', 5.0,  'critical'),
    -- Pump Unit 1: alert if humidity exceeds 85% (condensation risk)
    ('22222222-2222-2222-2222-222222222222', 'humidity',    'gt', 85.0, 'warning'),
    -- Conveyor Belt: alert if temperature exceeds 60C
    ('33333333-3333-3333-3333-333333333333', 'temperature', 'gt', 60.0, 'warning')
ON CONFLICT DO NOTHING;

COMMIT;
