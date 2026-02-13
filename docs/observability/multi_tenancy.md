# Observability Multi-Tenancy & Privacy

## Goals
- Isolate tenant metrics while enabling MSP/ops rollups
- Enforce least-privilege access; prevent cross-tenant leakage

## Metrics strategy
- Emit tenant labels only where justified; prefer coarse labels for global panels
- Use per-tenant histograms: `shopsquire_cv_provider_latency_tenant_seconds`, `shopsquire_fraud_provider_latency_tenant_seconds`
- Add Grafana variable `tenant` and default to `.*` for MSP views
- For tenant dashboards, pre-filter to the specific tenant and hide the selector

## Access control
- Grafana:
  - Separate dashboards per role; folder-level permissions
  - Consider per-tenant data sources or enforced query filters (e.g., Grafana query permissions)
- Backend:
  - Add middleware to validate `tenant_id` on incoming requests
  - Redact/mask tenant labels for non-authorized roles
- API Keys / Tokens:
  - Scoped per tenant; rotate regularly; rate limit by tenant

## Privacy safeguards
- Audit access to dashboards and sensitive queries
- Anomaly detection for unusual query volumes or label scans
- Limit raw event payloads; store only necessary dimensions

## Incident response
- Alerts on cross-tenant data exfil indicators
- SOP to revoke tokens and quarantine dashboards

## Next steps
- Map roles → dashboard folders and data sources
- Add automated tests for label redaction paths
- Document tenant onboarding and dashboard provisioning