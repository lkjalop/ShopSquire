# Spatiotemporal Capability — Assessment, Delta Gap, and Comparison

**Date:** 2026-08-12 · **HEAD:** `86a1efb3` · Row counts measured from the live demo database

---

## 1. Three different things get called "spatiotemporal"

They have different costs and different payoffs. ShopSquire has built all three unevenly.

| Axis | Question it answers | ShopSquire surface |
|---|---|---|
| **Valid time** ("when was this true in the world") | "Was that price correct on the 8th?" | `valid_from` / `valid_to` on `decision_logs` |
| **Transaction time** ("when did we learn it") | "What did we know when we decided?" | `decision_logs` (399,612 rows), `fulfillment_case_version` (2,559) |
| **Space** ("where is it") | "Can 30 units reach Melbourne in 2 days?" | per-location availability, transfer modelling, `data_residency`, `geoip` |

**Bitemporal** = the first two together. It is standard in banking, insurance and reinsurance, and
genuinely rare in commerce. It is the reason you can answer *"why did the system recommend that,
on what evidence, as at the date it decided"* six months later — even after the price changed, the
stock moved and the supplier requalified.

---

## 2. Why you would want it — and why you might not

### Want it

- **Audit defensibility.** A 30-unit, $180k purchase gets questioned. Without transaction time you can only show today's state; with it you show what was known at decision time. That is the difference between "we think it was fine" and a record.
- **Retractability without deletion.** A wrong interpretation can be superseded rather than erased — the belief-state ledger already does this. Regulated buyers cannot destroy the prior record.
- **Price and availability are volatile.** Your own ingest caught the same URL serving $2,899 then $4,799 minutes apart. Any "good price" claim without a timestamp is unverifiable.
- **Deadline feasibility is inherently spatiotemporal.** "7 local now, 23 transfer" is a space claim; "in 2 days" is a time claim; the verdict needs both.
- **Forecasting requires history.** No time series, no demand signal, no reorder point.

### Don't want it

- **Storage and query cost.** 399,612 decision rows for a demo. Bitemporal queries need `AS OF` semantics and careful indexing or they get slow.
- **Modelling complexity.** Every fact gains two time dimensions. Most developers get bitemporal joins wrong, and the bugs are subtle.
- **Most commerce doesn't need it.** For a consumer buying one laptop, "why did you recommend this in March" is never asked. The value is concentrated in **regulated, high-value, audited, multi-unit** buying.
- **It is a cost centre until something reads it.** Which is exactly ShopSquire's current problem.

---

## 3. Measured state — recording is dense, reasoning is empty

This single contrast is the whole assessment:

```
WRITTEN (dense)                         READ BACK / REASONED OVER (empty)
decision_logs              399,612      forecast_actual_pair                 0
market_signal                5,805      forecast_intelligence_evaluation     0
sales_metrics                4,883      price_history                        0
fulfillment_case_version     2,559      temporal_cache_generation            0
marketing_event_fact         2,317      temporal_cache_rebuild_job           0
market_finding                 922      temporal_cache_binding               0
fulfillment_case               784      inventory_reorder_proposal           0
orders / draft_orders          710/713  inventory_external_stock             0
market_signal_rollup           203      allocation_shadow_parity_run         0
price_book_entry               150
product_availability_obs        26
hippograph_journey_edges        77
temporal_dependency             21
```

**The platform is an excellent recorder and a non-existent forecaster.** It captures ~400k
time-stamped decisions and then never scores a single forecast against an actual, never builds a
price series, never proposes a reorder, and never uses its temporal cache.

`price_history = 0` is the sharpest single gap. Every "is this good value", "has this moved",
"undercut detection" and "should we buy now or wait" question is unanswerable — and your own
inventory work identified price volatility as the reason to timestamp per fetch.

---

## 4. Delta gap by domain

### Market intelligence
**Have:** 5,805 signals, 922 findings, 203 rollups, 30 hippograph/market modules, a real ingestion
pipeline with observability, competitor price-book entries (150).
**Gap:** it is **shadow-only** — `HIPPOGRAPH_FEEDBACK_ENABLED=shadow`, and the launcher comment says
outright that market intel *"appears in the decision trace, does NOT steer the buyer."* So 5,805
signals inform nothing. With `price_history = 0` there is also no trend, only point-in-time facts.
**Needed:** a governed path from finding → recommendation influence, with the same evidence
discipline as workload research. This is the largest built-but-dark asset in the codebase.

### Sales metrics
**Have:** 4,883 rows, 2,317 marketing event facts, 710 orders.
**Gap:** descriptive only. No cohort, no elasticity, no attribution over time, no feedback into
ranking. Nothing reads them for a decision.
**Needed:** close one loop end-to-end — e.g. conversion by fit-verdict class — to prove the
recording has purpose.

### Procurement journeys
**Have:** the strongest temporal work in the project. 784 cases with **2,559 versions** — genuinely
bitemporal, revision-bound supplier choices, quarantined responses, human-gated sends.
**Gap:** unreachable from chat (the clarification-interrupt defect). Also `fulfillment_draft_retry = 0`
and `allocation_shadow_parity_run = 0` — the resilience paths have never executed.
**Needed:** the clamp. Everything else here is built.

### External search
**Have:** freshness SLAs declared per publisher (168h / 720h / 72h), `observed_at` on claims, content
hashes, an evidence cache.
**Gap:** the cache is not visible in the trace (`cache_hit` vs `network_execution` indistinguishable),
staleness is never *acted* on — nothing re-fetches when an SLA expires — and `temporal_cache_*`
tables are all empty, so the temporal cache machinery is unused.
**Needed:** SLA-driven refresh, and surface cache age on the card. Cheap, high credibility.

### Bulk orders
**Have:** the best spatiotemporal reasoning in the product — per-location stock, transfer modelling,
shortfall, `promise_feasibility`, `evaluate_critical_path`, and honest refusal to promise a date
without carrier evidence.
**Gap:** only **26 availability observations** across 12 configurations (~2 each), `inventory_external_stock = 0`,
no dated carrier data. So feasibility reasons over almost no spatial data. And it is unreachable
from chat.
**Needed:** real per-location feeds. The reasoning is ahead of its inputs.

---

## 5. What is broken

1. **No price time series** (`price_history = 0`) — blocks all value/trend reasoning.
2. **Forecasting never evaluated** (`forecast_actual_pair = 0`) — a forecast that is never scored is an opinion.
3. **Market intel is dark** — 5,805 signals, shadow-only, steering nothing.
4. **Temporal cache unused** — three tables at zero.
5. **Spatial data too thin to reason on** — 26 observations, no external stock feed.
6. **Freshness declared but not enforced** — SLAs exist; nothing expires or refreshes.
7. **Reorder proposals never generated** (`inventory_reorder_proposal = 0`).
8. **The whole spatiotemporal commercial layer is behind the clarification-interrupt bug.**

---

## 6. How this compares to adjacent platforms

Framed by category, since specific vendor feature sets change and I have not verified them.

| Category | What they do well | Where ShopSquire is genuinely ahead | Where it is behind |
|---|---|---|---|
| **Commerce search/reco** (Algolia, Constructor, Bloomreach, Coveo class) | Real-time behavioural ranking, trending, personalisation, sub-100ms at scale | **Provenance per claim and refusal.** These platforms rank; almost none can say *why* a product qualifies or decline to claim fit | Scale, latency, behavioural signal, catalogue breadth. Not close |
| **Source-to-pay** (Coupa, Ariba, Jaggaer class) | Spend analytics over time, supplier performance history, contract lifecycle, approval workflow | **Evidence-bound requirements.** These start from a requisition; ShopSquire derives the requirement from authoritative sources and shows which publisher established it | Supplier master data, contract management, invoice matching, real spend history |
| **DSPM / AI governance** (the Securiti/BigID/Cyera class) | Data discovery and classification at estate scale, access lineage over time | **AI-decision** lineage rather than data lineage — recording why an agent decided, not just who touched data | Estate-scale discovery, connector breadth, real deployments |
| **Inventory / OMS** (NetSuite, Manhattan, Blue Yonder class) | Multi-echelon ATP, demand forecasting, allocation at scale | **Honesty about unverified dates.** Most systems promise a date; ShopSquire refuses without carrier evidence and says who must verify | Forecasting (zero), real feeds, allocation maturity, scale |
| **Agentic shopping** (Rufus, OLX Magic, Perplexity-shopping class) | Conversational intent, huge catalogues, production traffic | **Governance, consent-gated research, audit, local inference** | Catalogue (12 evidence-grade rows), traffic, model scale |

### The honest positioning

ShopSquire is not competitive on **scale, breadth, forecasting or latency** against any of those
categories, and will not become so.

It is differentiated on one axis that is genuinely uncommon across all five: **a bitemporal record
of why an AI decided what it decided, with per-claim provenance and an explicit refusal
vocabulary.** Commerce platforms rank but do not justify. Procurement platforms approve but do not
derive requirements from evidence. DSPM tracks data but not agent decisions. OMS promises dates.
Agentic shoppers are confident.

The nearest true analogue is not a commerce product at all — it is **bitemporal record-keeping from
financial systems, applied to AI decisions.** That is a defensible and unusual position, and it is
the half that is 399,612 rows deep.

---

## 7. What I would do about it

1. **Add `price_history`.** One table, timestamped per fetch. Unblocks trend, value and undercut reasoning, and your ingest already argues for it.
2. **Score one forecast.** Populate `forecast_actual_pair` for a single metric. An unscored forecast is not intelligence.
3. **Surface cache age and enforce one freshness SLA.** Expire and re-fetch when a publisher SLA lapses; show `cache_hit` distinctly. Cheap, and it makes the temporal claim real.
4. **Give market intel one governed path to influence** — a single finding type, evidence-gated, out of shadow.
5. **Thicken availability observations** before extending feasibility logic. The reasoning is ahead of its inputs; more logic on 26 observations adds nothing.

Ordering note: none of 1–5 outranks the clarification-interrupt clamp, which is still what makes the
entire spatiotemporal commercial layer reachable at all.
