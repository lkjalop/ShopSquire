# Runbook: ErrorRateHigh

Alert: 5xx responses exceed 5% over 5 minutes

Steps:
- Check API logs for stack traces (with redaction enabled)
- Inspect recent release for breaking changes
- Verify DB connectivity, migrations, and feature flags
- Roll back recent changes; apply feature flag kill-switch for risky endpoints
- Scale replicas; restart unhealthy pods
- Escalate to on-call; open P1 ticket if persisting >15m
