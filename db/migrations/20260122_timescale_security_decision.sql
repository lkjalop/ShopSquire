-- TimescaleDB migration for security_events and decision_logs
-- Non-destructive: adds timestamptz columns, creates hypertables, policies and aggregates.
-- Run on PostgreSQL with TimescaleDB installed. Not applicable to SQLite.

BEGIN;

-- Enable extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Add timestamptz columns (if missing)
ALTER TABLE IF EXISTS security_events
  ADD COLUMN IF NOT EXISTS event_ts TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE IF EXISTS decision_logs
  ADD COLUMN IF NOT EXISTS system_from_ts TIMESTAMPTZ DEFAULT NOW();

-- Backfill from existing TEXT columns when parsable
UPDATE security_events
  SET event_ts = COALESCE(NULLIF(event_time, '')::timestamptz, event_ts)
  WHERE event_time IS NOT NULL;

UPDATE decision_logs
  SET system_from_ts = COALESCE(NULLIF(system_from, '')::timestamptz, system_from_ts)
  WHERE system_from IS NOT NULL;

-- Create hypertables (idempotent via try/catch)
DO $$
BEGIN
  PERFORM create_hypertable('security_events', 'event_ts', if_not_exists => TRUE);
EXCEPTION WHEN others THEN NULL;
END$$;

DO $$
BEGIN
  PERFORM create_hypertable('decision_logs', 'system_from_ts', if_not_exists => TRUE);
EXCEPTION WHEN others THEN NULL;
END$$;

-- Compression policies
ALTER TABLE security_events SET (timescaledb.compress);
SELECT add_compression_policy('security_events', INTERVAL '7 days') ON CONFLICT DO NOTHING;

ALTER TABLE decision_logs SET (timescaledb.compress);
SELECT add_compression_policy('decision_logs', INTERVAL '14 days') ON CONFLICT DO NOTHING;

-- Retention policies
SELECT add_retention_policy('security_events', INTERVAL '180 days') ON CONFLICT DO NOTHING;
SELECT add_retention_policy('decision_logs', INTERVAL '180 days') ON CONFLICT DO NOTHING;

-- Continuous aggregates (5m buckets)
CREATE MATERIALIZED VIEW IF NOT EXISTS sec_events_5m
WITH (timescaledb.continuous) AS
SELECT time_bucket('5 minutes', event_ts) AS bucket,
       severity,
       COUNT(*) AS c
FROM security_events
GROUP BY bucket, severity;

CREATE MATERIALIZED VIEW IF NOT EXISTS decisions_5m
WITH (timescaledb.continuous) AS
SELECT time_bucket('5 minutes', system_from_ts) AS bucket,
       agent_name,
       COUNT(*) AS c
FROM decision_logs
GROUP BY bucket, agent_name;

-- Refresh policies for aggregates
SELECT add_continuous_aggregate_policy('sec_events_5m',
    start_offset => INTERVAL '2 hours',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes')
ON CONFLICT DO NOTHING;

SELECT add_continuous_aggregate_policy('decisions_5m',
    start_offset => INTERVAL '2 hours',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes')
ON CONFLICT DO NOTHING;

COMMIT;
