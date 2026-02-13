-- BI materialized views (Postgres) and fallback views (SQLite).

-- Orders daily
CREATE MATERIALIZED VIEW IF NOT EXISTS bi_orders_daily AS
SELECT
  DATE(created_at) AS day,
  status,
  COUNT(*) AS order_count,
  SUM(total_cents) / 100.0 AS revenue
FROM orders
GROUP BY DATE(created_at), status;

-- Decisions daily
CREATE MATERIALIZED VIEW IF NOT EXISTS bi_decisions_daily AS
SELECT
  DATE(system_from) AS day,
  agent_name,
  COUNT(*) AS decision_count
FROM decision_logs
GROUP BY DATE(system_from), agent_name;

-- Security events daily
CREATE MATERIALIZED VIEW IF NOT EXISTS bi_security_daily AS
SELECT
  DATE(event_time) AS day,
  severity,
  COUNT(*) AS event_count
FROM security_events
GROUP BY DATE(event_time), severity;

-- Search funnel (requires search_events)
CREATE MATERIALIZED VIEW IF NOT EXISTS bi_search_funnel AS
SELECT
  DATE(event_time) AS day,
  COUNT(*) AS searches,
  SUM(CASE WHEN result_count > 0 THEN 1 ELSE 0 END) AS searches_with_results
FROM search_events
GROUP BY DATE(event_time);
