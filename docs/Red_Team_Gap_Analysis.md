# ShopSquire Red Team Gap Analysis
## Production-Ready Demo Plan (As of February 10, 2026)

This document is the demo-facing security readiness view of ShopSquire.
It is explicitly scoped to proving deterministic detection, containment, auditability, and handoff interoperability (not building a full XDR).

## Canonical 10-Minute Demo Runbook

### Objective
Prove `detect -> route -> trace -> SIEM handoff -> ticket linkage` across 4 scenarios.

### Prerequisites (2 minutes)
- Set a real receiver (recommended for demo): `SIEM_WEBHOOK_URL` (Webhook.site) or `SPLUNK_HEC_URL`.
- Use owner/developer API key.
- Optional: set `X-Tenant-Id: demo-tenant`.

### Steps (8 minutes)
1. Show runbook metadata:
   - `GET /api/v1/admin/email_security/demo/runbook`
   - Expect: walkthrough steps and dashboard URLs.
2. Execute 4 attack scenarios in one call:
   - `POST /api/v1/admin/email_security/demo/runbook/execute`
   - Body: `{"tenant_id":"demo-tenant","scenarios":["bec","prompt_injection","canary","supplier_bank_change"]}`
   - Expect: each scenario returns route, decision/trace IDs, reasons, SIEM handoff flag.
3. Show incident funnel:
   - `GET /api/v1/admin/email_security/demo/funnel?tenant_id=demo-tenant`
   - Expect: detected count, routed counts, trace-linked count, ticketed count.
4. Show connector reliability:
   - `GET /api/v1/admin/email_security/connectors/reliability?hours=24`
   - Expect: sent/retrying/failed/dlq by target.
5. Show decision drilldown with taxonomy/tags:
   - `GET /api/v1/decisions/{decision_id}/query?include_events=true`
   - Expect: security/risk metadata, events, evidence tags, trace IDs.
6. Show ops readiness:
   - Email: `GET /api/v1/admin/email_security/ops/readiness`
   - Inventory: `GET /api/v1/admin/inventory/ops/readiness`
   - Expect: escalation/FP/handoff/latency/trace-failure alerts.

## Demo-Impact Priority

### P0 (must have for credible demo)
1. Prove full chain on 4 scenarios.
2. Use real external receiver (Webhook.site or Splunk HEC), not placeholder.
3. Prove deterministic auditability (decision tags, trace IDs, taxonomy in drilldown).

### P1 (high value, next sprint)
1. Add correction-time truth loop (`ground_truth`, `analyst_verdict`, `correction_ts`).
2. Add mutation-based red-team runner + trend endpoint.

### P2 (later maturity)
1. Agent-vs-agent adversarial swarm (detect vs red-team vs adjudicator).

## Status Summary (Today)

| Capability | Status | Notes |
|---|---|---|
| Detection observer + security taxonomy tags | `done` | Active in observer and decision drilldowns |
| Email/BEC deterministic routing | `done` | `evaluate` + simulation/runbook endpoints |
| SIEM/CrowdStrike/CSPM handoff adapter | `done` | Adapter + reliability + DLQ endpoints |
| Demo runbook APIs | `done` | `/demo/runbook` + `/demo/runbook/execute` |
| Ops readiness dashboards (email/inventory) | `done` | `/admin/email_security/ops/readiness`, `/admin/inventory/ops/readiness` |
| Real external receiver configured in environment | `in_progress` | Code supports it; env must be set per deployment |
| Correction-time truth loop in security events | `not_started` | Requires schema + API workflow |
| Mutation red-team benchmark trend API | `not_started` | Static suite exists; generative/mutation trends missing |
| Agent-vs-agent adversarial consensus | `not_started` | Single observer + deterministic routing today |

## Gap-by-Gap Demo Proof Checklist

### Gap 1: Self-Red-Team is static (not generative)
- Current status: `in_progress`
- What exists: static suite and scenario simulations.
- Proof checklist:
  - Endpoint: `POST /api/v1/email_security/simulate?scenario=prompt_injection`
  - Expect: deterministic route/verdict/reasons.
  - Artifact: screenshot of scenario result JSON + trace query output.
- Next acceptance criteria:
  - Mutation runner produces >= 50 mutated payloads/run.
  - Benchmark API exposes pass/fail trend by category for 30-day window.

### Gap 2: SIEM handoff uses configurable targets
- Current status: `in_progress`
- What exists: normalized handoff, retries, DLQ, reliability API.
- Proof checklist:
  - Endpoint: `GET /api/v1/admin/email_security/connectors/reliability?hours=24`
  - Expect: non-zero sent/retrying/failed counters after demo run.
  - Artifact: receiver-side evidence (Webhook.site/Splunk event) + reliability response screenshot.
- Next acceptance criteria:
  - At least one live receiver confirms payload receipt with matching `decision_id/trace_id`.

### Gap 3: Email security route wiring risk
- Current status: `done`
- What exists: evaluate + simulate + admin dashboard routes.
- Proof checklist:
  - Endpoint: `POST /api/v1/email_security/evaluate`
  - Expect: route, verdict_action, reasons, decision IDs.
  - Artifact: response JSON and incident detail screenshot from `/api/v1/admin/email_security/incidents/{id}`.
- Next acceptance criteria:
  - All 4 canonical scenarios map to expected route policy in one demo execution.

### Gap 4: Supply chain depth beyond schema/content checks
- Current status: `in_progress`
- What exists: schema drift/content marker detection + replay protections.
- Proof checklist:
  - Endpoint: `POST /api/v1/admin/connectors/test` (signed webhook)
  - Expect: detection/replay controls; suspicious payload handling.
  - Artifact: request/response pair and resulting security event trace.
- Next acceptance criteria:
  - Add SBOM/CVE enrichment with at least one real vulnerable dependency test case.

### Gap 5: Incident routing channels are mixed (some stubs)
- Current status: `in_progress`
- What exists: incident/ticket linkage via email security flow and admin incident APIs.
- Proof checklist:
  - Endpoint: `GET /api/v1/admin/email_security/demo/funnel`
  - Expect: `ticketed > 0` and trace linkage fields present.
  - Artifact: funnel JSON and admin incident record screenshot.
- Next acceptance criteria:
  - One real chat/ticket channel confirms delivery from production config.

### Gap 6: No parallel adversarial swarm in detection path
- Current status: `not_started`
- What exists: deterministic single observer plus post-processing traces.
- Proof checklist (today):
  - Endpoint: `GET /api/v1/decisions/{decision_id}/query?include_events=true`
  - Expect: ordered events and explicit policy/detection evidence.
  - Artifact: event timeline screenshot.
- Next acceptance criteria:
  - Background adversarial lane adds adjudicated update event without blocking request path.

### Gap 7: Bi-temporal correction-time fields missing
- Current status: `not_started`
- What exists: decision-time traceability and posthoc outcome labeling.
- Proof checklist (today):
  - Endpoint: `GET /api/v1/admin/email_security/feedback/summary`
  - Expect: false-positive metrics and trends.
  - Artifact: summary JSON + ops readiness alert panel.
- Next acceptance criteria:
  - Schema includes `ground_truth`, `analyst_verdict`, `correction_ts`, `correction_notes`.
  - API supports updates and reflects correction delta in admin drilldown.

## Acceptance Criteria for Priority Items

### P0 acceptance criteria
1. Four scenarios execute via runbook endpoint with deterministic outputs.
2. Every result has `decision_id` or `trace_id` and is queryable through decisions API.
3. SIEM reliability endpoint reflects outbound attempt(s) after execution.
4. Demo funnel shows linkage (`route`, `trace_id`, `ticket_id`) for recent incidents.

### P1 acceptance criteria
1. Correction-time API updates at least one incident and surfaces in drilldown/summary.
2. Mutation red-team job runs nightly and exposes trend metrics endpoint.

### P2 acceptance criteria
1. Agent-B/Agent-C workflow produces adjudicated verdict updates with confidence and rationale.
2. Swarm path is asynchronous and does not increase p95 request latency beyond agreed SLO.

## Honest Claims for Demo

### Safe to claim
- Deterministic email threat detection and routing with trace-linked evidence.
- Configurable SIEM/security middleware handoff with retry/DLQ telemetry.
- Decision and trace drilldowns with policy/taxonomy context.
- Operational readiness endpoints for escalation, false positives, handoff failures, and latency.

### Claim with qualifier
- "Enterprise SIEM integration": implemented and production-capable, but requires real endpoint/token configuration per tenant.

### Do not claim yet
- Full XDR behavior.
- Agent-vs-agent autonomous adversarial consensus in production path.
- Comprehensive SBOM/CVE dependency security coverage.
