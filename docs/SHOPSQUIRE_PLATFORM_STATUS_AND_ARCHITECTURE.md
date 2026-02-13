# ShopSquire Platform Status (Auto-Generated)

Date: 2026-02-02

## What ShopSquire Is
ShopSquire is a vendor-agnostic modular, agentic AI ecommerce platform targeting near-autonomous operation with compliance alignment for ISO 42001, ISO 27001, NIST AI RMF, PCI-DSS, EU AI Act, and threat-modeling coverage (DREAD, STRIDE, MITRE, OWASP LLM/API/Agentic). It provides NLP + CV commerce workflows, policy gating, fraud/security observation, decision logging, and bitemporal auditability.

## Core Architecture (High-Level)
- **Frontend (Vite/React):** Chat assistant, right-panel catalog UI, CV triage panel, Decision Trace modal with Security Matrix.
- **Backend (FastAPI):** Orchestrated routes for recommend/chat/orchestrate/decisions/complaints/vision/security/payments.
- **Decision Trace:** Bitemporal decision_logs + decision_trace_events with SSE streaming.
- **Security Observer:** Risk scoring + taxonomy mapping (MITRE/OWASP/STRIDE/DREAD/PASTA) with event persistence.

## Agents and Roles
- **Recommendation Agent** (`src/app/routers/recommend.py`, `src/app/services/recommendations.py`) — NLP parsing, candidate retrieval, reranking, inventory checks.
- **Security Observer Agent** (`src/app/security/observer.py`) — risk scoring, OWASP/MITRE/STRIDE/DREAD/PASTA tagging, event persistence.
- **Policy Gate Agent** (`src/app/policy/gate.py`) — policy rule evaluation, review/deny decisions.
- **Inventory Agent** (`src/app/services/inventory_agent.py`) — stock checks and escalation triggers.
- **Fraud / CV Triage** (`src/app/routers/vision.py`, `src/app/routers/support_complaints.py`) — image triage, fraud hints, case workflows.
- **Approvals Agent** (`src/app/routers/approvals.py`) — human review workflow.
- **Decision Audit + RAGAS** (`src/app/services/decision_log.py`, `src/app/services/ragas_eval.py`) — persistence and evaluation hooks.

## Model Tiering / LLM Strategy
- **Small model default** for short/simple queries; **big model escalation** based on complexity signals.
- **Selection logic:** `src/app/services/llm_provider.py` and `recommend` trace `model_selection` events.
- **Pragmatic use:** Rule-first, embedding-based ranking, fallback to LLM rerank only when enabled.

## Decision Trace & Bitemporal Logging
- **Decision logs** stored in `decision_logs` (bitemporal columns). Trace events in `decision_trace_events`.
- **SSE stream**: `/api/v1/decisions/{trace_id}/events/stream` (broker-aware SSE).
- **UI**: `frontend/src/components/DecisionTrace.tsx` with Security Matrix tab.

## What Works (Verified)
- Decision trace events render in UI for recommend/chat flows.
- Security Matrix shows MITRE/OWASP/STRIDE/DREAD/PASTA payloads.
- Policy gate logs and minimal decision logs on early returns.
- Playwright tests and pytest suites pass with local configuration.

## Fixes Applied (Key Files)
- **Model tiering + early returns**: `src/app/routers/recommend.py`
  - Early model selection trace event.
  - Price-range DB fallback when candidate search returns none.
  - AI/ML spec relaxation fallback.
  - Early decision logging for no-results paths.
  - Fixed `model_tier`/`complexity_signals` scoping bugs.
- **Decision log redaction**: `src/app/deps.py`, `src/app/services/decision_log.py`
  - Avoid over-redacting ticket IDs; redact PII safely.
- **Engine selection for tests**: `src/app/main.py`
  - Respect test engines (StaticPool) and env overrides.
- **Security observer updates**: `src/app/security/observer.py`
  - Added missing OWASP/Agentic tags; structured PASTA workflow.
- **Security Matrix UI**: `frontend/src/components/DecisionTrace.tsx`

## Remaining Issues / Watch-Items
- **CV + NLP unified orchestration**: still separate flows; orchestrate should merge CV/fraud signals into the same trace_id when complaint intent or images are present.
- **Payments / pricing contracts**: need final verification against docs/tests for 200/503/403 semantics.
- **Chaos latency enforcement**: verify flags across pricing + recommend.
- **Security “hard-block” endpoint**: confirm incident hard-block route if required.
- **LLM cost governance**: add thresholds for rerank, add logging for model tiering decisions.

## ASCII Wireframes (Target UX)

### 1) Main Assistant + Catalog + Decision Trace
```
+-----------------------------------------------------------------------------------+
| Header: ShopSquire  [Search box] [Cart] [Login]                                    |
+-----------------------------------------------------------------------------------+
| Assistant (left)                   |  Catalog (right)                             |
|------------------------------------|----------------------------------------------|
|  Chat history                      |  Grid/List/Compare toggle                    |
|  - User query                      |  Product cards w/ specs + CTAs               |
|  - Assistant answer                |                                              |
|                                    |                                              |
| [input + mic + send]               |                                              |
+------------------------------------+----------------------------------------------+
| [Decision Trace icon] -> opens modal (Events | Summary | Security Matrix | Raw)   |
+-----------------------------------------------------------------------------------+
```

### 2) CV Triage + Decision Trace
```
+---------------------------------------------------+   +--------------------------+
| CV Triage Panel                                   |   | Decision Trace Modal     |
|---------------------------------------------------|   |--------------------------|
| Order ID   | Issue Type | Description             |   | Events (timeline)        |
| [images upload] [submit] [agree/disagree/escalate]|   | Security Matrix          |
| Verdict / Next Steps                              |   | Raw JSON                 |
+---------------------------------------------------+   +--------------------------+
```

## Compliance & Privacy Posture (Current)
- **PII Redaction**: applied in decision_logs + security_events (`src/app/deps.py`).
- **Retention controls**: retention policy in `src/app/services/retention.py`.
- **GDPR/EU AI Act signals**: emitted in security observer details.

## Recommended Next Steps
1) Add unified NLP+CV orchestration for complaint intent + images (`src/app/services/orchestrator.py`).
2) Tighten payments/pricing contract behavior to align docs/tests.
3) Add CI-level seed step for NLP?products consistency.
4) Add explicit “model tier selection” telemetry to Decision Trace summary.

---
Generated by Codex
