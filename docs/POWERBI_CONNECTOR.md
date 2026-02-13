# PowerBI Connector Guide

## Connection
Use the PostgreSQL connector.

Recommended connection string:
```
Host=localhost;Port=5432;Database=shopsquire;Username=postgres;Password=postgres
```

## Example Queries

### Decisions per day
```sql
SELECT
  date_trunc('day', valid_from) AS day,
  count(*) AS decision_count
FROM decision_logs
GROUP BY day
ORDER BY day DESC;
```

### Security events by severity
```sql
SELECT
  severity,
  count(*) AS events
FROM security_events
GROUP BY severity
ORDER BY events DESC;
```

### Orders by status
```sql
SELECT
  status,
  count(*) AS order_count,
  sum(total_cents) / 100.0 AS gross_usd
FROM orders
GROUP BY status
ORDER BY order_count DESC;
```

### Recommendation decision quality (with policy version)
```sql
SELECT
  policy_version,
  count(*) AS decisions,
  avg(CASE WHEN execution_status = 'executed' THEN 1 ELSE 0 END) AS exec_rate
FROM decision_logs
GROUP BY policy_version
ORDER BY decisions DESC;
```

### Top products by inventory
```sql
SELECT
  p.sku,
  p.name,
  i.stock
FROM products p
JOIN inventory i ON i.product_id = p.id
ORDER BY i.stock DESC
LIMIT 20;
```

## Notes
- For large datasets, use incremental refresh by filtering on `created_at` or `valid_from`.
- Store read-only credentials for BI use in production.
