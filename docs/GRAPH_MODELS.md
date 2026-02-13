# Graph Models: ContextGraph & PolicyGraph

This document outlines a per-tenant graph approach for richer context and policy evaluation across the platform.

## ContextGraph (per tenant/store)

Purpose:
- Represent entities (customers, orders, products, tickets, images) and relationships (purchased, returned, reported, similar_to) to enable contextual reasoning.
- Power features like duplicate detection, co-occurrence, and relationship-aware recommendations.

Suggested schema (PostgreSQL):
- `cg_nodes(id UUID, tenant_id UUID, type TEXT, key TEXT, created_at TIMESTAMP)`
- `cg_edges(id UUID, tenant_id UUID, src_id UUID, dst_id UUID, type TEXT, weight FLOAT, created_at TIMESTAMP)`
- Index on `(tenant_id, type, key)` and `(tenant_id, src_id, dst_id, type)`.

Examples:
- Node: `image:{sha256}` or `product:{sku}`; Edge: `similar_to` with phash-derived weight.

## PolicyGraph (per tenant/store)

Purpose:
- Track company policies, compliance controls, and model governance across frameworks (PCI-DSS, ISO 27001/42001, NIST AI RMF, GDPR, EU AI Act).
- Express policy nodes and control rules that evaluate decision contexts and drive approvals/escalations.

Suggested schema (PostgreSQL):
- `pg_policies(id UUID, tenant_id UUID, name TEXT, framework TEXT, version TEXT, enabled BOOL, created_at TIMESTAMP)`
- `pg_controls(id UUID, policy_id UUID, control_key TEXT, description TEXT, severity TEXT, enabled BOOL)`
- `pg_rules(id UUID, control_id UUID, rule TEXT, priority INT)`  // e.g., JSONata/SQL conditions on decision context
- `pg_evaluations(id UUID, decision_id UUID, control_id UUID, result TEXT, evaluated_at TIMESTAMP)`

Integration points:
- When agents write `decision_logs`, evaluate applicable `pg_controls` and record `pg_evaluations` with results (pass/fail/needs_approval).
- Use `framework` and `version` to align with audit requirements.

## Time-Series (TimescaleDB)

For high-volume events (security, decisions, metrics), use hypertables:
- `dl_timeseries(time TIMESTAMP, tenant_id UUID, agent_name TEXT, status TEXT, tags JSONB)`
- Convert to hypertable: `SELECT create_hypertable('dl_timeseries','time');`

Notes:
- TimescaleDB enables fast temporal queries and retention policies.
- Keep PII out of long-term time-series; store hashed identifiers.

## Compliance Mapping

Examples:
- PCI-DSS: log payment-related decisions, mask PAN; controls on approval flows.
- ISO 27001: security event logging, incident workflows, access controls.
- ISO 42001 (AI): model governance, bias checks, human-in-the-loop approvals.
- NIST AI RMF: risk categorization, control evaluation, outcome monitoring.
- GDPR/EU AI Act: data minimization, subject access/export via `privacy` router, risk-level gating for high-risk uses.

## Next Steps

- Add migrations for the tables above (optional Alembic).
- Implement `policy_evaluator` service to apply rules to `decision_logs` and emit `pg_evaluations`.
- Add admin views for compliance status per policy/control.
