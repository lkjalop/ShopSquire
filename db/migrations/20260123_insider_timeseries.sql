-- Add actor fields to decision_logs and create Timescale hypertable for security timeseries
-- Alters are safe (IF NOT EXISTS checks where possible)

ALTER TABLE IF EXISTS decision_logs ADD COLUMN actor_id TEXT;
ALTER TABLE IF EXISTS decision_logs ADD COLUMN actor_role TEXT;
ALTER TABLE IF EXISTS decision_logs ADD COLUMN event_type TEXT;

-- Security observer timeseries table (time-series for risk metrics)
CREATE TABLE IF NOT EXISTS security_observer_timeseries (
  time TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_id TEXT,
  severity TEXT,
  risk_adj DOUBLE PRECISION,
  insider_score DOUBLE PRECISION,
  tenant_id TEXT
);

-- Create hypertable (TimescaleDB). If running on SQLite or plain Postgres without Timescale, this will fail; run conditionally in deployment.
SELECT create_hypertable('security_observer_timeseries', 'time', if_not_exists => TRUE);

-- Retention policy: keep 90 days of high-res data
SELECT add_retention_policy('security_observer_timeseries', INTERVAL '90 days', if_not_exists => TRUE);
