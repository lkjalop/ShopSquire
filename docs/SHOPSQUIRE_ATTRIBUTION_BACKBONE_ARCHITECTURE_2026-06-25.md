# ShopSquire Attribution Backbone — Architecture & Wiring Deep Dive

**Date:** 2026-06-25
**Author:** Claude Opus 4.8 (4-explorer codebase sweep with file:line evidence)
**Status:** Design / theory. Line numbers are **anchors — re-verify before editing** (recommend.py/orchestrator.py are large and churn).
**Companion doc:** `SHOPSQUIRE_MARKET_INTELLIGENCE_ADAPTIVE_GROWTH_IMPLEMENTATION_2026-06-25.md`

---

## 0. Thesis: the backbone is 60% latent — connect the loop, don't rebuild it

Three discoveries change the build from "new subsystem" to "wire the missing edges":

1. **The write primitive already exists.** `decision_log.record_commerce_outcome(decision_id, *, conversion, upsell_clicked, bundle_purchased, aov_delta_cents, …)` (`services/decision_log.py:1033–1094`) creates a new bitemporal `decision_logs` row with `event_type="commerce_outcome"` that **supersedes** the original decision (`supersedes_decision_id`, line 1090). That *is* an attribution record.
2. **The interaction sink already has trace_id.** `recommend_interactions` (`services/checkout_upsell.py:258–277`) already has columns `(uid_hash, sku, action, surface, trace_id, context_json)`, and the ALS trainer weights `purchase/order=2.2×, add_to_cart=1.5×, click=1.0×, view=0.4×` (`services/recommendation_als.py:50–62`).
3. **The decision IDs already converge.** In `routers/recommend.py`, `trace_id` is minted at **line 4380**, `decision_id` is set at **line 9741** (`decision_id = decision_id or trace_id`), and both land in the response payload assembled at **lines 10175–10237**, wrapped by `_with_trace()` at **line 10238**.

**What's missing is three edges:**
- (E1) Orders don't carry `trace_id`/`decision_id` (`models/orm.py:51–60`); the cart's own `trace_id` (`routers/cart.py:171–173`, `"cart:{cart_id}"`) is dropped at order creation (`routers/orders.py:146`, `206–208`).
- (E2) Nothing calls `record_commerce_outcome()` when an order is created.
- (E3) The bandit's reward is an undefined input — `record_bandit_reward(db, *, uid_hash, sku, arm, reward, context)` (`services/recommendation_bandit.py:157–233`) takes `reward: float` but **no code derives it from a conversion**.

Close E1–E3 and you have a measured system. Everything else (intelligence store, decision engine, comms) builds on that loop.

---

## 1. Agnostic-first design (the non-negotiable shape)

### 1.1 The core module
New **`src/app/services/attribution.py`** → added to `_CORE_MODULES` in `tests/test_no_flavour_in_core.py`. **Zero product vocabulary** — it speaks only `decision_id / trace_id / sku / uid_hash / action / value_cents / window`. It is a pure function library over injected data (same shape as `availability_agent.py`, the canonical core example).

```python
# src/app/services/attribution.py  (CORE — vertical-blind)
def record_decision(*, trace_id, decision_id, skus, arm, variant,
                    uid_hash, surface, context) -> None: ...
    # writes recommendation_decision row; never raises

def attribute_order(*, order_id, trace_id, uid_hash, value_cents,
                    line_skus, window_s, now_ts) -> AttributionResult: ...
    # finds the decision within window, writes conversion_event,
    # calls record_commerce_outcome(), emits recommend_interactions(action="order")

def reward_from_outcome(outcome: AttributionResult) -> float: ...
    # deterministic, bounded [0,1] reward — the bandit's missing signal
```

**Why a new core module, not inline in recommend.py:** recommend.py is on the flavour ratchet (~14 tokens) and is 11,980 lines — adding attribution there fails the silent-except ratchet and worsens the monolith. A core service is testable across profiles (electronics/fashion/pharmacy) by `test_profile_parity.py`.

### 1.2 What stays in the adapter (profile slots)
The *mechanism* is agnostic; the *tuning* is vertical flavour → `config/store_profiles/*.json` new slots:
- `attribution_window_seconds` (electronics: a laptop is researched for days → e.g. 7d; pharmacy: minutes).
- `attribution_action_weights` (override the ALS weights per vertical).
- `conversion_value_floor_cents` (ignore noise below a vertical-specific floor).

### 1.3 Data model (two new tables; follow the alembic pattern)
Follow `alembic/versions/20260214_*.py` conventions (`revision`/`down_revision`, `_ensure_col` helper, `op.create_table`, `server_default=CURRENT_TIMESTAMP`; portable via `db.py`'s `now()`→`CURRENT_TIMESTAMP` rewrite at line 1088 and `INSERT OR REPLACE` on SQLite at 1098):

```sql
recommendation_decision(
  id PK, trace_id, decision_id, uid_hash, surface, arm, variant,
  skus_json, context_json, created_at,
  valid_from, valid_to, system_from, system_to)        -- bitemporal, like decision_logs

conversion_event(
  id PK, decision_id FK, order_id FK, uid_hash,
  attributed_skus_json, value_cents, window_s,
  attribution_model, converted_at, created_at)
```
Plus **one column add** to `orders` (and mirror on `order_sessions`): `trace_id TEXT, decision_id TEXT`.

**Why bitemporal:** it matches `decision_logs` (valid_from/valid_to/system_from/system_to written at `decision_log.py:426–429`) so attribution participates in the existing **replay** (`decision_replay.py`) and **audit chain** (`audit_chain.py`) for free — "as of last Tuesday, which decision did we credit this order to?" is answerable.

---

## 2. Exact wiring (the edges, by file:line)

### Edge E0 — emit the decision row (capture)
**Where:** `routers/recommend.py:10238`, immediately after `payload = _with_trace({...}, trace_id)` — the single point where `results`, `trace_id`, and `decision_id` all exist.
**Do:** `attribution.record_decision(trace_id, decision_id, skus=[r["sku"] for r in results], arm=proposal.get("ab_variant"/arm), variant=..., uid_hash=_hash(uid), surface="recommend", context={budget, use_case})`.
**Bounded:** fire-and-forget in a `safe_stage` wrapper (never block the response; never raise — same discipline as `record_partial_failure`). Sample at high volume.

### Edge E1 — carry trace_id cart → order
**Where:** the cart already computes `_cart_trace_id(cart_id)` (`cart.py:117`) and hydrates `trace_id`/`decision_trace_id` (`cart.py:171–173`). Plumb it into `OrderCreate` and persist at `orders.py:146` (order insert) and the `order_sessions` insert at `orders.py:206–208`.
**Why:** the cart's trace_id is the bridge from the recommendation decision to the purchase. Today it dies at the cart boundary.

### Edge E2 — close the loop at order creation
**Where:** end of `create_order()` (`orders.py:~210`, after the atomic insert, before return).
**Do:** `attribution.attribute_order(order_id, trace_id, uid_hash, value_cents=total_cents, line_skus=..., window_s=profile_slot("attribution_window_seconds"))`. Internally this calls the **existing** `record_commerce_outcome(decision_id, conversion=True, aov_delta_cents=total_cents, …)` (`decision_log.py:1033`) and inserts `recommend_interactions(action="order", trace_id=…)` (table at `checkout_upsell.py:258`).
**Bounded:** idempotent on `(order_id)` — an order can only be attributed once (the Idempotency middleware fingerprint at `idempotency.py:38–52` protects the endpoint; the attribution write itself guards on order_id PK).

### Edge E3 — feed the bandit (the missing reward)
**Where:** a new Celery task `tasks/attribution_tasks.py` (Celery + HMAC-signed, per `workers/celery_app.py`), scheduled via beat. It reads recent `conversion_event` rows and calls `record_bandit_reward(db, uid_hash=…, sku=…, arm=…, reward=attribution.reward_from_outcome(…), context=…)` (`recommendation_bandit.py:157`).
**Why a batch job, not inline:** decouples the reward from the hot path; lets the **attribution window** elapse (a click now, a purchase in 3 days); and is the natural quarantine point (see §6).
**Bounded:** reward clamped `[0,1]`; only orders past the fraud/return settling window count; deduped per `conversion_event.id`.

### Result: the loop
`suggest()` → `record_decision` → user buys → `create_order` → `attribute_order` → `record_commerce_outcome` + `recommend_interactions` → nightly `attribution_tasks` → `record_bandit_reward` + `trend_indicator`. The bandit (`choose_recommendation_arm`, `recommendation_bandit.py:100`) and ALS trainer (`recommendation_als.py:65`) now learn from *ground truth* instead of an undefined signal.

---

## 3. How attribution threads through the architecture

### 3.1 Scatter-gather / agentic swarm (orchestrator.py)
The orchestrator runs a 4-phase swarm — EXPLORE (`orchestrator.py:1005–1117`/`2773–3062`), EVALUATE (`1119–1610`/`3063–3231`, with parallel `_inv_task` 1129 + `_fraud_task` 1192 gathered by `asyncio.gather` in `_run_phase2` 1273), PLAN (`1748`/`3233`), ACTION (`3319–3434`). Each agent already emits trace events (`log_trace_event`, the swarm produced 43 events/26 agents in this session's audit).

**Attribution rides the trace, not a parallel pipe.** The `decision_id` is the join key: every agent's contribution (which arm `choose_recommendation_arm` picked, which signals fraud saw, whether availability injected an OOS penalty) is already a trace event under that `trace_id`. So attribution can answer *"which agent/arm/signal correlated with conversion"* by joining `conversion_event.decision_id` → `decision_trace_events.trace_id`. **No new instrumentation in the swarm** — only the outcome edge (E2) is new.

**One addition:** stamp the chosen **arm/variant** into the `OrchestratorResult.proposal` (it already carries `ab_variant`, `proposal.py` ~line 1637) so `record_decision` captures it. That makes per-arm uplift measurable.

### 3.2 External search
`external_product_research_service.research()` (`:72–85`, disabled by default, PII-scrubbed, allowlisted, tenant-namespaced cache `:94–97`) returns "also-sold-elsewhere" context labelled **not-sold-here** (`:126–135`). Attribution treats it as an **input feature to measure, not act on**: record whether a decision *included* external-research context, then measure if those decisions convert better/worse. **Bounded:** research never enters the cart; it's a context flag on `recommendation_decision.context_json`, never a product.

### 3.3 Inventory / ERP consultation
`inventory_query_service.get_stock_level()` (direct DB, parameterized, injection-guarded `:29–37`) and `availability_agent.assess_availability()` (core, with the per-SKU `allocation` evidence we added this session) are **inputs** attribution correlates: *did the OOS rank penalty (recommend.py ~10773) or a shortfall allocation correlate with abandonment?* Attribution closes the analysis loop the deck's M3 wants ("inventory-demand misalignment").

### 3.4 Inventory reordering & supplier communications
This is where attribution **feeds back outward** — and must stay bounded. A high-converting, low-stock SKU is a demand signal → `reorder_supplier_flow.plan_reorder_with_supplier_draft()` (`:17–28`). **Critical invariant preserved:** that function is **draft-only** (`status="awaiting_human_approval"`), and `supplier_contact` is hard-gated to **HUMAN_REVIEW** in the authority matrix (rule SUP-04, `action_authority_matrix.py:145–152`). So attribution may *raise* a reorder draft but **can never auto-send a PO**. Supplier domain is allowlist-validated (`supplier_domain_guard.is_trusted_supplier_domain`, fail-closed `:80–100`) to stop attribution-driven BEC.

> **Design rule:** attribution is allowed to *propose* into the inventory/supplier loop, never to *execute*. The forecast it feeds is anti-poison-quarantined (`demand_forecast._quarantine_and_weight:66–87`).

---

## 4. How the engine feeds the 7 modules — bounded / reviewed / throttled

| Target module | What attribution sends | Bound / review / throttle |
|---|---|---|
| **Signal Ingestion (M1)** | `conversion_event` → a `market_signal` of type `conversion` | **Bound:** uid is hashed (`uid_hash`, never raw — bandit table at `recommendation_bandit.py:33–44`); no PII in `context_json`. **Throttle:** batched via `begin_trace_batch`/`flush_trace_batch` (`decision_log.py:61–98`). |
| **Intelligence Store (M2)** | `trend_indicator` rows (conversion rate by arm/segment/day) | **Bound:** retention policy; bitemporal so corrections don't overwrite history. |
| **Analysis Engine (M3)** | the **ground-truth label** for uplift / anomaly | **Review:** min-sample gate before any finding is actionable (mirror `fraud_scorer.compute_signal_multipliers` min_samples + `[0.5,1.5]` clamp `:71–107`). |
| **Decision Engine (M4)** | attributed uplift → bandit reward + ranking nudge | **Review:** changes routed through `escalation_policy.assess_escalation` bands (`:84`, review_at 0.35 / human_at 0.60) and `action_authority_matrix.evaluate` (`:213`); low-confidence → BAND_REVIEW (logged, not executed). |
| **Comms Orchestrator (M5)** | "this arm/message converts better" | **Bound:** only *reversible* nudges (ranking, phrasing) auto-apply; offers/discounts → HUMAN_REVIEW. **Throttle:** new `contact_frequency_ledger` (the one missing governance primitive) before any outbound. |
| **Policy/Governance/Audit (M7)** | every attribution write | **Bound:** chained into `audit_chain.chain_new_record` (`:142–180`, SHA-256 + WORM + HMAC); replayable via `decision_replay`. The **reward feed is the highest-risk surface** → see §6. |
| **(cross) Comms execution** | nothing executes without `assert_autonomy_allowed` | **Kill switch:** `kill_switch.assert_autonomy_allowed(scope="attribution", …)` (`:170–194`), 4-level hierarchy, fail-closed 503. |

**The governing principle (David's deck, slide 15):** *AI interprets and proposes; Policy authorizes; Automation executes; Audit records.* Attribution is firmly in **"interprets / proposes"** — it measures and recommends a reward/uplift; the existing policy gate + escalation bands + kill switch decide whether anything acts on it.

---

## 5. recommend.py / orchestrator.py / main.py — extract, excise, combine

The attribution work is the right moment to pay down the three god-files, because attribution needs **clean seams** (a capture point, an outcome point) that a monolith obscures.

### 5.1 recommend.py (11,980 lines) — EXTRACT
| Block | Lines | → new module | Why (for attribution) |
|---|---|---|---|
| Fast-path catalog | 1036–1290 | `recommend_fast_path.py` | fast path must *also* emit a decision row; isolate it |
| Query understanding | 2019–2270 | `recommend_query_understanding.py` | the decision's "why" context lives here |
| Constraint building | ~5552–6750 (scattered) | `recommend_constraint_builder.py` | `context_json` for attribution = these constraints |
| Retrieval stage | 8066–8280 | (extend `recommend_pipeline.py`) | scatter-gather already partly extracted |
| Result assembly | 9950–10074 | (extend `recommend_response_finalizer.py`) | the `results` list attribution captures |
| **Decision capture** | **insert at 10238** | calls `attribution.record_decision` | the convergence seam (E0) |
**Excise:** the inline electronics flavour (gaming/GPU/RTX/144Hz/brand literals across ~30 line clusters) → `electronics.json` slots, lowering the `_PENDING_EXCISION` ratchet (currently ~14). Attribution code must not add any.
**Goal:** recommend.py becomes a thin handler that *orchestrates stages* and *emits one decision row*.

### 5.2 orchestrator.py (4,009 lines) — COMBINE & EXTRACT
| Concern | Lines | → module | Why |
|---|---|---|---|
| Adaptive agent budgets | 271–363 | `agent_budgets.py` | pure function; reusable; testable |
| Parallel exec (`_inv_task`/`_fraud_task`/`_run_phase2`) | 1129–1281 | `parallel_agent_executor.py` (exists — move into it) | the scatter-gather attribution joins on |
| Phase tracing | 376–455 | `phase_tracer.py` | unify the trace events attribution reads |
| Incident/escalation ticketing | 481–654 | `incident_manager.py` | shared with attribution-driven escalation |
| Proposal assembly | 1637–1662 / 3180–3225 | `_build_proposal()` consolidated | **stamp arm/variant here** for attribution |
**Combine:** the duplicated phase logic between `run_nlp_cv` and `_run_internal` (two code paths writing the same proposal) — collapse so there's **one** place that stamps the decision's arm/variant.

### 5.3 main.py (2,341 lines) — EXTRACT (pure hygiene, enables clean middleware order)
| Block | Lines | → module |
|---|---|---|
| Middleware stack | 609–728 | `middleware_stack.py` (returns ordered list) |
| Router registry | 1622–2020+ (~80 routers) | `routers_registry.py` (grouped, flag-gated) |
| Lifespan startup | 174–472 | `startup_db.py` / `startup_seed.py` / `startup_cv.py` / `startup_models.py` |
| Backpressure mw | 731–1006 | `concurrency_limiter.py` + `rate_limiter.py` + `chaos_injector.py` |
| Observer mw | 1104–1264 | `observer_middleware.py` |
**Why it matters for attribution:** the `TraceBatchMiddleware` (717→726) and `StoreProfileMiddleware` (717) ordering is what makes batched, tenant-scoped attribution writes correct. Extracting the stack makes that ordering explicit and testable. **Do this LAST** (no behavior change, pure risk).

> Sequencing: do **E0–E3 first** (small, high-value), then extract the seams the attribution touched (5.1), then orchestrator (5.2), then main.py (5.3). Never extract and add behavior in the same PR.

---

## 6. Attack defense — attribution is a high-value poisoning target

Attribution data **feeds a learning loop** (bandit reward, ALS weights, demand forecast). That makes it the juiciest target in the system: poison the reward and you steer what gets recommended, reordered, and promoted. Threat model + the existing primitive that defends each:

| # | Attack | Vector | Defense (existing primitive) | New control needed |
|---|---|---|---|---|
| 1 | **Reward poisoning** | Fake conversions inflate an arm/SKU → bandit over-recommends attacker's SKU | Anti-poison quarantine pattern (`demand_forecast._quarantine_and_weight:66–87`); fraud-signal multiplier clamp `[0.5,1.5]` + min_samples (`fraud_scorer:71–107`) | Apply the SAME quarantine to `reward_from_outcome`: median-baseline, trust-weight, cap per-uid contribution; **only settled (post-return-window) orders count** |
| 2 | **Fake/replayed conversions** | Replay an order-create or forge `conversion_event` | Idempotency fingerprint includes body+path (`idempotency.py:38–52`); order_id PK; audit chain detects forged rows (`audit_chain.verify_chain:183–223`) | Attribution write idempotent on `order_id`; require the order to exist + be `paid` before crediting |
| 3 | **Self-attribution / click fraud** | Bot generates decisions+orders to farm reward | fraud_scorer 26+ signals incl. velocity/ring/JA3/JA4 (`:111–150`); customer_trust_scores | Gate reward on `fraud_score < noise_floor` (0.10) AND trust≥threshold; rate-limit per uid_hash |
| 4 | **Cross-tenant leakage** | Tenant A reads B's conversion/SKU data | ContextVar profile isolation (`store_profile.active_profile_id:28–64`); tenant registry fail-closed; research cache namespaced (`:94–97`) | `recommendation_decision`/`conversion_event` carry tenant/profile id; all queries tenant-scoped |
| 5 | **PII leakage** | Raw email/uid in attribution rows | bandit tables already use `uid_hash` not raw uid (`recommendation_bandit.py:33–44`); consumer_signals hashing | Attribution stores **only** `uid_hash` (salted SHA-256); `context_json` numeric/categorical only; redaction in post-pipeline |
| 6 | **SSRF via "research drove conversion"** | Attribution context references external URL → later fetch hits internal host | `external_research_httpx._host_is_safe:45–66` blocks private IPs; `follow_redirects=False`; domain allowlist | Never store fetchable URLs in attribution; store only the boolean "research_present" + source_domain |
| 7 | **Attribution-driven autonomy escape** | Spoofed "high uplift" flips a kill switch / bypasses escalation | `kill_switch.assert_autonomy_allowed` 4-level env-first hierarchy (`:170–194`); `escalation_policy` hard overrides (fraud_hard 0.70) regardless of soft score (`:138`); authority matrix fail-closed HUMAN_REVIEW (`:268–288`) | Attribution output is advisory only; any action it suggests re-enters the gate from zero trust |
| 8 | **Audit tampering** | Rewrite history to hide a poisoned decision | SHA-256 hash chain + `prev_hash` continuity + WORM `O_APPEND` + HMAC secret fail-closed in prod (`audit_chain.py:43–140`) | Chain every `conversion_event`/reward write; periodic `verify_chain` job |

**The cardinal defense:** attribution **measures and proposes; it never executes.** Every downstream action (reorder, offer, message, ranking change) re-enters the existing policy gate → escalation bands → kill switch → audit chain. Determinism over learning for the *gates*; learning only for the *ranking it proposes*. And the reward feed is **batch + quarantined + settled-orders-only**, so a burst of fake conversions can't move the model before fraud/returns catch it.

---

## 7. First PR (smallest end-to-end slice)
1. Alembic migration: `recommendation_decision` + `conversion_event` + `orders.trace_id/decision_id` (follow `20260214_*` pattern).
2. `services/attribution.py` (core) — `record_decision`, `attribute_order`, `reward_from_outcome`; add to `_CORE_MODULES`; parity test across profiles.
3. Wire **E0** at `recommend.py:10238` (safe_stage, non-blocking), **E1** at `cart.py:171`→`orders.py:146/206`, **E2** at end of `create_order` (calls existing `record_commerce_outcome`).
4. `tasks/attribution_tasks.py` (**E3**) — settled-order reward feed with quarantine; sets bandit reward.
5. `admin_bi` endpoint: conversion-rate + revenue by arm/variant (read-only).
6. Flags: `ATTRIBUTION_ENABLED` (capture on by default — measurement only), `ATTRIBUTION_REWARD_FEED_ENABLED` (default OFF until the quarantine is bench-validated).
7. Profile slots: `attribution_window_seconds`, `attribution_action_weights`, `conversion_value_floor_cents`.

**Risk:** capture (E0–E2) is read-mostly measurement — low risk, default-on. The learning feed (E3) is the only behavior-changing part — default-OFF behind a flag until §6 controls #1/#3 are validated. This mirrors ShopSquire's existing "don't flip behavioral defaults without bench data" discipline.
