-- TimescaleDB continuous aggregates (optional)
-- Requires TimescaleDB extension enabled.

-- Orders per minute aggregate (example)
CREATE MATERIALIZED VIEW IF NOT EXISTS orders_per_minute
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', created_at) AS bucket, count(*) AS orders
FROM orders
GROUP BY bucket
WITH NO DATA;

-- Refresh policy: run every 5 minutes over last 1 hour
SELECT add_continuous_aggregate_policy('orders_per_minute',
  start_offset => INTERVAL '1 hour',
  end_offset => INTERVAL '5 minutes',
  schedule_interval => INTERVAL '5 minutes');

-- Decision logs hourly aggregate by status + agent
CREATE MATERIALIZED VIEW IF NOT EXISTS decision_hourly_mv
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 hour', valid_from) AS bucket,
  agent_name,
  execution_status,
  COUNT(*) AS count
FROM decision_logs
GROUP BY bucket, agent_name, execution_status
WITH NO DATA;

SELECT add_continuous_aggregate_policy('decision_hourly_mv',
  start_offset => INTERVAL '7 days',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour');

-- Security events daily aggregate by severity
CREATE MATERIALIZED VIEW IF NOT EXISTS security_daily_mv
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 day', event_time) AS bucket,
  severity,
  COUNT(*) AS count
FROM security_events
GROUP BY bucket, severity
WITH NO DATA;

SELECT add_continuous_aggregate_policy('security_daily_mv',
  start_offset => INTERVAL '30 days',
  end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day');

-- Approval rate by agent (hourly)
CREATE MATERIALIZED VIEW IF NOT EXISTS approvals_by_agent_hourly_mv
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 hour', valid_from) AS bucket,
  agent_name,
  COUNT(*) AS total,
  SUM(CASE WHEN execution_status IN ('approved','executed') THEN 1 ELSE 0 END) AS approved
FROM decision_logs
GROUP BY bucket, agent_name
WITH NO DATA;

SELECT add_continuous_aggregate_policy('approvals_by_agent_hourly_mv',
  start_offset => INTERVAL '7 days',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour');

-- Top products by customer tier (daily)
CREATE MATERIALIZED VIEW IF NOT EXISTS top_products_by_tier_daily_mv
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 day', valid_from) AS bucket,
  COALESCE(retrieved_context->>'customer_tier', 'unknown') AS customer_tier,
  sku,
  COUNT(*) AS count
FROM (
  SELECT
    valid_from,
    retrieved_context,
    jsonb_array_elements_text((proposed_action::jsonb)->'ranked_skus') AS sku
  FROM decision_logs
) t
GROUP BY bucket, customer_tier, sku
WITH NO DATA;

SELECT add_continuous_aggregate_policy('top_products_by_tier_daily_mv',
  start_offset => INTERVAL '30 days',
  end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day');

