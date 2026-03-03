# ShopSquire Sequential Delivery Matrix (Execution-First)

Date: 2026-02-26
Owner: Platform Engineering
Status Model: `todo` | `in_progress` | `done` | `blocked`

## Phase 1 - Security + Platform Hardening
Goal: production-safe core before expansion.

### 1.1 Full LLM10 hardening
- Status: `in_progress`
- Scope:
  - tighten model-theft extraction controls (rate, diversity, probe patterning)
  - enforce watermark propagation in decision traces and API responses
  - add per-key and per-tenant extraction anomaly thresholds
- Exit criteria:
  - security tests pass for model-theft guard and recommend wiring
  - extraction probes generate ticket + security event with deterministic reason code
  - no false blocks on baseline recommendation tests

### 1.2 NDR/PCAP maturity
- Status: `in_progress`
- Scope:
  - stabilize PCAP analyzer contracts
  - map network indicators into incident severity model
  - emit normalized network signal events into decision traces
- Exit criteria:
  - `tests/security/test_pcap_analyzer.py` green
  - at least one end-to-end trace path includes network-correlated signal payload

### 1.3 Vulnerability scanning path
- Status: `todo`
- Scope:
  - keep KEV ingestion
  - add active scan provider abstraction (nuclei/openvas adapter boundary)
  - add allowlist/scope policy guardrails
- Exit criteria:
  - scan adapter can run in dry-run and policy-enforced live mode
  - scan findings stored with source/provenance and confidence

### 1.4 Pentest module boundaries
- Status: `todo`
- Scope:
  - explicit "simulation only" constraints
  - strict authz + audit tags + tenant scoping
  - no unaudited destructive action paths
- Exit criteria:
  - boundary tests reject unsafe/unscoped operations
  - all pentest runs produce immutable audit artifacts

### 1.5 Multi-region foundations
- Status: `todo`
- Scope:
  - region-aware config contracts
  - stateless service assumptions + externalized state
  - replication/read-routing strategy document
- Exit criteria:
  - deployment manifests parameterized by region
  - data residency controls testable via config

### 1.6 SaaS onboarding + billing core
- Status: `todo`
- Scope:
  - tenant onboarding workflow
  - usage metering model
  - billing provider abstraction (Stripe metered first)
- Exit criteria:
  - new tenant can be provisioned with plan/limits
  - usage counters roll up to billable records

### 1.7 Platform hardening patch already delivered
- Status: `done`
- Delivered:
  - BI SQL generation now dialect-aware in query agent
  - admin BI router dialect detection hardened
  - sqlite/postgres portability improved for date filtering logic
- Files:
  - `src/app/services/bi_query_agent.py`
  - `src/app/routers/admin_bi.py`

## Phase 2 - Data/AI Foundation
Goal: identity + learning rigor.

### 2.1 CDP-grade identity governance
- Status: `todo`
- Scope:
  - identity graph with consent and data-right workflows
  - merge policies with explainable edge confidence
- Exit criteria:
  - profile merge decisions are traceable and reversible
  - consent controls enforced per feature call path

### 2.2 Forecasting MLOps hardening
- Status: `todo`
- Scope:
  - scheduled retraining orchestration
  - model registry + promotion gates
  - anti-poison quarantine and trust-weighted retrain input
- Exit criteria:
  - retrain jobs are reproducible and auditable
  - drift alerts + rollback path verified

### 2.3 Collaborative filtering productionization
- Status: `todo`
- Scope:
  - nightly training orchestration
  - online feature parity checks
  - fallback/ranking blend quality gates
- Exit criteria:
  - online scoring parity with offline eval within tolerance
  - ranking regression alarms wired

### 2.4 A/B significance rigor
- Status: `todo`
- Scope:
  - statistical significance and power checks
  - sequential testing guardrails
- Exit criteria:
  - experiment API returns significance + confidence metadata

## Phase 3 - Finance Write-Back
Goal: accountant-grade operational closure.

- Status: `todo`
- Scope:
  - Xero/MYOB/QBO write-back contracts
  - reconciliation workflow
  - P&L/margin model
  - tax contract engine (VAT/GST abstraction)
- Exit criteria:
  - posted entries round-trip with idempotency and audit linkage

## Phase 4 - Commerce Expansion
Goal: deepen intelligence-layer integrations (not ERP/storefront ownership by default).

- Status: `todo`
- Scope:
  - B2B wholesale module
  - subscriptions workflows
  - carrier connectors
  - marketplace connectors
- Exit criteria:
  - each connector has contract tests + failure-mode playbooks

## Phase 5 - Product Surface
Goal: surface expansion after trust/reliability gates.

- Status: `todo`
- Scope:
  - mobile app
  - voice interface
  - email marketing
- Exit criteria:
  - only after SLO and security gates from Phases 1-2 are stable

## Test Gates (Per Phase)
- Unit and service tests for touched modules
- API contract tests for new endpoints
- DB portability checks (SQLite + Postgres/Timescale where applicable)
- Decision-trace integrity verification for new signals/features
- Security regression set for authz, auditability, and policy enforcement
