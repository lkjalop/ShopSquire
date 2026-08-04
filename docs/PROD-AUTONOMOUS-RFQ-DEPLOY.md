# Autonomous RFQ — production deploy & enablement runbook

The autonomous-RFQ-send feature (WS-A…D) is OFF by default and safe-first: with nothing configured it
behaves exactly as the human-in-the-loop flow. This runbook is the checklist to turn it on responsibly.

## 1. Real sending (SMTP transport)

By default the supplier transport is **sandbox** — `send_approved` / `send_autonomous` STAGE the message
and return a `DEMO-OUT-…` ref but transmit nothing. To actually send, set at deploy:

| env var | meaning |
|---|---|
| `FULFILLMENT_SUPPLIER_TRANSPORT=smtp` | select the real SMTP transport (default `sandbox`) |
| `SMTP_HOST` | mail host (required) |
| `SMTP_PORT` | default `587` |
| `SMTP_USER` / `SMTP_PASSWORD` | credentials (STARTTLS used when `SMTP_USER` is set) |
| `SMTP_SENDER` | the From address (required) |

Preflight: `GET /api/v1/fulfillment/autonomous/audit` returns `transport: {mode, configured, missing,
transmits}`. **Do not enable autonomy while `transport.mode=smtp` and `configured=false`** — every send
would fail. A real transport failure never corrupts the case: it returns `send_failed` and records no send.

## 2. Vendor trust (KYV onboarding)

Autonomous send only contacts a domain that has a **verified, low/medium-risk** `kyv_vendors` record.
Onboard via the owner control plane (`X-API-Key` = owner; `X-Tenant-Id` optional):

- `POST /api/v1/admin/kyv/vendors` — register (`legal_name`, `verified_domain`, `contact_email`,
  `risk_tier`, optional `registration_number`+`registration_type` (ABN/ACN, validated)). Starts `pending`.
- `POST /api/v1/admin/kyv/vendors/{id}/verify` — mark verified (the bit the trust gate needs).
- `POST /api/v1/admin/kyv/vendors/{id}/status` — `suspended`/`revoked` instantly removes trust.
- `POST /api/v1/admin/kyv/vendors/contact-email` — backfill a real recipient address by domain.
- `GET /api/v1/admin/kyv/vendors/review` — vendors flagged for re-review.

The domain must ALSO be on the supplier allowlist (`supplier_domain_guard`) — the recipient is resolved
server-side from allowlist/KYV, never from buyer text.

## 3. Enable autonomy (flags + caps)

Toggle at runtime via `config/feature_flags.json` (governed: `POST /api/v1/admin/flags`, dual-control) or
env. Any kill source stops it (fail-safe).

| control | default | effect |
|---|---|---|
| `FULFILLMENT_AUTONOMOUS_RFQ` | false | master enable |
| `FULFILLMENT_AUTONOMOUS_KILL_SWITCH` / `KILL_SWITCH` / `ADAPTATION_KILL_SWITCH` | false | emergency stop |
| `FULFILLMENT_AUTONOMOUS_MIN_CONFIDENCE` | 0.8 | min draft confidence to auto-send |
| `FULFILLMENT_AUTONOMOUS_MAX_VALUE_CENTS` | 500000 ($5k) | per-RFQ value cap |
| `FULFILLMENT_AUTONOMOUS_MAX_QTY` | 25 | per-RFQ quantity cap |
| `FULFILLMENT_AUTONOMOUS_RATE_PER_HOUR` | 10 | per-tenant send rate cap |

Guards (ALL must pass, else ESCALATE to the human gate): enabled ∧ not killed ∧ allowlist+KYV trusted ∧
draft claim-safe ∧ draft complete ∧ confidence ≥ min ∧ value ≤ cap ∧ qty ≤ cap ∧ under rate ∧ action-gate
authorizes. An RFQ is non-binding (no price / no PO — enforced by the send-cage).

## 4. Observe

`GET /api/v1/fulfillment/autonomous/audit?limit=N` (operator-gated): `summary {sent, escalated,
by_reason}`, the per-decision `rows` (sent=`allow`, escalations=`escalate`+reason), live `enabled`/`killed`
state, and the `transport` preflight. Every active-autonomy decision is durably audited
(`adaptive_action_audit`, action_type `supplier_rfq_send`). The admin Procurement page renders this.

## 5. Recommended enablement order

1. Onboard + verify the suppliers you trust; confirm each via `GET …/kyv/vendors/by-domain/{domain}`.
2. Configure SMTP; confirm `transport.configured=true` on the audit endpoint.
3. Set conservative caps; turn `FULFILLMENT_AUTONOMOUS_RFQ` on for one tenant.
4. Watch the audit endpoint — confirm sends are the ones you expect and escalation reasons make sense.
5. Keep the kill switch one toggle away.
