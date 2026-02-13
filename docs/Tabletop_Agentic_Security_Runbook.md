# Tabletop + Runbook: Agentic Security Demo

## Objective
Demonstrate that the platform is not only detecting attacks, but enforcing separation of duties and producing audit-grade evidence.

## Roles (Demo)
- Operator: runs scenarios and shows UI/metrics.
- Security Analyst: reviews incidents, approves playbook changes.
- Finance/Ops: validates out-of-band verification steps (simulated).

## Scenario 1: Email BEC With Payment Change
1. Send safe synthetic payload to `POST /api/v1/email_security/evaluate`.
2. Verify response includes `tags`, `reasons`, `risk_band`, `playbook.id`.
3. Confirm a playbook run exists via trace events (decision id) and playbook run steps.
4. Confirm incident is visible via admin endpoints (incidents and security events).

## Scenario 2: CV Robustness Gate
1. Upload an image to `POST /api/v1/cv/upload` (can be benign).
2. Verify response includes `robustness` fields and `evidence_tags`.
3. If dual OCR is enabled and disagreement detected, show escalation actions.

## Scenario 3: Agent Outbound Email C2 Pattern
1. Simulate outbound agent emails: `POST /api/v1/admin/email_security/outbound/simulate`.
2. Show anomaly reasons: `GET /api/v1/admin/email_security/outbound/anomalies`.
3. Explain containment step (next): suspend agent identity / revoke token (policy-driven).

## Evidence Checklist (What To Screenshot / Export)
- API JSON for each scenario (response + trace id/decision id).
- Admin pages / endpoints:
  - `GET /api/v1/admin/security/events`
  - `GET /api/v1/admin/playbooks/trail/PB-PAYMENT-FRAUD`
  - `GET /api/v1/admin/email_security/outbound/anomalies`
- Grafana panels showing event counts and signal counters (if enabled).

