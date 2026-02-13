# Data Retention and Disposal (MVP)

- Security Events: retain 90 days in `security_events`; summarize older data.
- Decision Logs: retain 180 days; redact PII via log filter; archive to cold storage.
- Incidents/Tickets: retain 1 year for audit; remove raw payloads after 30 days.
- Webhooks: keep hashes and metadata 30 days; delete bodies unless explicitly needed.
- LLM Outputs: store only when `SECURITY_EVENT_PERSIST_CONTENT=true` for debugging; default off.

Disposal Procedures
- Automated jobs purge old rows safely in off-peak hours.
- On request, delete tenant data across tables and object storage within 30 days.
- Verify deletions by sampling and cross-checking index counts.

Access Controls
- Limit read access to observability indexes and `decision_logs` to security and SRE roles.
- Enable audit logging on access to sensitive tables.
