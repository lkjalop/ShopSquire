# ShopSquire Deep Dive Revalidated

Date: 2026-03-29

## Executive Summary

The platform is materially further along than `docs/SHOPSQUIRE_DEEP_DIVE_MARCH29_2026.md` claims.

Several items listed there as missing are now implemented:

- audit-chain secret hardening exists in `src/app/security/audit_chain.py`
- connector scope enforcement defaults to on in `src/app/security/scope_enforcement.py`
- action authority matrix exists in `src/app/policy/action_authority_matrix.py`
- data residency registry exists in `src/app/policy/data_residency.py`
- provider-boundary redaction + residency enforcement exists in `src/app/security/provider_boundary.py`
- CSP/security headers middleware exists in `src/app/security/headers.py` and is mounted in `src/app/main.py`
- DSR-style privacy endpoints exist in `src/app/routers/privacy.py`
- CV model registry exists at `config/cv/model_registry.json`
- Celery task signing is enabled in `docker-compose.yml`

The platform is not a fake demo. Core recommendation, fraud/security observation, NQE, memory, audit trace, privacy APIs, and parallel agent orchestration are real.

## Current Honest State

- Production-grade overall: about 75%
- Strong for demo and controlled pilot
- Not yet ready for regulated live production without a short remediation sprint

## What The Code And Tests Actually Show

### Verified working

- Conversation memory is real:
  - Redis/local-backed session memory in `src/app/services/memory.py`
  - episodic/profile memory in `src/app/services/episodic_memory.py`
  - NQE state persisted in `src/app/routers/recommend.py`
  - targeted tests passed:
    - `tests/integration/test_chat_history_api.py`
    - `tests/test_recommend_followup_memory.py`
    - `tests/services/test_nqe_receipt_gate.py`

- Audit chain is real:
  - hash-chain logic and secret enforcement in `src/app/security/audit_chain.py`
  - targeted test passed:
    - `tests/security/test_decision_replay_and_audit_chain.py`

- Privacy/DSR workflow exists:
  - consent + request endpoints in `src/app/routers/privacy.py`
  - export/delete endpoints exist
  - targeted test passed:
    - `tests/api/test_privacy_consent_requests.py`

- Parallel agents are real:
  - `asyncio.gather` in `src/app/services/agent_dag_runtime.py`
  - orchestrator phase parallelism in `src/app/services/orchestrator.py`
  - parallel executor in `src/app/services/parallel_agent_executor.py`
  - agent traces and weights are present, not simulated-only

### Verified still broken or incomplete

- Payment idempotency is still a real blocker:
  - code is no longer the old in-memory cache, but behavior is still wrong
  - targeted test failed:
    - `tests/api/test_payments_intent.py::test_payment_intent_idempotency`
  - second request with the same idempotency key still returned `200` instead of `409`

- Compliance mapping docs are stale:
  - `docs/COMPLIANCE-FRAMEWORK-CONTROL-MATRIX.md`
  - `docs/SHOPSQUIRE_DEEP_DIVE_MARCH29_2026.md`
  - both still claim several controls are missing even though code now exists

- Feature-flag governance is weak:
  - `config/feature_flags.json` is nearly empty
  - much runtime behavior depends on env vars, not centrally governed release flags

- Kill-switch implementation is partial:
  - some route-level kill-switch checks exist
  - no single production-grade global autonomy kill-switch module/database authority was found

- Evidence pack is partial:
  - compliance registry, reporting, control registry, framework correlation, and audit evidence agent exist
  - but much of the framework status is still document-driven and not backed by a complete evidentiary control pack

## Revalidated Critical Gaps

### CRIT-01 Hardcoded audit HMAC secret

Status: no longer correct as written.

Reality:
- fixed in principle
- `src/app/security/audit_chain.py` now fails closed in prod-like envs if `AUDIT_CHAIN_SECRET` is missing or weak
- residual gap is deployment hygiene, not code absence

### CRIT-02 In-memory idempotency cache

Status: partially outdated, but still production-blocking.

Reality:
- the old claim is outdated because `src/app/routers/payments.py` now uses DB-backed persistence logic
- however the path is still not reliable enough for production because the existing test still fails
- this remains a true critical blocker until behavior is fixed and re-tested

### CRIT-03 Connector scope enforcement off by default

Status: no longer correct.

Reality:
- `src/app/security/scope_enforcement.py` defaults `ENFORCE_CONNECTOR_SCOPES` to `"1"`
- `docker-compose.yml` also sets `ENFORCE_CONNECTOR_SCOPES: "1"`

### CRIT-05 No policy authority matrix

Status: no longer correct.

Reality:
- implemented in `src/app/policy/action_authority_matrix.py`
- wired in at least:
  - `src/app/routers/billing.py`
  - `src/app/routers/events.py`
  - `src/app/routers/privacy.py`
  - `src/app/routers/returns.py`
- remaining gap is coverage/completeness, not total absence

### CRIT-06 PII not scrubbed before LLM calls

Status: mostly outdated, but with nuance.

Reality:
- provider-boundary sanitization exists and is wired into:
  - `src/app/services/llm.py`
  - `src/app/services/llm_provider.py`
  - `src/app/services/llm_providers.py`
  - `src/app/services/llm_router.py`
  - `src/app/services/embeddings.py`
  - `src/app/services/vision_reasoning.py`
  - `src/app/services/voice_asr.py`
- `src/app/security/provider_boundary.py` uses `dlp_scrub_all()`
- residual gap:
  - some export/admin sanitization still only uses secret scrubbing, not full PII scrubbing
  - evidence/testing around all outbound paths should be tightened

### Data residency gate missing

Status: no longer correct.

Reality:
- implemented in `src/app/policy/data_residency.py`
- enforced through provider-boundary and routing in LLM/vision/voice paths
- residual gap is governance proof:
  - several providers are marked with `signed_dpa=False`
  - production use with real PII still depends on legal/process completion

## Demo And Stub Audit

### Safe demo-only surfaces

- `src/app/routers/demo.py`
- demo-gated routes in admin/security routers
- seeded demo scripts in `scripts/`
- local demo hunt/report generation in `src/app/routers/merchant_dashboard.py`

These are mostly isolated behind `ENABLE_DEMO_ROUTES` or local-host checks.

### Real stub/degrade pockets still present

- `src/app/services/erp_edi.py`
  - real connector framework exists
  - mock mode and partial connector implementations remain

- `src/app/services/graph_retrieval.py`
  - in-memory fallback exists

- `src/app/analytics/ragas.py`
  - explicit stub path

- `src/app/analytics/events_sink.py`
  - placeholder sink

- `src/app/services/orchestrator.py`
  - multiple graceful-degrade and stub fallback paths for unavailable model/runtime dependencies

- `src/app/services/product_ranking_agent.py`
  - at least one placeholder scoring component remains

These do not make the whole platform fake, but they do reduce evidence quality for some advanced paths.

## Compliance Mapping Assessment

### What exists

- control registry:
  - `config/security/taxonomy/control_registry.json`
  - `src/app/security/control_registry.py`

- framework correlation:
  - `src/app/security/framework_correlation.py`

- compliance artifact storage:
  - `src/app/models/compliance_registry.py`
  - `src/app/routers/admin_compliance_registry.py`

- evidence reporting:
  - `src/app/services/compliance_reporting.py`
  - `src/app/routers/admin_compliance_reports.py`

- deterministic audit evidence rules:
  - `src/app/services/audit_evidence_agent.py`

### What is not yet production-grade

- the main mapping docs are stale and overstate missing controls
- evidence collection is only partially tied to runtime pass/fail gates
- many framework claims still depend on documentation/process artifacts not found in code:
  - DPIA
  - RoPA
  - formal ISMS scope/review cadence
  - formal AI governance policy pack
  - legal DPA completion evidence

### Live-test readiness by framework

- PCI DSS 4.0:
  - close, but not ready for a serious live claim
  - biggest technical blocker found: payment idempotency behavior
  - claim blocker also includes external assessment/pen-test evidence

- ISO 27001:
  - technical controls are decent
  - process evidence is incomplete
  - not certification-ready

- ISO 42001:
  - runtime governance is much better than the docs say
  - formal AI management artifacts are still incomplete
  - not audit-ready

- GDPR / APP 8:
  - much better than the older report says
  - DSR endpoints and transfer gates exist
  - still not ready to claim full compliance without RoPA/DPIA/DPA/process evidence

- EU AI Act:
  - bounded-authority controls exist
  - central kill-switch + formal classification/documentation still incomplete

## Answers To Your Specific Questions

### How is the platform going?

Better than the older deep-dive says. The core product is real and relatively advanced. The remaining gaps are no longer “does it exist?” gaps as much as “is it fully enforced, consistently tested, and governance-evidenced?” gaps.

### What is still needed for production grade?

Highest-priority:

1. Fix payment idempotency behavior and add stronger persistent semantics.
2. Centralize autonomy kill switches and prove they work across high-impact routes.
3. Refresh the compliance mapping docs so they match code reality.
4. Expand evidentiary tests for provider-boundary redaction/residency across every outbound model/tool path.
5. Turn env-driven controls into governed feature/config artifacts where appropriate.
6. Build the missing process artifacts: DPIA, RoPA, AI policy, DPA evidence, ISMS review cadence.

### Find all the demo and stubs?

No, not all code is demo/stubbed. Demo paths are clearly present, but the regulated core path is mostly real. The meaningful remaining stub/degrade areas are ERP integration, graph fallback, analytics placeholder/stub modules, and some orchestrator/model fallback branches.

### How are the compliance framework mappings?

There is real machinery for mappings and evidence, but the top-level documents are stale. The mappings are not yet trustworthy as a live audit packet until they are regenerated from current code/runtime facts.

### Are they ready to be live tested?

For internal pilot/live testing: mostly yes.

For regulated production/live customer operation: not yet.

Blocking reasons:

- payment idempotency failure
- incomplete global autonomy kill-switch story
- incomplete evidence/process pack for compliance claims
- stale documentation undermining auditability

### How are all the parallel agents? Are they evidence based?

Yes, mostly. The parallel orchestration is real, instrumented, and tied to actual CV/fraud/inventory/security work. It is not just a UI fiction. The weakest part is that some downstream services still degrade to fallback/stub behavior when optional dependencies are unavailable.

### How is the next question engine?

Good. The NQE looks genuinely implemented, carries forward state, avoids repeated questions, and has passing targeted tests for memory/follow-up behavior.

### Does the platform actually remember the conversation now?

Yes. Session memory is real. Chat history and follow-up memory tests passed. Long-term/cross-session memory exists as episodic/profile memory, but it is still softer operationally than the session-memory path.

## Recommended Production Sprint

### P0

- fix `src/app/routers/payments.py` idempotency behavior
- add regression test coverage for duplicate payment prevention across restart/process boundaries
- implement a global autonomy kill-switch authority and wire it into all high-impact action paths
- regenerate compliance status docs from current runtime/code facts

### P1

- add outbound-path tests for provider-boundary redaction/residency
- move more env-only governance knobs into structured config/registry
- tighten audit/compliance evidence generation from runtime state

### P2

- reduce remaining stub/degrade pockets in ERP, analytics, graph enrichment, and ranking
- formalize AI governance/process artifacts

## Bottom Line

The old March 29 assessment is directionally useful but materially out of date.

The platform is not “65% with five missing primitives” anymore. It is closer to “real platform with several implemented safeguards, one confirmed payment blocker, a partial governance/evidence layer, and a short path to controlled production pilot but not yet to regulated production claim-making.”
