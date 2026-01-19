# ShopSquire PRD v2 — Secure, Modular, Copy‑and‑Rejig Agentic Commerce

Version: 2.0 (2026‑01‑19)
Owner: Platform Architecture
Scope: Reference architecture + demo stack enabling fast adaptation across e‑commerce platforms while meeting security, audit, and rollout needs.

## 1) Objectives & Outcomes
- Demonstrate a production‑grade, auditable agent system for commerce tasks (pricing, support, inventory) that teams can copy, rejig, and deploy.
- Preserve safety: zero‑trust agents, policy gating, full provenance.
- Enable controlled rollout: feature flags, percentages, instant rollback.
- Be modular: adapters for storefronts (Medusa.js starter), payments, catalog, and chat/voice interfaces.

KPIs (MVP → 8 weeks)
- <5% human override delta vs baselines on low‑risk paths
- <2% agent error on auto‑approved decisions
- 100% of write actions have policy verdict + audit artifacts
- p95 decision latency: Fast path ≤250ms, Enhanced path ≤900ms

## 2) Architecture Summary
- CRAG Gateway: routes each turn to Fast (~200–300ms), Enhanced (~700–900ms), or Crisis path (100% catch) based on classification + risk.
- Zero‑Trust Agents: propose‑only; Transaction Firewall approves/executes.
- Memory Hygiene: Tier‑0 prompt window, Tier‑1 Redis rolling summary + KV, Tier‑2 authoritative stores (catalog/orders); forced retrieval for volatile facts (price/stock/specs/delivery).
- Audit & Compliance: bi‑temporal decision logs; hot/warm/cold retention; cross‑mapping to ISO 42001, NIST AI RMF, EU AI Act.
- Health & Telemetry: dependency banners, factor telemetry, RAGAS snapshot, drift/anomaly alerts.

Key Components
- Orchestrator (5‑stage): validate → retrieve → reason → policy → execute/escalate
- Security Observer: OWASP LLM/API + MITRE ATLAS; Unicode, PII mask, jailbreak/poisoning checks; risk scoring (DREAD/STRIDE/CVSS/KEV correlation)
- Transaction Firewall: ABAC rules, idempotency, circuit breakers, approval tiers
- Adapters: chat (web), voice (Twilio), storefront (Medusa.js), payments, inventory, SIEM

## 3) Governance: Feature Flags, Rollout, Rollback
- Flags (config/feature_flags.json)
  - USE_AGENT_CAPABILITIES, AGENT_ROLLOUT_PERCENT, USE_CAREER_TRACKS‑analogue per capability (pricing/support/inventory)
- Rollout
  - Percentage‑based canary; cohort stickiness; exposure logged to decision context
- Rollback
  - Instant kill‑switches by capability and by tenant
  - Auto‑rollback triggers: error spikes, threat severity, KPI regressions

Admin APIs
- GET/POST /api/v1/admin/flags
- GET/POST /api/v1/admin/scoring/weights (lightweight sliders)
- GET/POST /api/v1/admin/scoring/update|versions|diff|rollback (persisted config)

## 4) Security & Compliance (Executive)
- Multi‑layer controls (Observer + Firewall) with strict propose‑only agents
- 100% of critical paths logged with retrieved evidence, policy version, dependency health, and confidence
- Mapped to ISO 42001, NIST AI RMF, EU AI Act; audit packs exportable

## 5) Memory & CacheRAG
- Per‑user Redis keys:
  - session:{uid}:summary (rolling narrative, 3h TTL)
  - session:{uid}:kv_state (budget, locale, draft_cart_id)
  - session:{uid}:recent_retrieval (CacheRAG: cache retrieval results, not model text)
- Forced Retrieval: claims about price/stock/specs/delivery always hit DB/API; CacheRAG caches result objects (5–10 min TTL volatile, 60 min static)
- Rolling Summarization: compress transcript to fit prompt; never use transcript as source of truth

## 6) Degradation & Kill Switches
- T1: AI; T2: Rules fallback; T3: Human queue; T4: Maintenance
- Auto‑degrade on timeouts/errors/confidence drops; auto‑recover on healthy streaks
- Manual override controls in Admin UI; all actions audited

## 7) Health, Telemetry, and Factor Quality
- Dependency health payload includes last_ok timestamps, latency, TTLs, queued batches
- Factor telemetry: window_precision, context_multipliers, factor_rankings
- RAGAS nightly sample; store to ragas_eval_results

## 8) Data, Retention, Privacy
- PostgreSQL: application + bi‑temporal decision logs (hot 7d)
- Warm analytics (90d), cold archive (≥7y)
- Fake/demo data by default; PII never in logs; masking at Observer

## 9) Modularity & Adapters
- Storefront: Medusa.js starter and mapping doc (webhooks/payments/catalog)
- Chat/Voice: Web chat + Twilio adapters, both pass CRAG + headers
- Payments, Fulfillment: pluggable clients via provider registry

## 10) Developer Experience & Quality Gates
- Package layout: domain routers under src/api/<domain>.py, small files (<500 lines) by lint gate
- Dependency injection for clients (DB/Redis/HTTP) via provider module
- Lint/Type: ruff + pylint (max‑module‑lines=500) + mypy strict; pre‑commit
- OpenAPI contract tests; router tests per capability; smoke for flags/rollback

## 11) Medusa.js Mock Commerce (MVP)
- Separate Medusa dev stack with seed catalog; webhook bridge to Orchestrator
- Minimal tasks: product browse, cart draft, checkout intent, order webhook
- See MEDUSA_INTEGRATION.md for wiring, env, and sample flows

## 12) Non‑Goals (MVP)
- No fine‑tuning/recursive training; we emulate “learning” with structured memory + CacheRAG and policy tuning
- No multi‑region HA; keep local demo simple

## 13) Risks & Mitigations (delta)
- Agent drift → forced retrieval, Observer trust gates, RAGAS
- Security regressions → pre‑commit OWASP scenario tests; kill‑switch
- Bloat/Spaghetti → file length lint, per‑router isolation, DI, tests

## 14) Deliverables (this repo)
- docs/shopsquire/SECURITY.md (controls + mappings)
- config/security/taxonomy/*.json (MITRE/DREAD/CVSS/STRIDE/KEV, risk policy)
- docs/shopsquire/MEDUSA_INTEGRATION.md (quickstart)
- Lint configs (.pylintrc, pre‑commit) to enforce lean modules
