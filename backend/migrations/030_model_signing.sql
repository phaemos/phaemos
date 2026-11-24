-- 030: a record, outside the model folder, that a signed anomaly model has been saved on this deployment.
-- An unsigned old-format bundle is accepted only while this table is empty. Safe to run again.
CREATE TABLE IF NOT EXISTS model_signing (
    id       INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    first_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
