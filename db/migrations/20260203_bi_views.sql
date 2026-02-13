-- BI materialized views (Postgres-ready)

-- Orders daily (revenue in currency units)
CREATE MATERIALIZED VIEW IF NOT EXISTS public.bi_orders_daily AS
SELECT
    DATE(oltp.orders.created_at) AS day,
    oltp.orders.status,
    COUNT(*) AS order_count,
    SUM(oltp.orders.total_cents) / 100.0 AS revenue
FROM oltp.orders
GROUP BY DATE(oltp.orders.created_at), oltp.orders.status;

CREATE INDEX IF NOT EXISTS idx_bi_orders_daily_day ON public.bi_orders_daily (day);

-- Decisions daily (attempts to surface avg confidence if present in input_data JSON)
CREATE MATERIALIZED VIEW IF NOT EXISTS public.bi_decisions_daily AS
SELECT
    DATE(audit.decision_audits.created_at) AS day,
    audit.decision_logs.agent_name AS agent_name,
    COUNT(*) AS decision_count,
    AVG( (audit.decision_logs.input_data->>'confidence')::double precision ) AS avg_confidence
FROM audit.decision_audits
LEFT JOIN audit.decision_logs ON audit.decision_logs.id::text = audit.decision_audits.decision_id::text
GROUP BY DATE(audit.decision_audits.created_at), audit.decision_logs.agent_name;

CREATE INDEX IF NOT EXISTS idx_bi_decisions_daily_day ON public.bi_decisions_daily (day);

-- Security events daily (fraud image hashes used as a simple signal source)
CREATE MATERIALIZED VIEW IF NOT EXISTS public.bi_security_daily AS
SELECT
    DATE(security.fraud_image_hashes.created_at) AS day,
    CASE WHEN security.fraud_image_hashes.confirmed_fraud THEN 'critical' ELSE 'info' END AS severity,
    'fraud_image' AS signal_type,
    COUNT(*) AS event_count
FROM security.fraud_image_hashes
GROUP BY DATE(security.fraud_image_hashes.created_at), severity, signal_type;

CREATE INDEX IF NOT EXISTS idx_bi_security_daily_day ON public.bi_security_daily (day);

-- Search funnel (requires `search_events` table)
CREATE MATERIALIZED VIEW IF NOT EXISTS public.bi_search_funnel AS
SELECT
    DATE((search_events.timestamp::timestamp)) AS day,
    search_events.query_cluster_id,
    COUNT(*) AS searches,
    SUM(CASE WHEN search_events.viewed_sku IS NOT NULL THEN 1 ELSE 0 END) AS views,
    SUM(COALESCE(search_events.added_to_cart, 0)) AS carts,
    SUM(COALESCE(search_events.purchased, 0)) AS purchases
FROM search_events
GROUP BY DATE((search_events.timestamp::timestamp)), search_events.query_cluster_id;

CREATE INDEX IF NOT EXISTS idx_bi_search_funnel_day ON public.bi_search_funnel (day);
