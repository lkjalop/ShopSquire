# ShopSquire × David's "Market Analysis & Adaptive Growth System" — Implementation Deep Dive

**Date:** 2026-06-25
**Author:** Claude Opus 4.8 (codebase deep dive, 4 parallel explorers across ingestion/analysis, decision/policy/audit, execution/experimentation, and core/adapter foundations)
**Scope:** Map David's 7-module autonomous market-intelligence subsystem onto the actual ShopSquire codebase; recommend *what to build, in what order, and where it lives* (agnostic core vs electronics adapter).

---

## 0. The one-paragraph answer

ShopSquire is **not** a blank slate for this. Its orchestrator + policy + bitemporal-audit + anomaly/forecast spine already implements **~75% of the deck's "AI interprets → Policy authorizes → Automation executes → Audit records"** design principle — that is precisely David's cross-cutting requirement, and it's the hardest part to build. What's genuinely missing is the **outward, closed-loop half**: (a) external market *sensing* (competitor/trend feeds), (b) a unified market-intelligence *store*, (c) a *decision engine for the new action types* (messaging/campaign/segment), (d) *execution* into marketing surfaces (storefront banners, email/SMS, offers), and above all (e) **experimentation & attribution** — which the deck flags as "non-negotiable" and which is currently ShopSquire's biggest gap. **Recommendation: build the attribution backbone first** (it's agnostic, low-risk, high-leverage, and a hard prerequisite for *any* honest autonomy), then assemble Phases 1–2 ("Visibility" + "Advisory") almost entirely from parts that already exist, and only grant live customer-facing authority (Phase 3+) once attribution + rollback can prove a change helped.

---

## 1. Module-by-module readiness scorecard

| David module | ShopSquire readiness | What already exists (file:symbol) | The real gap |
|---|---|---|---|
| **M1 — Signal Ingestion** | **~60%** | `routers/consumer_signals.py` (clickstream, PII-hashed, ASN/geo), `services/search_events.py:log_search_event`, `services/decision_log.py`, `models/decision_trace_events.py`, `services/retargeting_trigger.py` (cart abandonment), webhook outbox `models/event_log.py` | No **unified `market_signal` schema** (each event lives in its own table); **no external** competitor/trend/sentiment feeds |
| **M2 — Market Intelligence Store** | **~40%** | `drift_daily_metrics` (daily trend aggregates), `anomaly_metric_history`, `decision_logs` (bitemporal valid/system time), Redis `session:{uid}:*`, `price_history`, `inventory_level_history` | No `trend_indicator`, `competitor_snapshot`, `segment_definition/membership`, `channel_performance`, `support_theme_summary`, `decision_outcome` |
| **M3 — Analysis Engine** | **~65%** | `services/anomaly_detector.py:AnomalyDetector` (IsolationForest+LOF+Prophet+zscore ensemble, graceful fallback), `services/demand_forecast.py:DemandForecaster` (EWMA+ARIMA+Prophet, anti-poison quarantine), `rules/engine.py` (50+ rules), `services/response_normalizer.py` (payload→plain-English LLM) | No **competitor-undercut** detection, **support-objection-theme** analysis, **sentiment**, **messaging-fatigue** curves |
| **M4 — Decision & Optimization** | **~70% spine / ~20% new actions** | `policy/action_authority_matrix.py` (ALLOW/DUAL_CONTROL/HUMAN_REVIEW/BLOCK + 25 rules), `services/escalation_policy.py` (BAND_AUTO/REVIEW/HUMAN), discount/refund ceilings in `policy/gate.py` | No **campaign/segment/messaging** decision types; **no contact-frequency caps** (the one missing governance primitive) |
| **M5 — Communication Orchestrator** | **~50%** | `services/recommend_ranking.py` (profile-driven ranking nudges), `services/upsell_engine.py`, `flows/nqe.py` + `flows/nqe_templates.py` (with **A/B variants**), `services/copywriting.py` (4 tone profiles, risky-claim stripping), `services/retargeting_trigger.py`, `services/email_sendgrid.py` | No **storefront banner/hero/landing variants**, **offer/promotion engine**, **SMS**, **email body generation**, **objection handling** |
| **M6 — Experimentation & Attribution** | **~25% — THE KEYSTONE GAP** | `services/recommendation_bandit.py` (LinUCB, 4 arms), `nqe_templates.py` variant bucketing (hash by trace_id), `recommend_interactions` table, `services/recommend_retrieval_metrics.py:compute_parity` (shadow-vs-primary) | **No trace_id→order_id linkage** (can't measure conversion!), no experiment registry, no uplift/stat-sig, no attribution window, **no rollback triggers**, no dashboard. Bandit **reward signal is undefined** today |
| **M7 — Policy, Governance & Audit** | **~85% — STRONGEST** | `policy/action_authority_matrix.py`, `security/audit_chain.py` (SHA-256 hash chain + WORM archive + HMAC), `services/decision_replay.py` (bitemporal replay), `services/product_claim_guard.py` ("no unsupported promises"), `policy/kill_switch.py:assert_autonomy_allowed`, `services/policy_evaluator.py`, OWASP-Agentic/ISO-42001 tagging | **Contact-frequency caps**, **region/channel restrictions** |

**Cross-cutting design principle ("propose → authorize → execute → audit"): ~80% wired.** The four stages all exist (`Orchestrator.run` → `execution_gate.decide` → `playbook_engine.execute_typed_actions` → `decision_log.log_decision`+`audit_chain`). The weak link is **uniform `trace_id` threading** and **execute-stage reversibility** — which is the same root as the M6 gap.

---

## 2. The keystone insight (why ordering matters)

David's deck states it plainly (Module 6): *"Autonomous adaptation without measurement creates a system that can confidently make things worse."* And the phased rollout (slide 29) gates **all** live customer-facing authority behind **Visibility → Advisory → measurement** first.

ShopSquire today can *act* (it ranks, narrates, escalates, reorders) but **cannot yet prove an autonomous change helped**, because there is no link from a decision/recommendation `trace_id` to the resulting `order_id`, and no conversion/attribution window. Its own LinUCB bandit has an **undefined reward signal** for exactly this reason. So:

> **Every other module's business value is unmeasurable — and un-rollback-able — until the attribution backbone exists.** That makes M6 (minimum slice) the correct first build, not the last.

This also happens to be the **cheapest high-leverage** item: it's pure agnostic-core, reuses the existing `decision_logs` bitemporal store + `recommend_interactions` + `orders`, and immediately makes the *recommendations you already ship* measurable.

---

## 3. Where the new code lives (the non-negotiable architecture constraint)

ShopSquire enforces an **agnostic-CORE vs vertical-ADAPTER** boundary *mechanically* (`tests/test_no_flavour_in_core.py` — a regex ratchet that fails the build if a core module contains `rtx|gtx|macbook|144hz|…`; `tests/test_profile_parity.py` ensures every `config/store_profiles/*.json` carries the same slots). Any new subsystem MUST respect it:

| New piece | Lives in | Rule |
|---|---|---|
| Market-analysis **mechanism** (demand/segment scoring, attribution math, decision evaluation) | `src/app/services/market_*.py` → add to `_CORE_MODULES` | Zero product vocabulary; pure functions over injected data |
| Vertical **flavour** (segment definitions, competitor brands, elasticity bands, offer policies) | `config/store_profiles/electronics.json` (+ fashion/pharmacy) new slots: `market_segments`, `competitive_intelligence_rules`, `adaptive_pricing_rules`, `channel_preferences` | Must be parity-present across all profiles (or inline-adapter ratchet) |
| Pipeline wiring | `routers/recommend.py`, new `tasks/market_analysis_tasks.py` | Feature-flag gated (`MARKET_ANALYSIS_ENABLED`), kill-switch (`assert_autonomy_allowed`), every action `log_decision`-audited |
| Rollout | `config/feature_flags.json` + `policy/kill_switch.py` | 1% → 10% → 100% canary; default-OFF for behavioral changes |

This is also exactly how the deck's "AI interprets / Policy authorizes / Automation executes / Audit records" maps onto ShopSquire's existing primitives — so we are *extending* the spine, not bolting on a parallel one.

---

## 4. Data-architecture delta

**Already present (reuse, don't rebuild):** `decision_logs` (bitemporal), `decision_trace_events`, `event_log` (outbox), `search_events`, `recommend_interactions`, `orders`/`order_items`, `price_history`, `inventory_level_history`, `drift_daily_metrics`, `anomaly_metric_history`, `recommend_bandit_arms`/`_events`, `suppliers`/`purchase_orders`, `incidents`/`human_review_tasks`, `customer_trust_scores`.

**To add (mapped to David's "Core Entities"):**

| Phase | New table | Reuses / pattern |
|---|---|---|
| **1 (keystone)** | `recommendation_decision` (trace_id, arm, variant, skus, ts) + `conversion_event` (decision_id→order_id, window_h, converted_at, revenue_cents) | bitemporal like `decision_logs`; closes bandit reward loop |
| 1 | `market_signal` (signal_type, domain, payload, source_table, source_id) — **normalizer over existing events** | one-table fold of consumer_signals/search/returns/support |
| 1 | `trend_indicator` (date, indicator, value, expected_lo/hi, z, severity) | clone `drift_daily_metrics` shape |
| 2 | `support_theme_summary` (date, theme, count, resolution_rate, blocking_conversion_pct) | `ComplaintNLP` + `response_normalizer` |
| 2 | `experiment` / `experiment_arm` / `experiment_metric` | generalize `nqe_templates` variant + bandit pattern |
| 2 | `decision_outcome` (decision_id, final_action, business_impact, impact_cents) | feedback loop to M3 |
| 3 | `contact_frequency_ledger` (customer_id, channel, window, count) | the missing governance primitive for M4/M7 |
| 4 | `competitor_snapshot`, `segment_definition`/`membership`, `channel_performance`, `offer_policy` | needs external feeds / batch jobs |

---

## 5. Recommended build order (mapped to David's 5 phases)

### ▶ Build 1 — Attribution backbone *(keystone; agnostic core; ~Phase 1–2 enabler)*
- `recommendation_decision` + `conversion_event` tables; emit a decision row on every `suggest()`/ranking; a Celery job (or order webhook) links `order_items` back to the most recent decision within an attribution window.
- Define the **bandit reward** = attributed conversion/revenue (fixes the undefined-reward bug in `recommendation_bandit.py`).
- **Payoff:** instantly measures the recommendations ShopSquire *already* ships; unblocks every later phase. **Risk: minimal** (read-only measurement, no customer-facing change).

### ▶ Build 2 — Market signal normalizer + intelligence store *(Phase 1 "Visibility")*
- `market_signal` table + a `services/market_signal_normalizer.py` (core) that folds existing events into the common schema; `trend_indicator` populated by a Celery job reusing `AnomalyDetector` + `DemandForecaster`.
- A read-only governance dashboard (extend `routers/admin_bi.py`).
- **Payoff:** the deck's Phase 1 ("detect trends, change nothing") — achievable mostly by *assembling existing signals*. **Risk: low.**

### ▶ Build 3 — Bounded decision engine for new action types *(Phase 2 "Advisory", shadow-only)*
- `services/market_decision_engine.py` (core) producing **bounded** decisions (messaging emphasis, ranking nudge, campaign-suppress-on-low-stock, segment comms) — each routed through the **existing** `action_authority_matrix` + `escalation_policy` bands + `kill_switch`.
- Add `contact_frequency_ledger` (the missing cap) and `decision_outcome`.
- Run **logged-only** (no execution), compared against actuals via Build 1's attribution — this is exactly ShopSquire's proven *shadow/parity* pattern (`compute_parity`).
- **Payoff:** the deck's "Advisory Mode." **Risk: low** (nothing executes).

### ▶ Build 4 — Communication execution adapters *(Phase 3 "Low-Risk Adaptation")*
- Wire decisions into surfaces that **already exist**: ranking nudge (`recommend_ranking`), support/pre-sales phrasing (`copywriting` + NQE variants), retargeting (`retargeting_trigger` + SendGrid). Each under kill-switch + attribution + **rollback trigger** (auto-revert if conversion/margin drops vs baseline).
- **Payoff:** first *live* autonomous adaptation, but only the reversible, low-blast-radius kind. **Risk: medium — gated by Builds 1+3.**

### ▶ Build 5 — Heavier surfaces & external sensing *(Phase 4 "Bounded Optimization")*
- NEW: storefront banner/hero/landing variants, offer/promotion engine, SMS, competitor-price feed + undercut detection, formal segments, channel_performance.
- **Payoff:** offers/bundles/campaigns/inventory-aware suppression. **Risk: higher; build last.**

### ▶ Build 6 — Closed-loop growth *(Phase 5)*
- Full sense→analyze→decide→execute→measure→rollback under policy across channels. Only after Builds 1–5 are instrumented and trusted.

---

## 6. What ShopSquire is *uniquely* well-positioned for

The deck's hardest, scariest requirements are ShopSquire's existing strengths:
- **"Immutable logging + full replay"** → `audit_chain.py` (hash chain + WORM) + `decision_replay.py` (bitemporal). ✅ Already production-grade.
- **"AI must never directly trigger privileged actions / no unsupported promises"** → `product_claim_guard.py` + `execution_gate` + `action_authority_matrix`. ✅
- **"Every failure mode has an autonomous response"** → `safe_stage.py` / `record_partial_failure` + `exception_resolver.py` terminal dispositions. ✅ (gap: retry backoff, circuit-breaker state machine, automated revert).
- **"Confidence thresholds before action"** → `escalation_policy.assess_escalation` bands + `confidence_calibration`. ✅
- **Multi-technique AI (not one general model)** → anomaly ensemble + forecaster + rules + LinUCB bandit + LLM-normalizer already coexist. ✅

## 7. Anti-patterns to avoid (from the deck's own warnings + ShopSquire's constraints)
1. **Don't grant live authority before attribution exists** (deck: "confidently make things worse"). Build 1 first.
2. **Don't put segment/competitor/offer flavour in core** — the flavour ratchet will fail the build. Use profile slots.
3. **Don't let LLM copy generation execute directly** — route through `copywriting` (claim-stripped) + templates + policy gate.
4. **Don't flip behavioral defaults without bench/uplift data** — same discipline already applied to narration mode.
5. **Don't skip the kill-switch + decision-log on any new autonomous path** — every existing autonomous subsystem has both.

---

## 8. Concrete first PR (if approved)
1. Alembic migration: `recommendation_decision` + `conversion_event`.
2. `services/attribution.py` (core) — `record_decision()`, `attribute_order()`, `attribution_window_h` config; parity-tested across profiles.
3. Emit a decision row in `recommend.py:suggest()`; link on order via Celery (`tasks/attribution_tasks.py`) or order webhook.
4. Set `recommendation_bandit` reward = attributed conversion.
5. `admin_bi` endpoint: conversion-rate / revenue by arm+variant (read-only dashboard).
6. Feature-flag `ATTRIBUTION_ENABLED` (default on — measurement only, no behavior change).

This is agnostic, low-risk, reuses the existing spine, and turns ShopSquire's already-shipping recommendations into a *measured* system — the foundation everything else in David's deck stands on.
