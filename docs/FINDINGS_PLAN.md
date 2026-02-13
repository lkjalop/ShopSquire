# Findings Plan and Sequenced Fixes

Summary: concise sequence of gaps discovered during audit and recommended fixes, prioritized for reliability and observability.

1) Model tiering & trace completeness
  - Issue: `is_complex_query()`/`complexity_explain()` present but model_selection traces should include explicit rationale consistently.
  - Fix: Ensure `llm_provider` outputs normalized `complexity_signals` and `model_selection` trace is emitted from LLM orchestration paths.
  - Ticket: `TICKET-001: Normalize model_selection traces` — add unit tests and trace schema validation.

2) Recommendation human handoff parity
  - Issue: Recommendation emits `handoff_requested` for bulk shortages; confirm consumers (Sales playbook) subscribe and UI surfaces approval hints.
  - Fix: Add integration test covering `handoff_requested` persistence and `approval_id` visibility in API responses.
  - Ticket: `TICKET-002: Add handoff persistence + UI hint` — includes Playwright step to verify widget shows escalation notice.

3) ConversationState & session parity
  - Issue: `ConversationState` exists but session KV parity across Redis/Postgres sometimes inconsistent in Postgres triage runs.
  - Fix: Add reconciliation job/logging to surface KV drift; add tests for session continuity across recommend→checkout flows.
  - Ticket: `TICKET-003: Session KV reconciliation and tests`.

4) Checkout / Orders tests expansion
  - Issue: Checkout dialog can hang in Playwright; some order history/updates need broader coverage.
  - Fix: Expand targeted API tests (`tests/api`, `tests/integration`, `tests/test_orders_*`) and add Playwright opt-in steps with `TEST_SKIP_CHECKOUT` toggles.
  - Ticket: `TICKET-004: Expand checkout + orders test coverage`.

5) Frontend UX hardening (a11y + icons)
  - Issue: Widget gear modal has basic aria; icon set inconsistent.
  - Fix: Implement ARIA roles, keyboard focus traps, and consolidate icon pack; add accessibility smoke Playwright tests.
  - Ticket: `TICKET-005: Widget accessibility & icon consolidation`.

6) Telemetry & observability
  - Issue: OTLP configured; Jaeger disabled; Splunk HEC optional and env-driven.
  - Fix: Add CI smoke for OTLP metrics and a Splunk HEC dry-run (env guarded) as part of deploy checks; ensure tracing instrumentation idempotency warnings are addressed.
  - Ticket: `TICKET-006: Telemetry CI smoke + tracing idempotency fix`.

7) Postgres triage and data parity
  - Issue: Some tests pass locally on sqlite but surface Postgres-specific failures in CI; session/visibility parity targeted.
  - Fix: Add Postgres-specific fixtures in CI, run migration checks, and add replication of sample data for parity tests.
  - Ticket: `TICKET-007: Postgres triage and CI fixtures`.

Sequencing suggestion (2-week sprint):
  1. TICKET-006 (Telemetry) — quick wins, low risk
  2. TICKET-001 (Model traces) and TICKET-002 (Handoff) — auditability
  3. TICKET-003 (Session KV) — impacts many flows
  4. TICKET-004 (Checkout tests) & TICKET-005 (Frontend a11y) — UX and reliability
  5. TICKET-007 (Postgres triage) — end-to-end parity

Minimal acceptance criteria: each ticket must include tests (unit/integration/Playwright as applicable), a migration or migration-check if schema touched, and a trace/event validation example.

Notes: I can create starter branches/PRs for any of the above tickets and implement the easiest ones first (telemetry smoke, model_selection trace normalization).
