# ShopSquire — Delta Assessment + Canonical Semantics Specification (2026-07-28)

*Part A: what moved in the last 24h, file by file, with business rationale and alternatives.
Part B: the nine definitional specifications requested.*

---

# PART A — DELTA & TRAJECTORY

## A.0 Headline: the trajectory turned, and it turned the right way

Yesterday I flagged **B0: the V2 cutover is uncommitted**. It is now committed
(`f6d4f24a feat(recommend): cut production routing to V2 compatibility`). **B0 closed.**

More significantly, the working tree has pivoted **hard into the exact quadrant** the positioning
analysis pointed at — ERP connectivity, inventory governance, authoritative feeds, account
intelligence, tenant membership. This is not drift; it is the wholesale/self-hosted thesis being
built.

| Measure | 2026-07-27 | 2026-07-28 | Δ |
|---|---:|---:|---:|
| Commits ahead | — | **+7** | cutover committed |
| Modified files | 37 | **65** | +28 |
| Untracked files | 20 | **46** | +26 |
| Insertions (tracked) | 1,173 | **2,086** | +913 |
| New-file LOC (untracked code) | ~1,470 | **4,052** | +2,582 |
| New alembic migrations | 3 | **12** | +9 |

**Net new engineering in 24h: ~6,100 lines.** That is a very high rate. It is also the single
biggest risk in this document — see §A.4.

---

## A.1 New services — file by file

| File | LOC | What it does | Business reason | Alternative approach |
|---|---:|---|---|---|
| `services/inventory_reorder_execution.py` | **537** | Governed reorder execution with claims/idempotency | Turns "propose a reorder" into "execute it exactly once, provably". The claim table is what stops a double-order — the money-path idempotency lesson applied to stock | **Alt:** push execution into the ERP entirely (Odoo/NetSuite own reorder). *Cheaper, but you lose the governed-proposal story — which is the product.* **Verdict: current approach right.** |
| `erp/connector_runtime.py` | **313** | Connector lifecycle: health, retry, circuit-breaking, reliability accounting | Self-hosted means *their* ERP will be down and you must degrade honestly, not silently. Directly serves the sovereign posture | **Alt:** let each connector handle its own failures. *Rejected correctly — that's how you get 8 different retry semantics and a silent-swallow class.* |
| `services/account_intelligence.py` | **221** | Party/identity resolution — **exact external-ID match only** | The CRM-without-a-CRM play from yesterday's analysis. Exact-only is deliberately conservative | See **§B.5** — this is where merge/split thresholds must go, and the current exact-only posture is the correct v1 |
| `services/operator_tenant_membership.py` | **219** | Operator↔tenant membership as durable data | **This is B2.** Tenant identity stops being an asserted header and becomes a membership fact | **Alt:** OIDC claims only. *Better long-term, but membership table is the right self-hosted answer — no IdP required.* |
| `services/product_lifecycle.py` | **200** | Product lifecycle states (intro/active/EOL/discontinued) | Wholesale distributors live or die on EOL and run-out planning. Also feeds dead-stock and markdown logic | **Alt:** derive lifecycle from velocity. *Weaker — a distributor* knows *when a line is discontinued; ask, don't infer.* |
| `services/authoritative_business_feed.py` | **198** | Canonical ingestion of 10 business entity types, hash-canonicalised, CSV+API | **The most strategically important file in the batch.** It is the seam that makes ShopSquire ERP-agnostic | See **§B.1/§B.2** — the slots exist; **the semantics do not** |
| `services/communication_observations.py` | **98** | Communications as observations | Feeds the account timeline; keeps comms evidence out of the decision path | Fine as-is |
| `services/inventory_intelligence.py` | **72** | Inventory-derived signals | Thin wrapper; correct size | — |
| `services/connector_email_ingress.py` | — | Email→connector ingress | Supplier replies as structured evidence | — |
| `tasks/connector_recovery_tasks.py` | — | Scheduled connector recovery | Unattended operation in someone else's perimeter | — |

## A.2 Reworked ERP layer

| File | Δ lines | Assessment |
|---|---:|---|
| `erp/connectors/netsuite.py` | **234** | Substantial rework of the only real deep connector. Correct target — NetSuite is the ANZ mid-market distribution default |
| `erp/connectors/provider_sync.py` | **232** | The generic engine got hardened. Highest-leverage file in the ERP layer — every future provider inherits it |
| `erp/sync.py` | **223** | Sync orchestration |
| `erp/jobs.py` / `jobs_generic.py` | 88 / 68 | Job plumbing |
| `routers/inventory.py` | **21 +, 75 −** | **Net −54.** A router *shrinking* as logic moves to services. Exactly the right direction — this is the anti-`recommend.py` pattern |
| `connectors/accounting/xero.py` | 14 | Xero exists. Correct — the ANZ SMB default I flagged as missing |
| `services/inventory_agent.py` | 110 | |
| `services/supplier_catalog.py` | 59 | |
| `tasks/fulfillment_tasks.py` | **120** | |

## A.3 Frontend / UI-UX — the honest read

| File | Δ | What it actually is |
|---|---:|---|
| `frontend/src/App.tsx` | 14 | wiring |
| `frontend/src/components/CartPanel.tsx` | 15 | sourcing display tweak |
| `frontend/src/components/DecisionTrace.tsx` | **7** | test-id/selector only |
| `frontend/e2e/*.spec.ts` (5 files) | 62 total | selector stabilisation |
| `components/__tests__/CartPanel.sourcing.test.tsx` | 9 | test |

**There is no UI/UX change in this batch.** ~107 lines across 9 files, almost entirely
test-selector stabilisation. `DecisionTrace.tsx` moved **7 lines** — the 14-tab problem, the missing
"WHY NOT" panel, and the Account panel are all untouched.

**Business read:** backend capability is compounding at ~6,000 lines/day while the surface a buyer
actually sees is static. For a product whose entire thesis is *"the trace is the product"*, that is
the wrong ratio. **The WHY-NOT panel is still the highest value-per-line item available and it has
not started.**

## A.4 Trajectory risks — name them now

1. **⚠️ The batch is enormous and uncommitted.** 4,052 lines of new code, 65 modified files, **12
   unmerged migrations**. Yesterday's B0 was "commit 2,600 lines"; today it is ~6,100. The lesson did
   not stick. **Land it in slices today.**
2. **⚠️ 12 migrations in one batch** (`20260802`…`20260812`). Migration chains are the least
   reversible thing in the repo. Each needs a rehearsed down-path before it merges.
3. **⚠️ B1 (currency authority) and B3 (label sealing) have not moved.** Both are still open and both
   still block a pilot. New capability is being added *above* an unfixed correctness bug.
4. **✅ Genuinely good:** `inventory.py` shrank; `operator_tenant_membership` attacks B2; the ERP
   layer got a runtime instead of ad-hoc error handling.

**Trajectory verdict: direction excellent, batch discipline poor.** The work is aimed at the right
quadrant. The delivery pattern — 6,000 uncommitted lines with 12 pending migrations while two
correctness blockers sit open — is the thing that will hurt.

---

# PART B — THE NINE SPECIFICATIONS

## B.1 Canonical semantics: ATP, reservations, receipts, returns, valuation, landed cost

`authoritative_business_feed.py` already declares the slots:
```
order · order_line · location_atp · reservation · return · receipt
invoice · purchase_order · inventory_valuation · landed_cost
```
**The slots exist; the semantics do not.** The feed accepts any `payload` dict. Below is the contract.

### B.1.0 The governing rule

> **ShopSquire never computes stock truth. It reads it, names its basis, and says `unknown` when a
> component is absent.**

This is the tri-state doctrine applied to inventory. The failure mode it prevents is the expensive
one: treating `on_hand` as if it were available, promising stock that is already reserved.

### B.1.1 The three quantity planes — keep them separate

Odoo's core insight, which ShopSquire's feed already mirrors: **physical ≠ financial ≠ promisable.**

```
PHYSICAL   what is on the shelf            → on_hand
PROMISABLE what may be sold to a new order → ATP
FINANCIAL  what it is worth on the books   → valuation (+ landed cost)
```
Landed cost changes **financial** without touching **physical**. A reservation changes **promisable**
without touching **physical**. Conflating any two is the classic ERP-integration bug.

### B.1.2 ATP — Available To Promise

```
free_qty(sku, loc)      = on_hand − reserved                     [instantaneous]
ATP(sku, loc, t)        = free_qty
                        + Σ confirmed_inbound(due ≤ t)
                        − Σ committed_outbound(due ≤ t)
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `sku` | str | ✅ | tenant-scoped SKU |
| `location_id` | str | ✅ | `*` permitted only for single-location tenants |
| `on_hand` | int | ✅ | physical units |
| `reserved` | int | ⚠️ **see below** | allocated to existing demand |
| `inbound[]` | list | ⚪ | `{qty, due_date, confidence}` — confirmed POs only |
| `outbound[]` | list | ⚪ | `{qty, due_date}` — committed orders |
| `as_of` | ISO-8601 UTC | ✅ | source observation time, not ingest time |
| `basis` | enum | ✅ | `observed` \| `derived` \| `estimated` \| `unknown` |
| `uom` | str | ✅ | must match catalog UoM or reject |

**The critical rule:**
```
if reserved is None:
    atp        = None
    basis      = "unknown"
    reason     = "reservations_not_supplied"
    # NEVER: atp = on_hand
```
A feed that omits reservations cannot produce an ATP. It produces `unknown`, and the buyer-facing
answer becomes *"I can see 40 on hand but I can't confirm how many are already committed"* — which
is honest, useful, and safe.

**Staleness:** ATP older than `atp_ttl_seconds` (default **900s**) is `stale`; a stale ATP may inform
narration but **may not authorize a commitment**.

### B.1.3 Reservations

| Field | Required | Notes |
|---|---|---|
| `reservation_id` | ✅ | idempotency key |
| `sku`, `location_id`, `qty` | ✅ | |
| `demand_ref` | ✅ | order/case that owns it |
| `state` | ✅ | `held` \| `confirmed` \| `released` \| `consumed` \| `expired` |
| `expires_at` | ⚪ | soft holds must expire |

**Rules:**
1. **ShopSquire proposes reservations; the SoR grants them.** A local hold is advisory until the ERP
   confirms. Never present an unconfirmed hold as secured stock.
2. **Reservations are idempotent on `reservation_id`.** Replay must not double-hold. (Reuse the
   money-ledger `provider_ref` dedup pattern — it is already proven in this codebase.)
3. **Soft holds expire.** An unexpiring hold silently consumes ATP forever.
4. `consumed` transitions to a receipt/shipment; `released` returns qty to free.

### B.1.4 Receipts (goods receipt / GRN)

| Field | Required |
|---|---|
| `receipt_id`, `po_ref`, `sku`, `location_id` | ✅ |
| `qty_received`, `uom`, `received_at` | ✅ |
| `qty_rejected`, `reject_reason` | ⚪ |
| `unit_cost`, `currency` | ⚪ (drives valuation) |
| `lot_ids[]`, `expiry` | ⚪ (perishable verticals) |

**Rules:** a receipt increments on_hand **and** creates a valuation entry — never one without the
other. Over-receipt beyond PO qty × tolerance (default **±2%**) is an **exception requiring human
review**, not a silent accept. Receipts are the input to three-way match (`three_way_match.py`
already exists) and to supplier OTIF (§B.6).

### B.1.5 Returns

Returns are **two independent facts** and must never be one:

```
PHYSICAL RETURN   goods come back    → +on_hand (or +quarantine), +valuation
FINANCIAL REFUND  money goes out     → −revenue, −margin
```
They can occur in either order, with a lag, or one without the other (refund-without-return =
goodwill; return-without-refund = pending inspection).

| Field | Required | Notes |
|---|---|---|
| `return_id`, `order_ref`, `sku`, `qty` | ✅ | |
| `disposition` | ✅ | `restock` \| `quarantine` \| `scrap` \| `return_to_vendor` \| `pending_inspection` |
| `refund_amount`, `currency` | ⚪ | absent ⇒ no financial effect yet |
| `reason_code` | ⚪ | feeds CV return-fraud triage — an existing differentiator |
| `restock_location` | ⚪ | required iff `disposition=restock` |

**Rule:** only `disposition=restock` increases ATP. Everything else increases on_hand-in-quarantine
at most. Margin-after-returns (a Tier-1 CFO metric) requires *both* facts joined — publish
`insufficient` until both arrive rather than an optimistic margin.

### B.1.6 Inventory valuation

| Field | Required |
|---|---|
| `valuation_id`, `sku`, `location_id` | ✅ |
| `qty_delta`, `value_delta_cents`, `currency` | ✅ |
| `costing_method` | ✅ — `standard` \| `avco` \| `fifo` |
| `unit_cost_cents`, `remaining_qty`, `remaining_value_cents` | ⚪ |
| `source_ref`, `as_of` | ✅ |

**Rules:** valuation is an **append-only layer stream**, never a mutable balance — this mirrors
Odoo's `stock.valuation.layer` and is what makes an audit reproducible. **Never mix costing methods
within one SKU × location.** Cross-currency valuation must not be summed without an FX rate carrying
its own `as_of` and source — the same currency-authority rule as B1 in the recommend lane.

### B.1.7 Landed cost

| Field | Required |
|---|---|
| `landed_cost_id`, `applies_to[]` (receipt/valuation refs) | ✅ |
| `cost_type` | ✅ — `freight` \| `duty` \| `insurance` \| `handling` \| `other` |
| `amount_cents`, `currency` | ✅ |
| `allocation_method` | ✅ — `by_value` \| `by_qty` \| `by_weight` \| `by_volume` |

**Rules:**
1. **Landed cost changes value, never quantity.** (Odoo's rule; adopt it verbatim.)
2. **Landed cost is the true margin denominator.** A margin computed on ex-works cost is wrong by the
   freight rate — which for imported goods in ANZ is material. When landed cost is absent, margin
   must be labelled `basis: ex_works`, never presented as final.
3. Allocation must be explicit and reproducible from the recorded inputs.

### Alternatives considered
| Option | Trade-off |
|---|---|
| **A. Read-only canonical feed (recommended)** | ShopSquire never owns stock truth. Safest, matches doctrine, works self-hosted. **Cost:** limited by feed quality. |
| B. Maintain a local shadow ledger | Better ATP when the ERP is slow. **Cost:** you become a system of record — crosses the line. **Reject.** |
| C. Live query-through to the ERP per turn | Freshest. **Cost:** latency + a hard dependency on their uptime for every chat turn. **Use for commitment only, not browse.** |
| D. Hybrid: cached feed for browse, live query at commit | **The right end-state.** Browse is fast and honest; commitment is authoritative. |

---

## B.2 Odoo models vs the ShopSquire feed contract

| Concept | Odoo model | ShopSquire slot | Gap |
|---|---|---|---|
| Physical stock by location | `stock.quant` (`quantity`, `reserved_quantity`) | `location_atp` | ⚠️ **must carry `reserved` separately** — see B.1.2 |
| Free to sell | `product.free_qty` = on_hand − reserved | derived | define, don't re-derive |
| Forecast position | `product.virtual_available` = on_hand − outgoing + incoming | `location_atp.inbound/outbound` | ✅ shape present |
| Stock movement | `stock.move` / `stock.move.line` | `receipt`, `return` | ⚠️ no generic **transfer** slot — needed for multi-location |
| Reservation | `stock.move.line` assigned qty | `reservation` | ⚠️ Odoo has no soft-hold TTL; ShopSquire needs one |
| Goods receipt | `stock.picking` (incoming) done | `receipt` | ✅ |
| Return | reverse `stock.picking` + `account.move` credit note | `return` | ⚠️ **must model physical and financial separately** (B.1.5) |
| Valuation | **`stock.valuation.layer`** | `inventory_valuation` | ✅ good match — adopt the layer-stream semantics |
| Landed cost | `stock.landed.cost` → adjusts SVL value only | `landed_cost` | ✅ adopt Odoo's value-not-quantity rule |
| Purchase order | `purchase.order` / `.line` | `purchase_order` | ✅ |
| Invoice | `account.move` | `invoice` | ✅ |
| Product | `product.template` / `product.product` (variant) | catalog | ⚠️ **template vs variant distinction is not modelled** — wholesale needs it |
| Unit of measure | `uom.uom` + category, with conversion | — | ❌ **MISSING AND IMPORTANT** — see below |
| Contract pricing | `product.pricelist` / `.item` | — | ❌ missing; required for wholesale |

### The three gaps that matter for wholesale

1. **UoM conversion is absent.** Wholesale runs on *"case of 24"* vs *"each"*. Odoo has a full
   UoM-category system with conversion factors. Without it, a quantity is ambiguous and every ATP
   number is potentially wrong by a factor of 24. **This is a correctness blocker for the wholesale
   pivot, in the same class as B1 currency authority.** Add `uom` + `uom_qty` + a conversion table;
   reject any feed row whose UoM is not in the catalog's UoM category.
2. **Template vs variant.** A distributor's "product" is a template with size/colour/pack variants.
   The current catalog is flat.
3. **Pricelist / contract pricing.** Per-account negotiated price is the defining B2B feature.
   `supplier_products.price_breaks` covers volume breaks but not per-account contracts.

**Why Odoo is the right reference:** it is open-source, self-hostable, dominant in exactly the
mid-market wholesale segment the positioning analysis targets, and its physical/financial separation
is the cleanest public model of these semantics. Aligning your canonical names to Odoo's costs
nothing and buys instant legibility with every Odoo integrator — and Odoo's own self-hosted posture
matches yours.

**Alternative:** align to GS1 / EDI (ORDERS, DESADV, INVOIC) instead. *Better for large-supplier EDI
integration, far heavier, and not needed until a customer demands EDI.* **Recommendation: Odoo names
now, GS1 mapping later as a translation layer.**

---

## B.3 Public datasets and licensing

**Purpose matters — pick per use, and never mix a non-commercial dataset into a shipped model.**

| Dataset | Use | Licence status | Verdict |
|---|---|---|---|
| **M5 / Walmart (Kaggle)** | forecasting benchmark; 30,490 series × 1,941 days, item/dept/store/state | **Kaggle competition rules — competition-scoped.** Not a general commercial licence | ✅ **benchmark & publish metrics** · ❌ **do not ship in the product** |
| **Online Retail II (UCI)** | RFM/CLV, basket, returns; UK online retail 2009-2011 | **UCI ML Repository — CC BY 4.0.** Attribution required | ✅ **safe for dev, demo, and shipped fixtures with attribution** |
| **Olist (Brazilian e-commerce)** | orders, reviews, logistics, delivery lead times | **CC BY-NC-SA 4.0** | ⚠️ **NC = non-commercial. Research only. Never ship.** |
| **Instacart Online Grocery** | reorder cadence, basket | Instacart-specific non-commercial terms | ⚠️ research only |
| **Open Food Facts** | product attributes, barcodes | **ODbL** (data) + CC-BY-SA (images) | ⚠️ ODbL is **share-alike on derived databases** — usable but read the obligation carefully |
| **GS1 / GPC** | product classification | free browse, licensing for redistribution | ⚠️ check before embedding |
| **Shopify Standard Product Taxonomy** | taxonomy (already pinned 2026-05) | open | ✅ already in use |
| **openFDA / DailyMed** | pharmacy vertical facts | US Government — public domain | ✅ |
| **TGA (AU)** | ANZ pharmacy | Crown copyright, CC BY 4.0 for most datasets | ✅ verify per dataset |
| **ABS / data.gov.au** | ANZ demographics, seasonality | **CC BY 4.0** | ✅ |

### The rules to encode
1. **Every dataset gets a `datasets/LICENSES.md` row**: name, URL, licence, retrieved date, permitted
   use (`dev` / `benchmark` / `ship`), attribution string.
2. **A CI test asserts no `ship: false` dataset appears under `config/` or `data/`.** This is exactly
   the ratchet pattern already used for `no_flavour_in_core` — it works, reuse it.
3. **Never train on a competition dataset and ship the weights.** Benchmark, publish the number,
   discard the model.
4. **Attribution appears in the product**, not only in the repo — an `/about/data` page.

---

## B.4 Forecasting & replenishment baselines and evaluation windows

### Current state (measured)
`demand_forecast.py`: chain `arima → prophet → ewma`, EWMA α=**0.28**, and `_mape()` — **computed
in-sample on the same series it fitted**. It is exposed honestly as `mape_proxy`, but it is not an
accuracy measurement.

### ⚠️ Two corrections before any baseline
1. **MAPE is the wrong metric for retail.** It divides by actuals, and retail SKUs have zero-sale
   days — MAPE becomes undefined or explodes. **Use WAPE** (Σ|e| / Σ|actual|) as the headline, and
   **MASE** vs seasonal-naive as the scale-free comparator.
2. **In-sample error always flatters.** Replace with **rolling-origin (walk-forward) evaluation.**

### The baseline ladder — you must beat these or admit you don't
| # | Baseline | Definition | Why it's here |
|---|---|---|---|
| B0 | **Naive** | ŷ(t+h) = y(t) | the floor |
| B1 | **Seasonal naive** | ŷ(t+h) = y(t+h−7) | **the real bar.** Weekly seasonality is most of retail signal; models that don't beat this are theatre |
| B2 | **Moving average** (28d) | mean of last 28 | robust, intermittent-tolerant |
| B3 | **Croston / SBA** | intermittent-demand method | **essential for wholesale** — most distributor SKUs sell sporadically |
| B4 | EWMA α=0.28 | current default | must beat B1 to stay |
| B5 | ARIMA / Prophet | current chain | must beat B1 **and** justify its latency |

**Rule: publish every model's WAPE against B1. If B1 wins, ship B1.**

### Evaluation windows
```
Origins        : rolling, weekly, ≥ 12 origins
Horizons       : h ∈ {7, 14, 28, lead_time_days}   ← lead-time horizon is the one that matters
Holdout        : last 28 days never used for tuning (the labels-discipline rule, applied to forecasts)
Warm-up        : SKUs with < 8 weeks history → status "insufficient", never a forecast
Segmentation   : report by ABC (value) × XYZ (variability) — a portfolio number hides the tail
Metrics        : WAPE (headline) · MASE (vs B1) · bias = Σe/Σactual (over/under) · service-level attained
```

### Replenishment baseline
```
ROP        = mean_daily_demand × lead_time_days  +  safety_stock
safety     = z(service_level) × σ_demand_during_lead_time
             σ_LT = √( LT × σ_d²  +  d̄² × σ_LT² )   ← includes LEAD-TIME variance
order_qty  = max(ROP − ATP_projected, MOQ)  rounded up to the next price break
```
Note `σ_LT` — **supplier lead-time variance belongs in safety stock**, and §B.6 already computes it
(`lead_time_stddev_days` exists in `supplier_intelligence.py`). Wiring that in is a genuinely
differentiated, cheap improvement: most mid-market tools assume constant lead time.

**Earned autonomy:** feed measured WAPE into `authorize_replenishment(min_confidence)`. Poor accuracy
⇒ gate stays conservative. Demonstrated accuracy ⇒ wider bounds. Autonomy earned from evidence, never
configured on.

---

## B.5 Account merge/split evidence thresholds

**Current state:** `account_intelligence.resolve_exact_external_identity()` — exact external-ID match
only. No fuzzy matching, no merge, no split. **This is the correct v1** and the spec below should not
be implemented until a real customer needs it.

### The asymmetry that governs everything here
> **A wrong merge is far worse than a missed merge.** A missed merge is two account views. A wrong
> merge leaks one customer's order history, pricing, and credit terms to another — a privacy incident
> and, in wholesale, a competitive-intelligence leak.

**Therefore: merges are proposed, never automatic, unless the evidence is deterministic.**

### Evidence tiers

| Tier | Evidence | Weight | Auto-merge? |
|---|---|---:|---|
| **T1 deterministic** | same `(source, object_type, external_id)`; verified ABN/ACN/company number; verified domain+ABN | **1.00** | ✅ **yes** — this is identity, not inference |
| **T2 strong** | verified email exact match; verified phone (E.164) exact | 0.60 | ❌ propose |
| **T3 moderate** | billing address normalised exact; corporate email domain (non-free) | 0.35 | ❌ propose |
| **T4 weak** | name similarity ≥ 0.92 (Jaro-Winkler); shared contact person | 0.15 | ❌ hint only |
| **Negative** | different ABN; different country; explicit human "not the same" | **−1.00 (veto)** | blocks regardless of score |

### Thresholds
```
score = Σ(tier weights, capped per tier, one contribution per evidence class)

score ≥ 1.00 AND ≥1 T1 present  → AUTO-MERGE      (deterministic only)
0.70 ≤ score < 1.00             → PROPOSE         (human review queue)
0.40 ≤ score < 0.70             → LINK, NOT MERGE (soft "possibly related" edge)
score < 0.40                    → NO ACTION
any negative veto               → BLOCK + record the veto permanently
```

**Free-email guard:** gmail/outlook/yahoo domains contribute **0** at T3. Otherwise every sole trader
using Gmail merges into one mega-account.

### Merge must be reversible
1. **Never destroy the source parties.** Merge creates a `party_link` with both `party_id`s retained.
2. **Record the evidence set that justified it** — the audit invariant: every merge reproducible from
   its recorded evidence.
3. **Split = revoke the link**, restoring both parties intact. If a merge cannot be reversed, it was
   implemented wrong.
4. **A human veto is permanent** and survives re-scoring.

### Split triggers
Conflicting verified ABN · human "not the same" · divergent verified billing entity · a payment
instrument disputed across the linked set.

---

## B.6 Supplier scoring and quote comparison

### Current state
`supplier_intelligence.py` computes `otif_rate`, `lead_time_mean_days`, `lead_time_stddev_days`
(good — variance is already there). `supplier_score_audits` has **859 rows**. **What is missing is a
documented composite and an insufficient-evidence state.**

### Supplier score

```
S = 0.35·OTIF + 0.25·QUALITY + 0.20·RELIABILITY + 0.10·PRICE + 0.10·RESPONSIVENESS
```

| Component | Formula | Source |
|---|---|---|
| OTIF | on-time **and** in-full deliveries ÷ deliveries | receipts vs PO promise |
| QUALITY | 1 − (rejected_qty ÷ received_qty) | receipt `qty_rejected` |
| RELIABILITY | `exp(−σ_LT / LT̄)` — **consistency, not speed** | lead-time stddev |
| PRICE | percentile rank of **landed** unit cost vs peers for the same SKU | §B.1.7 |
| RESPONSIVENESS | median RFQ→quote hours, normalised | outbound queue + inbox |

**Rules:**
1. **Minimum evidence: 5 deliveries in 180 days.** Below that → `status: insufficient_evidence`,
   **score = null**. Never a default 0.5 — a defaulted score silently authorizes.
2. **Recency weighting:** half-life 90 days. A supplier that fixed itself six months ago should not
   be punished forever.
3. **Reliability rewards consistency.** A supplier that always takes 10 days beats one averaging 7
   with σ=6 — because the second one destroys your safety stock. This is a genuinely
   differentiated modelling choice and it falls straight out of data you already collect.
4. **Every score carries `as_of`, `n_observations`, and the component breakdown.** An unexplainable
   score cannot survive a supplier disputing it.

### Quote comparison — the one rule that matters

> **Compare landed, not listed.**

```
comparable_unit_cost = ( quote_unit_price × qty
                       + freight + duty + insurance + handling
                       − volume_break_discount )
                       ÷ qty
                       ↓ converted at a dated, sourced FX rate
```

**Blocking rules:**
1. **No cross-currency comparison without a dated FX rate carrying its own source.** Refuse and say
   why. (This is exactly the `compare_two_models` refusal already in the parity ledger — the same
   rule, generalised.)
2. **No comparison across different UoM** until conversion exists (§B.2 gap 1).
3. **Non-price terms are surfaced, never silently scored in:** payment terms, warranty, MOQ, lead
   time, return policy. Show the trade-off; let the human weigh it.
4. **A cheaper quote from a supplier with `insufficient_evidence` is flagged**, not auto-preferred.
5. Tie-break within 2% → higher supplier score wins; still human-approved.

---

## B.7 Market-finding confidence, freshness, contradiction

`market_facts.py` already has `confidence`, `freshness_policy`, `valid_from/valid_to`, `provenance`,
and `_bounded_confidence()`. The **bitemporal shape is right**. What is missing is a **contradiction
rule** and **trust tiering**.

### Trust tiers
| Tier | Source | Default TTL | Narration |
|---|---|---:|---|
| **T1** | regulator, first-party ERP, publisher spec (Steam), signed EDI | 30d | stated as fact |
| **T2** | curated fixture, pinned taxonomy | 90d | stated as fact, dated |
| **T3** | allowlisted structured source (JSON-LD, public API) | 7d | hedged, attributed |
| **T4** | open web text | 24h | hedged, attributed, **never sole basis for an action** |

### Confidence
```
confidence = tier_prior × freshness_factor × corroboration × extraction_quality
freshness_factor = exp(−age_hours / ttl_hours)
corroboration    = 1.0 (single) · 1.15 (two agreeing, capped 1.0) · 0.5 (contested)
```

### Freshness bands
`fresh` (age < ½ TTL) → usable for action · `aging` (½ → 1 TTL) → usable, flagged ·
`stale` (> TTL) → **narration only, never authorizes an action** · `expired` (> 2 TTL) → excluded.

**Hard rule:** safety-critical or money-moving claims **must** be `fresh` **and** T1/T2.

### Contradiction — the missing piece
Two findings contradict when they assert different values for the same `(entity, attribute)` with
overlapping validity and a difference beyond tolerance (numeric: >5% or outside stated precision;
categorical: any difference).

**Resolution ladder — in order, stop at the first that resolves:**
1. **Tier** — higher tier wins outright. T4 never overrides T1.
2. **Freshness** — same tier → fresher wins.
3. **Conservative** — same tier and freshness → **the stricter value wins** (higher requirement,
   lower availability, higher cost, shorter shelf life). Never average.
4. **Unresolved** → **status `contested`, confidence × 0.5, both values surfaced in the trace, and
   the finding cannot authorize an action.**

**Never average contradicting sources.** The mean of two incompatible facts is a third fact nobody
asserted — and it is unattributable, which breaks the audit invariant.

**Every contradiction is written to the decision trace.** "We saw two answers and here is why we
chose this one" is a trust-building moment, not a failure to hide.

---

## B.8 Data-source terms review before collecting competitor prices

### Current state — better than expected
`connectors/competitor_price_fetch.py` already: honours **robots.txt** (and **skips the domain** on a
robots network error — conservative and correct); **rate-limits** via `min_request_interval_sec`;
sends an **identifying User-Agent**; extracts **JSON-LD structured data** rather than parsing HTML;
records **provenance**; and runs behind an **allowlist**. That is a defensible posture already.

### What the law actually says (2026)
- **hiQ v. LinkedIn** (9th Cir.) and **Meta v. Bright Data** (2024 SJ) both hold that scraping
  **public** data **without bypassing technical access controls** is not a CFAA violation.
- **The login wall is the legal dividing line.** Meta's contract claims failed *because Bright Data
  collected public data without an account.* Create an account and accept ToS, and scraping in breach
  of those terms is a **straightforward contract breach**.
- **Australia:** scraping is not automatically illegal, but the **2026 privacy reforms** impose
  strict consent and data-handling obligations, and copyright plus the Australian Privacy Principles
  still apply.

### The policy to encode
1. **Never authenticate.** No accounts, no cookies, no logged-in sessions. This single rule keeps you
   on the right side of the only line the case law actually draws. **Encode it as a test.**
2. **Never bypass a control** — no CAPTCHA solving, no rotating residential proxies to evade blocks,
   no ignoring 403/429.
3. **Prices and public specs only.** No personal information, ever — that is where the AU privacy
   reforms bite.
4. **Structured data first** (JSON-LD/microdata). It is what the site published for machines, it is
   more stable, and it is a materially better-faith posture than DOM scraping.
5. **Per-domain terms review before enrolment**, recorded as data:
   ```json
   { "domain": "...", "reviewed_at": "...", "reviewed_by": "...",
     "robots_allows": true, "tos_url": "...", "tos_prohibits_scraping": false,
     "requires_account": false, "rate_limit_sec": 30,
     "verdict": "allow|deny", "review_due": "..." }
   ```
   **A domain with no review row is not fetched.** Re-review every 180 days.
6. **`tos_prohibits_scraping: true` ⇒ deny**, even where legally arguable. The commercial downside of
   a cease-and-desist during a pilot vastly exceeds the value of one competitor's prices.
7. **Prefer licensed feeds and official APIs** where they exist. In ANZ, retailer affiliate feeds and
   price-comparison APIs cover much of this legitimately.
8. **A competitor price is T3** (§B.7) — hedged, attributed, and **never the sole basis for an
   automated price change.**

**Alternative worth serious consideration:** don't collect competitor prices at all in v1. For a
*wholesale* customer, the valuable comparison is **supplier quotes** (which they receive directly and
own outright) — not retail competitor prices. **Recommendation: defer external price collection; it
carries legal surface for a benefit the wholesale wedge doesn't need.**

---

## B.9 Simulated tests: generic protocol behaviour vs provider-specific certification

### The distinction

> **Protocol tests** prove *ShopSquire behaves correctly given a contract*. They may be fully
> simulated, must run in CI offline, and are the safety net.
>
> **Certification tests** prove *a specific provider actually honours that contract*. They require
> the real provider (or its sandbox), cannot run in normal CI, and are **per-provider, per-version,
> and expire.**

The failure this prevents is the expensive one: **a green simulated suite reading as production
readiness.** Your own history has this exact pattern — `sandbox_supplier.py` is explicitly
*"production-shaped, never real"*, and `FULFILLMENT_SUPPLIER_TRANSPORT` defaults to `sandbox`.

### Classification

| Tier | Marker | Runs in CI | What it proves | Examples in this repo |
|---|---|---|---|---|
| **P — Protocol** | `@pytest.mark.protocol` | ✅ always | our logic given a contract | connector returns `Evidence\|None` and never raises; retry/backoff; idempotency on replay; ATP `unknown` when `reserved` absent; landed cost changes value not qty; merge veto blocks; T4 never overrides T1 |
| **C — Certification** | `@pytest.mark.certification(provider=…)` | ❌ gated | **that provider** honours it | NetSuite REST auth + pagination + real field names; Xero OAuth refresh; Odoo XML-RPC/JSON-RPC shapes; SMTP delivery to a real MX; Stripe webhook redelivery |
| **S — Sandbox/demo** | `@pytest.mark.sandbox` | ✅ | the demo path works | `sandbox_supplier`, seeded catalog flows |
| **L — Live characterization** | `@pytest.mark.live` | ❌ opt-in | real model/provider behaviour today | live replay, vision battery |

### The rules
1. **Every connector needs both.** A provider with protocol tests but no certification run is
   **`status: uncertified`** and must be labelled as such in the admin UI. This is the honesty
   doctrine applied to integrations.
2. **Certification results are dated artifacts, not code.**
   ```json
   { "provider": "netsuite", "api_version": "2024.2", "certified_at": "...",
     "certified_by": "...", "suite_sha": "...", "result": "pass",
     "expires_at": "...", "notes": "..." }
   ```
3. **Certification expires — default 180 days**, or immediately when the provider's API version
   changes. An expired certification reverts the connector to `uncertified`.
4. **A simulated test may never assert a provider-specific fact.** If a test hard-codes NetSuite's
   field names against a mock, it is a certification test wearing a protocol test's clothes — and it
   will pass forever while production is broken. **Add a CI ratchet for this**, in the same style as
   `test_no_flavour_in_core`.
5. **The demo must state its transport.** `FULFILLMENT_SUPPLIER_TRANSPORT=sandbox` should be visible
   in the UI, not just the env. "Sandbox supplier — no real message sent" on screen. You already tag
   this in the service; surface it.
6. **Never claim certification from a mock.** The `external_stock` precedent is the right instinct:
   absent data is labelled absent. Same for uncertified providers.

---

## C. Recommended sequence

**Blockers first — unchanged, and two are now overdue:**
`B0.5 silent-swallow + decision-log flag` · **`B1 currency authority`** · **`B3 seal the labels`** ·
**land the 6,100-line batch in slices with rehearsed migration down-paths.**

Then:

| # | Item | Why now | Effort |
|---|---|---|---|
| 1 | **UoM model + conversion** (§B.2 gap 1) | correctness blocker for wholesale, same class as B1 | **M** |
| 2 | **ATP semantics + `unknown` rule** (§B.1.2) | the feed slot exists and is currently semantics-free — every downstream number depends on it | **M** |
| 3 | **WHY-NOT panel** | still the highest value-per-line UI item; still not started; frontend moved 7 lines today | **S** |
| 4 | **Seasonal-naive baseline + WAPE + rolling origin** (§B.4) | replaces an in-sample `mape_proxy` that cannot be trusted | **S** |
| 5 | **Supplier composite + landed-cost quote compare** (§B.6) | data already collected; σ_LT → safety stock is a real differentiator | **M** |
| 6 | **Contradiction rule + trust tiers** (§B.7) | bitemporal shape already exists; this completes it | **M** |
| 7 | **`datasets/LICENSES.md` + CI ratchet** (§B.3) | cheap, and prevents an unshippable dependency | **S** |
| 8 | **Protocol/certification test markers + registry** (§B.9) | prevents "green suite = ready" | **S** |
| 9 | Account merge/split (§B.5) | **defer** — exact-match-only is correct until a customer needs more | — |
| 10 | Competitor price collection (§B.8) | **defer** — legal surface without wholesale benefit | — |

---

## Sources

- [Automatic inventory valuation — Odoo 18.0 documentation](https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/product_management/inventory_valuation/inventory_valuation_config.html)
- [Stock valuation dashboard — Odoo 18.0](https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/warehouses_storage/reporting/aging.html)
- [Odoo Inventory Analytics: Stock Quants, Moves — Spark by MishiPay](https://spark.mishipay.com/blog/odoo-inventory-analytics)
- [OCA/stock-logistics-warehouse](https://github.com/oca/stock-logistics-warehouse)
- [M5 Forecasting - Accuracy | Kaggle](https://www.kaggle.com/competitions/m5-forecasting-accuracy)
- [Online Retail — UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/352/online+retail)
- [Best Retail Datasets for Machine Learning 2026 — Unidata](https://unidata.pro/blog/best-retail-datasets-for-ml/)
- [Major Decision Affects Law of Scraping: Meta v. Bright Data — Farella Braun + Martel](https://www.fbm.com/publications/major-decision-affects-law-of-scraping-and-online-data-collection-meta-platforms-v-bright-data/)
- [What Recent Rulings in 'hiQ v. LinkedIn' Say About Data Scraping — FBM](https://www.fbm.com/publications/what-recent-rulings-in-hiq-v-linkedin-and-other-cases-say-about-the-legality-of-data-scraping/)
- [Taking a Swipe at Scraping: hiQ v. LinkedIn and Meta v. BrandTotal — Meitar](https://meitar.com/en/media/taking-a-swipe-at-scraping-practical-takeaways-from-hiq-v-linkedin-and-meta-v-brandtotal/)
- [Web Scraping Laws in Australia: Legal Risks and Compliance — Sprintlaw](https://sprintlaw.com.au/articles/web-scraping-laws-in-australia-legal-risks-and-compliance/)
- [Is Web Scraping Legal in 2026? — Browserless](https://www.browserless.io/blog/is-web-scraping-legal)

*Assessment + specification only. No code changed.*
