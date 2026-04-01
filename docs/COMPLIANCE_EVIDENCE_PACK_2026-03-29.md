# ShopSquire Evidence Pack
**Date:** 2026-03-29  
**Scope:** 5173 storefront, 8080 backend and email security triage lab

## Purpose

This pack lists the strongest code-backed evidence for governance, privacy, threat modeling, and bitemporal decision tracing. It is an engineering evidence pack, not a certification pack.

## Evidence themes

### 1. Bitemporal decision trace

- Decision persistence:
  - `src/app/services/decision_log.py`
  - `src/app/services/trace_contracts.py`
- Query / replay surfaces:
  - `src/app/routers/decisions.py`
  - `src/app/routers/decision_trace_events.py`
- Test evidence:
  - `tests/security/test_decision_replay_and_audit_chain.py`
  - `tests/test_decision_bitemporal_query.py`

What this proves:
- every decision can carry valid-time and system-time evidence
- traces are suitable for replay and post-hoc control review

### 2. Human oversight and autonomy governance

- Deterministic authority matrix:
  - `src/app/policy/action_authority_matrix.py`
  - `src/app/policy/route_enforcement.py`
- Single global autonomy authority:
  - `src/app/policy/kill_switch.py`
- Storefront wiring:
  - `src/app/routers/recommend.py`
  - `src/app/routers/pricing.py`
  - `src/app/routers/payments.py`
  - `src/app/routers/orchestrator_api.py`
- Email lab governance evidence:
  - `src/app/routers/email_security.py`
  - `src/app/security/email_security.py`
- Test evidence:
  - `tests/test_rollout_and_killswitch.py`

What this proves:
- the platform has a single place to stop autonomous execution
- governance decisions are emitted into the trace layer

### 3. Framework-backed security matrix

- Correlation engine:
  - `src/app/security/framework_correlation.py`
- Control taxonomy:
  - `config/security/taxonomy/control_registry.json`
- CV / image pipeline usage:
  - `src/app/routers/chat.py`
  - `src/app/services/cv_tier2_pipeline.py`
- Email security usage:
  - `src/app/security/email_security.py`
- Test evidence:
  - `tests/security/test_framework_correlation_grounding.py`
  - `tests/security/test_framework_correlation_sbom.py`
  - `tests/security/test_trace_contracts_matrix_gate.py`

What this proves:
- framework mapping is not just slideware
- signals are attached to MITRE / STRIDE / PASTA / DREAD style structures in runtime payloads

### 4. Privacy and provider-boundary controls

- Residency gating:
  - `src/app/policy/data_residency.py`
- Outbound scrubbing:
  - `src/app/security/provider_boundary.py`
  - `src/app/security/dlp_export.py`
- DSR endpoints:
  - `src/app/routers/privacy.py`
- Test evidence:
  - `tests/api/test_privacy_consent_requests.py`

What this proves:
- data export and provider egress are policy-aware
- privacy workflows are present in code, not just listed in docs

### 5. Conversation memory and next-question continuity

- Session memory:
  - `src/app/services/memory.py`
- Episodic / profile memory:
  - `src/app/services/episodic_memory.py`
- NQE persistence:
  - `src/app/routers/recommend.py`
- Test evidence:
  - `tests/integration/test_chat_history_api.py`
  - `tests/test_recommend_followup_memory.py`
  - `tests/services/test_nqe_receipt_gate.py`

What this proves:
- the platform remembers enough state to support follow-up refinement and continuity

### 6. Email security triage lab evidence

- Main analysis engine:
  - `src/app/security/email_security.py`
- API surface:
  - `src/app/routers/email_security.py`
- Merchant lab UI:
  - `src/app/routers/merchant_dashboard.py`
- Test evidence:
  - `tests/security/test_email_security_p0_p1_p2.py`
  - `tests/security/test_email_detonation_trace.py`
  - `tests/pw/test_email_lab_security_matrix_flow.py`

What this proves:
- the lab is wired to real backend analysis and trace generation
- security matrix evidence is not frontend-only decoration

### 7. Storefront trace / UI evidence

- UI trace panel:
  - `frontend/src/components/DecisionTrace.tsx`
- Storefront app wiring:
  - `frontend/src/App.tsx`
- Test evidence:
  - `tests/pw/test_storefront_frontend_smoke.py`
  - `tests/pw/test_decision_trace_modal.py`
  - `tests/pw/test_followup_chips.py`

What this proves:
- the frontend has real trace and follow-up surfaces wired for demo and operator review

## Current evidence limits

- Formal governance artifacts are still incomplete:
  - DPIA
  - RoPA
  - formal AI policy pack
  - formal ISMS review cadence
- Showcase proof still needs a fresh Playwright run preserved with current code.
- Payment idempotency remains the most important live-production control concern.

## Honest usage guidance

Use this pack to support:

- architecture walkthroughs
- pilot / design-partner conversations
- security and governance demos
- engineering credibility around bitemporal trace and bounded autonomy

Do not use it to support:

- certification claims
- legal compliance claims
- “fully production-grade regulated deployment” claims
