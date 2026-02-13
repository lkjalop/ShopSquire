# Monitoring SLOs

Target SLOs (initial):
- Request latency: p95 < 500ms, p99 < 900ms
- Error rate: 5xx < 1% over 5m
- Webhook signature failures: spike response within 5m
- Alert acknowledgement: < 5 minutes (critical), < 15 minutes (warning)
- Incident time-to-resolution: P1 < 4 hours, P2 < 24 hours

Measurement sources:
- Prometheus metrics (http latency, error rate, webhook verifications)
- AlertManager notifications (ACK timestamps)
- Incident and ticket metrics (P1/P2) in Grafana

Review cadence:
- Daily SLO dashboard review
- Weekly postmortem for breached SLOs
