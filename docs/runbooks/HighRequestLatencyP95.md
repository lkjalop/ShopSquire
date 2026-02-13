# Runbook: HighRequestLatencyP95

Alert: P95 HTTP latency > 750ms for 5m

Steps:
- Check Grafana panel: HTTP latency timeseries; identify endpoints with spikes
- Inspect recent deployments or config changes
- Verify database health: connections, slow queries; check `shopsquire_db_query_duration_seconds`
- Check Redis health, saturation, and circuit breaker metrics
- Scale API pods (if K8s) or increase resources; enable rule-based fallback for agents
- If external dependencies degrade, enable `DEGRADATION.force_rules` and reduce LLM usage
- Acknowledge alert in AlertManager; create ticket if sustained (>30m)
