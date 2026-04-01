# ShopSquire Compliance Framework Control Matrix
**Date:** 2026-03-29  
**Purpose:** Current-state control coverage tied to live code paths, not historical gap notes.  
**Frameworks:** PCI DSS 4.0, ISO 27001:2022, ISO 42001:2023, GDPR, EU AI Act, NIST AI RMF, Australian Privacy Act (APPs)

**Status legend:** `Implemented` | `Partial` | `Not ready to claim`

## Current platform position

- Strong demo / pilot posture with real runtime controls, bitemporal decision traces, privacy workflows, framework correlation, and evidence-oriented security analysis.
- Not ready to market as fully compliant or regulated-production-ready.
- Main current technical blockers for stronger claims:
  - payment idempotency behavior
  - broader governance/process evidence pack
  - full showcase/UI execution proof with Playwright in this environment

## Cross-cutting controls now present in code

| Control area | Current implementation | Evidence | Status |
|---|---|---|---|
| Bitemporal decision trace | Decision logs + trace events with valid/system time | `src/app/services/decision_log.py`, `src/app/services/trace_contracts.py` | Implemented |
| Audit chain integrity | Hash-chain + secret enforcement | `src/app/security/audit_chain.py`, `tests/security/test_decision_replay_and_audit_chain.py` | Implemented |
| Action authority matrix | Deterministic approval / review / block rules | `src/app/policy/action_authority_matrix.py`, `src/app/policy/route_enforcement.py` | Implemented |
| Global autonomy authority | Single kill-switch authority with trace emission | `src/app/policy/kill_switch.py`, `tests/test_rollout_and_killswitch.py` | Implemented |
| Data residency / provider boundary | Transfer gating + provider-side sanitization | `src/app/policy/data_residency.py`, `src/app/security/provider_boundary.py` | Implemented |
| Privacy / DSR workflow | Consent, export, delete, request endpoints | `src/app/routers/privacy.py`, `tests/api/test_privacy_consent_requests.py` | Implemented |
| Security headers / CSP | Security header middleware mounted in app | `src/app/security/headers.py`, `src/app/main.py` | Implemented |
| Framework correlation | MITRE, PASTA, STRIDE, DREAD, compliance mapping | `src/app/security/framework_correlation.py`, `config/security/taxonomy/control_registry.json` | Implemented |
| Email security forensics | Attachment, IOC, trust, route, trace, framework mapping | `src/app/security/email_security.py`, `src/app/routers/email_security.py` | Implemented |
| Conversation memory | Session + episodic/profile + NQE persistence | `src/app/services/memory.py`, `src/app/services/episodic_memory.py`, `src/app/routers/recommend.py` | Implemented |

## PCI DSS 4.0

| Requirement | Current state | Evidence | Status |
|---|---|---|---|
| Req 3 / tokenized payment handling | Provider-managed tokenized checkout paths exist | `src/app/routers/payments.py` | Partial |
| Req 6.4.3 CSP / security hardening | Header middleware present | `src/app/security/headers.py`, `src/app/main.py` | Implemented |
| Req 10 audit logging | Audit chain present and tested | `src/app/security/audit_chain.py`, `tests/security/test_decision_replay_and_audit_chain.py` | Implemented |
| Req 12 targeted risk / approval authority | Deterministic authority matrix present | `src/app/policy/action_authority_matrix.py` | Implemented |
| Production payment safety | Duplicate protection still not fully credible | `src/app/routers/payments.py`, `tests/api/test_payments_intent.py` | Not ready to claim |

Call: do not claim PCI DSS compliance. You can claim PCI-oriented controls and tokenization posture.

## ISO 27001:2022

| Control family | Current state | Evidence | Status |
|---|---|---|---|
| Logging and monitoring | Audit chain, security events, metrics, trace streams | `src/app/security/audit_chain.py`, `src/app/routers/decision_trace_events.py` | Implemented |
| Supplier / cloud use controls | Provider boundary + residency gate | `src/app/security/provider_boundary.py`, `src/app/policy/data_residency.py` | Implemented |
| Incident response paths | Incident + escalation + ticketing routes exist | `src/app/routers/incident.py`, `src/app/routers/escalation_room.py` | Partial |
| Privileged access / RBAC | Role checks widely used, not yet full resource-by-resource proof | `src/app/security/auth.py`, router dependencies | Partial |
| ISMS documentation / review cadence | Formal policy pack and management review evidence not in repo | process gap | Not ready to claim |

Call: do not claim ISO 27001 certification. You can claim substantial technical alignment.

## ISO 42001:2023

| Clause area | Current state | Evidence | Status |
|---|---|---|---|
| AI governance / model registry | Registry exists | `config/cv/model_registry.json` | Implemented |
| Human oversight | Authority matrix + global autonomy kill-switch | `src/app/policy/action_authority_matrix.py`, `src/app/policy/kill_switch.py` | Implemented |
| Logging / traceability | Bitemporal decision trace exists | `src/app/services/decision_log.py` | Implemented |
| Runtime evidence / monitoring | Security matrix and evidence-rich traces exist | `src/app/security/framework_correlation.py`, `src/app/security/email_security.py` | Partial |
| Formal AI management system docs | Formal AI policy, internal audit, change-management pack still incomplete | process gap | Not ready to claim |

Call: do not claim ISO 42001 certification. You can claim ISO 42001-oriented control design.

## GDPR

| Article area | Current state | Evidence | Status |
|---|---|---|---|
| Data minimization / scrubbing | Outbound provider scrubbing and transfer controls exist | `src/app/security/provider_boundary.py`, `src/app/security/dlp_export.py` | Implemented |
| Data subject rights | Export/delete/request flows exist | `src/app/routers/privacy.py`, `tests/api/test_privacy_consent_requests.py` | Implemented |
| Security of processing | Audit, encryption boundaries, provider gating exist | `src/app/security/audit_chain.py`, `src/app/policy/data_residency.py` | Partial |
| Automated decision oversight | Human review paths + kill switch + authority matrix | `src/app/policy/action_authority_matrix.py`, `src/app/policy/kill_switch.py` | Implemented |
| RoPA / lawful basis / DPIA | Formal documentation and legal records are not complete in repo | process gap | Not ready to claim |

Call: do not claim GDPR compliance. You can claim GDPR-supporting technical controls.

## EU AI Act

| Article area | Current state | Evidence | Status |
|---|---|---|---|
| Article 12 logging | Bitemporal trace and event persistence | `src/app/services/decision_log.py`, `src/app/routers/decisions.py` | Implemented |
| Article 13 transparency | Explainability and trace UI exist | `frontend/src/components/DecisionTrace.tsx`, `src/app/routers/decisions.py` | Partial |
| Article 14 human oversight | Authority matrix + global autonomy kill-switch | `src/app/policy/action_authority_matrix.py`, `src/app/policy/kill_switch.py` | Implemented |
| Article 15 robustness / cybersecurity | Security matrix, adversarial image / email controls, framework mapping | `src/app/security/framework_correlation.py`, `src/app/security/email_security.py` | Partial |
| Formal provider obligations / QMS | Full technical documentation and post-market governance pack incomplete | process gap | Not ready to claim |

Call: do not claim EU AI Act compliance. You can claim preparedness-oriented architecture.

## NIST AI RMF / Australian Privacy Act

| Area | Current state | Evidence | Status |
|---|---|---|---|
| GOVERN / oversight | Authority matrix + kill switch + trace | `src/app/policy/action_authority_matrix.py`, `src/app/policy/kill_switch.py` | Implemented |
| MAP / risk identification | Security matrix + framework correlation | `src/app/security/framework_correlation.py` | Implemented |
| MEASURE / evidence | Audit evidence agent + runtime traces | `src/app/services/audit_evidence_agent.py`, decision traces | Partial |
| MANAGE / treatment | Policy gating, human review, residency gate | `src/app/policy/route_enforcement.py`, `src/app/policy/data_residency.py` | Implemented |
| APP 8 / cross-border privacy | Residency gate exists | `src/app/policy/data_residency.py` | Implemented |
| APP policy/publication duties | Formal published privacy governance remains incomplete | process gap | Not ready to claim |

## Storefront 5173 and Email Lab 8080 evidence posture

| Surface | What is real | Remaining gap |
|---|---|---|
| Storefront (5173) | Recommendation flow, decision trace modal, security taxonomy, memory, NQE, policy trace hooks | Need fresh full-path Playwright verification in this session |
| Email Security Triage Lab (8080) | Email analysis, attachment/security matrix, trust routing, framework mapping, bitemporal trace, autonomy governance trace | Need fresh end-to-end runtime verification in this session |

## Honest claim set

You can claim:

- bitemporal decision trace with replay-oriented evidence
- bounded autonomy with deterministic policy controls
- global human-override / kill-switch authority
- framework-correlated security findings across commerce and email-security flows
- privacy / DSR support APIs
- real conversation memory and NQE follow-up continuity

You should not claim yet:

- PCI DSS compliance
- GDPR compliance
- ISO 27001 certification
- ISO 42001 certification
- EU AI Act compliance
- fully production-grade autonomous payments

## Highest-priority remaining work

1. Finish payment idempotency hardening beyond passing local tests.
2. Run and preserve the full Playwright showcase proof for storefront + email lab.
3. Produce formal governance artifacts: DPIA, RoPA, AI policy, ISMS scope/review cadence.
4. Expand evidence-pack generation so framework claims are tied to reproducible runtime traces and tests.
