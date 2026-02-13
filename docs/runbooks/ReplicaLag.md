# Replica Lag Runbook

Purpose: Detect and mitigate high read replica lag to protect read routing and freshness.

- Signals: `db_replica_lag_seconds` (or vendor‐specific), read routing error rates, stale read incidents.
- SLO: p95 replica lag < 1s; p99 < 3s during business hours.
- Alerts:
  - Warning: lag_p95 > 1s for 10m
  - Critical: lag_p99 > 3s for 5m

Actions:
- Switch reads to primary for affected tenants; reduce heavy analytics queries.
- Enable degradation policies for non‐critical endpoints (caching/short responses).
- Investigate replication pipeline health: I/O, WAL backlog, network throughput.

Checklist:
- Verify failover policy applies: route reads to healthy node.
- Confirm dashboard panels show lag time series and routing distribution.
- Review slow queries; apply indices or materialized views as needed.

Rollback:
- Restore read routing after lag recovers below SLO.
- Revert temporary query caps and cache TTL changes.
