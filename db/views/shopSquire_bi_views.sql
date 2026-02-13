CREATE OR REPLACE VIEW bi_decisions_daily AS
SELECT DATE(valid_from) AS day, COUNT(*) AS decision_count
FROM decision_logs
GROUP BY DATE(valid_from)
ORDER BY day DESC;

CREATE OR REPLACE VIEW bi_security_daily AS
SELECT DATE(event_time) AS day, severity, COUNT(*) AS event_count
FROM security_events
GROUP BY DATE(event_time), severity
ORDER BY day DESC;

CREATE OR REPLACE VIEW bi_orders_daily AS
SELECT DATE(created_at) AS day, status, COUNT(*) AS order_count, SUM(total_cents) / 100.0 AS gross_usd
FROM orders
GROUP BY DATE(created_at), status
ORDER BY day DESC;

CREATE OR REPLACE VIEW bi_inventory_top AS
SELECT p.sku, p.name, i.stock
FROM products p
JOIN inventory i ON i.product_id = p.id
ORDER BY i.stock DESC;
