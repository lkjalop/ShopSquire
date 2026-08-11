# ShopSquire Demo Build — Execution Handoff (2026-07-24)

Handoff for the next executor. Goal: a **full end-to-end, pilot-grade demo** (voice → recommend →
procurement → live market intelligence → human approval) showcasing **agentic bounded autonomy,
segregation of duties, and real operator intelligence**. Voice paused (blocked on credential);
concurrency load-test held (needs real infra).

Positioning (why this wins): the hyperscalers (ChatGPT Instant Checkout, Gemini AI Mode, Amazon Rufus,
Salesforce Agentforce Commerce) all race on **buyer-side discovery→checkout**. Nobody exposes an
**openable, real-time, per-decision governance + margin/procurement trace**. That trace is the product.

---

## 0. STATUS — done vs left

| Phase | Item | Status | Commit |
|---|---|---|---|
| 0a | feature_flags.json regression restored (20 keys incl. `FULFILLMENT_AUTONOMOUS_*`) | ✅ done | working-tree restore |
| 0b | Tier 0 verify + seed `sales_metrics` (4,883 rows / 125 SKUs) | ✅ done | `2432c3a` |
| 1a | `slot_gap_clarify` empty-inversion fix + 3 tests | ✅ done | `b3a9473` |
| 1b | `turn_router` clamp `general_policy` hole | ✅ done (concurrent agent — fix + parametrized test) | — |
| 2a | Live Procurement economics strip | ⬜ **next** | — |
| 2b | Combined-availability two-option (procurement + cart) | ⬜ | — |
| 3a | `market_projection` event + Market Intelligence tab | ⬜ | — |
| 3b | Velocity/DSI + bulk-order-frequency detectors | ⬜ | — |
| 4a | Surplus → variable discount (human-gated) | ⬜ | — |
| 4b | Governed replenishment surfacing | ⬜ | — |
| 4c | Marketing/newsletter draft (human-gated) | ⬜ | — |

**Data findings that constrain the demo:**
- `external_stock` **MISSING** → **no supplier ATP feed**. Supplier stock is **RFQ-based** ("5 sourced via supplier RFQ, lead 7d"), NOT a confirmed live number. Do not claim otherwise on camera.
- `supplier_score_audits` 821 rows ✅ · `inventory_level` 503 rows ✅ (multi-location + transfer works) · `fulfillment_cases` MISSING (bulk-frequency starts at 0, fills as RFQs are drafted — transaction-reactive).

---

## 1. Environment / runbook

- **Stack:** shopper `:5173`, admin `:3001`, API `:8080`, Ollama `:11434`.
- **DB:** SQLite `tmp/demo.sqlite` (2.6 GB). ⚠️ `bi_intelligence.py` uses SQLite `datetime('now', …)` — **Postgres-incompatible**; note before any prod claim.
- **Seed BI data:** `python scripts/seed_demo_sales_metrics.py` (idempotent; re-run any time).
- **Pre-warm before recording** (cold start ~90s; `VOICE_COLD_CEILING_SECONDS` is a **dead env var** — wire it or add a pre-warm step to the runbook).
- **Two agents on one tree:** split by lane to avoid collisions (see §7).

---

## 2. Component role model (the SoD story the whole demo sells)

Every trace source is classified in [DecisionTrace.tsx:206-228](../frontend/src/components/DecisionTrace.tsx#L206) as one of:

```
  model      ▸ proposes      (qwen / llm)         — maps language → bounded schema
  gate       ▸ authorizes    (policy / guard)     — clamps, approves, send-gate
  connector  ▸ executes       (api / email / edi)  — the only thing that acts outward
  observer   ▸ observes       (trace / market intel / feedback)
```
**Design invariant for every new agent/tool below:** declare its role and its read/write scope. Model
proposes; gate authorizes; connector executes; consequential sends stay **human-gated**.

---

## 3. Wireframes

### 3.1 Procurement tab (Phase 2a + 2b)
```
┌─ Decision Trace · Procurement ─────────────────────── [● live] ─┐
│ RFQ — LAP-69763798 ×5     human-gated · not sent · GATE 2       │
│ Supplier SUP-CREATOR (creatorfleet.example) · channel: api      │
│ Terms  MOQ 10 · 7d lead · breaks 25→5% · 50→11%                 │
│─ CAN'T FULFIL 20 AS-IS ─────────────────────────────────────────│
│  OPTION A — Fill now (human-gated)                              │
│   • 10 in stock (this location)                                 │
│   • 5 transfer from Warehouse-2 → arrives 2d                    │
│   • 5 sourced via supplier RFQ (draft only, 7d)                 │
│   [ Approve plan ]   nothing sent until you approve             │
│  OPTION B — Ship from stock now                                 │
│   • 15 of this unit, or an in-stock alternative (ships today)   │
│   [ Show alternatives ]                                         │
│─ LIVE DEAL ECONOMICS  (operator-only, role-gated) ─────────────│
│  Verdict ● HEALTHY   margin 22.4% (floor 10%)                  │
│  List $1,919 → Wholesale $1,490 → Gross $429/u                 │
│  Bulk @25u −5% → wholesale $1,415 → margin 26.2%               │
│  Projected profit (5u): $2,145   Max buyer discount: $312      │
│─ SEGREGATION OF DUTIES ─────────────────────────────────────────│
│  Model ▸ proposes   Policy ▸ authorizes   Connector ▸ executes  │
│  Send gate: needs_info · HUMAN ONLY · hash d3596…              │
└──────────────────────────────────────────────────────────────── ┘
```

### 3.2 Market Intelligence tab (Phase 3a + 3b) — NEW
```
┌─ Decision Trace · Market Intelligence ───────────────  [● live] ─┐
│ Scope:  ( ) This query   (●) LAP-69763798    as_of 09:41         │
│─────────────────────────────────────────────────────────────────│
│ Product        Trend  Velocity  Margin  Proj30d  Stock    Conf   │
│ LAP-69763798 ▸ ↑+18%  12d DSI   22.4%   $6.4k   balanced  0.71   │
│ LAP-858DC749   → flat  34d DSI   17.1%   $1.9k   surplus   0.63   │
│ LAP-647D08E6   ↓ −7%   61d DSI   14.8%   $0.4k   surplus   0.48   │
│─────────────────────────────────────────────────────────────────│
│ INSIGHT  LAP-69763798 turns 3× faster than demand-matched peers  │
│   → velocity outpaces forecast ⇒ reorder candidate (feeds RFQ)   │
│ Bulk-order frequency  4 RFQs / 30d  (Gaming Laptops)            │
│ ⚠ estimate · confidence-scored · not a guarantee · as_of stamped │
└──────────────────────────────────────────────────────────────────┘
```

### 3.3 Governed action cards (Phase 4) — all human-gated
```
┌─ SURPLUS · LAP-858DC749 (velocity 34d, stock 40) ──────────────┐   ┌─ SHORTAGE · LAP-69763798 (demand ↑, ATP −5) ───────────────┐
│ ① Variable discount — margin allows up to 12% while clearing   │   │ Governed replenishment PROPOSED                            │
│    floor. Recommended 8%.        [ Approve discount ]          │   │  evidence: demand ↑ (3 sources, conf 0.81) · ATP deficit 5 │
│ ② Feature in newsletter (JB-HiFi-style catalogue)             │   │  · lead 7d · economics HEALTHY                             │
│    draft blurb + deal ready.     [ Review draft ]  never auto-sent │  [ Approve reorder ]   supplier send is HUMAN-ONLY (GATE 2)│
└────────────────────────────────────────────────────────────────┘   └────────────────────────────────────────────────────────────┘
```

### 3.4 Admin BI panels (surface the dark endpoints) — MerchantBIPro tab
```
┌─ Admin · Merchant BI ─────────────────────────────────────────┐
│ [Transactions] [Executive Pulse] [Margin ◀NEW] [Suppliers ◀NEW]│
│─ Margin Intelligence (window 90d) ────────────────────────────│
│  SKU            Revenue   Wholesale  Margin%  Units            │
│  LAP-AF295B6E   $1.43M    $1.12M      22.0%    299             │
│  LAP-4743EFFF   $0.57M    $0.41M      28.0%    317             │
│─ Supplier Scorecard (window 60d) ─────────────────────────────│
│  Supplier   Lead  On-time  Defect  Score                      │
│  SUP-7       7d    96%      1.2%    0.91                       │
│  (821 audit rows — real data)                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. Per-item specs (file:line · contract · TDD · commit)

### Phase 2a — Live Procurement economics strip
- **Backend:** `margin_advisor.assess(case_id)` ([margin_advisor.py:35](../src/app/services/fulfillment/margin_advisor.py#L35)) already returns `{verdict, economics, max_buyer_discount_cents, recommended_buyer_discount_cents, supplier_last_invoice_cents, rationale}`. Ensure the operator case-detail endpoint the trace fetches ([fulfillment_cases.py]) includes it. Add bulk-break rows from `supplier_products.price_breaks`.
- **Frontend:** [DecisionTrace.tsx:555 `loadProcurementDetail`](../frontend/src/components/DecisionTrace.tsx#L555) already fetches operator case detail + re-runs on `procurementRevision` ([:608](../frontend/src/components/DecisionTrace.tsx#L608)). Render the economics strip near the Procurement render site ([:1587](../frontend/src/components/DecisionTrace.tsx#L1587)).
- **Contract:** `{verdict, margin_pct, list_cents, wholesale_cents, gross_per_unit_cents, bulk_breaks:[{min_qty,discount_pct,margin_pct}], projected_profit_cents, max_discount_cents, discount_authorized}`
- **TDD:** backend — `assess()` returns HEALTHY/thin/below_floor for known inputs (test exists: `test_margin_advisor.py`); frontend — strip renders + refreshes on revision.
- **Commit:** `feat(trace): live deal economics in procurement tab`

### Phase 2b — Combined-availability two-option (procurement + cart)
- **Backend:** `multi_location_availability.network_availability(...)` ([multi_location_availability.py:46](../src/app/services/multi_location_availability.py#L46)) already returns `{total_in_network, by_location, transfer_plan, shortfall, fillable_from_network}`. Wire it into the availability block of [recommend_fulfillment_stage.py](../src/app/services/recommend_fulfillment_stage.py) so the response carries it; add a cart-line availability check (same call, cart qty as `requested_qty`).
- **Frontend:** two-option card in the Procurement tab **and inline in the cart** (`frontend/src/` cart component) when a line qty > stock. Option B alternatives = the recommendation core's nearest-fit.
- **Contract:** `{requested, total_in_network, by_location:{loc:qty}, transfer_plan:[{from_location,qty}], shortfall, fillable_from_network, alternatives:[sku]}`
- **Data:** `inventory_level` (503 rows ✅). Supplier shortfall = **RFQ** (no ATP feed).
- **TDD:** `network_availability` transfer-plan + shortfall math; cart-line trigger fires only when qty>stock.
- **Commit:** `feat(fulfillment): combined-availability two-option (network transfer + supplier shortfall)`

### Phase 3a — `market_projection` event + Market Intelligence tab
- **Backend (event, non-sensitive skeleton):** emit one `market_projection` trace event per shown SKU via `log_trace_event` ([decision_log.py]) from a projection stage (sibling to [recommend_intelligence_stage.py:154](../src/app/services/recommend_intelligence_stage.py#L154) which already emits `market_intelligence`). Rides the existing SSE stream ([decisions.py:867](../src/app/routers/decisions.py#L867)).
  - payload: `{sku, demand_trend, forecast_units_30d, velocity_dsi_days, stock_position, confidence, as_of}`
- **Backend (operator economics, role-gated — DO NOT stream):** new `GET /api/v1/admin/bi/product-projection?sku=…` (roles MERCHANT/OWNER/DEVELOPER). Assemble from `products.price_cents` + `supplier_catalog.cheapest_wholesale_cents` ([:586](../src/app/services/supplier_catalog.py#L586)) + forecast.
  - payload: `{sku, list_cents, wholesale_cents, gross_margin_pct, projected_profit_30d_cents, discount_headroom_cents}`
- **Frontend:** new Market Intelligence tab in DecisionTrace: consume `market_projection` events from the stream (skeleton) + fetch `/product-projection` for the operator columns (merge like the Procurement tab merges buyer payload + operator detail). Scope toggle (query = all shown SKUs; product = clicked SKU). Add `api.ts` client fns (model on [fetchExecutivePulse (api.ts:150)](../src/frontend/admin-react/src/api.ts#L150)).
- **TDD:** event carries the skeleton keys for a seeded SKU; `/product-projection` **403s a buyer role** (operator-only guarantee); margin math correct.
- **Commit boundaries:** (1) `feat(trace): emit market_projection events` (2) `feat(admin-bi): product-projection endpoint` (3) `feat(trace): market intelligence tab`.

### Phase 3b — Velocity/DSI + bulk-order-frequency detectors
- **Backend:** new detectors in [market_analysis.py](../src/app/services/market_analysis.py) (established deterministic-detector home; keep vertical-blind — counts only).
  - `velocity`: `units_sold_window / avg_stock_on_hand`; `DSI = stock_on_hand / (units_sold/day)`; `dead_stock=True` when velocity≈0 with stock>0.
  - `bulk_order_frequency`: `COUNT(fulfillment_cases) per sku/category / window`.
- **Data:** `sales_metrics` (seeded ✅) + `inventory`/`inventory_level` (✅); `fulfillment_cases` (empty until RFQs — 0 is honest).
- **TDD:** 100 sold/10 on-hand → high turnover, low DSI; 0 sold/50 → `dead_stock`; zero-stock no div-by-zero; no product vocabulary.
- **Commit:** `feat(market): velocity/DSI + bulk-order-frequency detectors`

### Phase 4a — Surplus → variable discount (human-gated)
- **Backend:** surplus = `_inventory_position=='surplus'` ([recommend_intelligence_stage.py]) + low velocity (3b). Discount headroom from `economics.compute`/`margin_advisor` (max discount clearing floor). Propose only; never applies.
- **Frontend:** action card (§3.3 left). `[Approve discount]` required.
- **Contract:** `{sku, surplus:true, velocity_dsi_days, max_discount_pct, recommended_discount_pct, margin_after_pct}`
- **TDD:** proposes discount ≤ headroom; never auto-applies; below-floor SKU offers 0.
- **Commit:** `feat(actions): human-gated surplus discount`

### Phase 4b — Governed replenishment surfacing
- **Backend:** `market_action_policy.authorize_replenishment(...)` ([market_action_policy.py:29](../src/app/services/market_action_policy.py#L29)) already gates on fresh demand + ATP deficit + lead-time + economics + source-diversity≥2. Surface its verdict; `reorder_supplier_flow` drafts; **human approves send** (same invariant as RFQ).
- **Frontend:** replenishment proposal card (§3.3 right).
- **Contract:** `{authorized, reasons[], shortfall, lead_time_days, economics_verdict, send_gate:"human"}`
- **TDD:** authorizes only with evidence; weak/stale signal DENIES; send stays human.
- **Commit:** `feat(actions): surface governed replenishment proposal`

### Phase 4c — Marketing/newsletter draft (human-gated) — thinnest build
- **Backend:** NEW draft generator (model drafts blurb + which surplus/featured SKUs to include + deals). `campaign_correlator.py` exists for correlation; the **draft-gen is new**. **Never auto-sends** (same send-invariant).
- **Frontend:** newsletter draft card (JB-Hi-Fi catalogue style: featured products + blurbs + deals) with `[Review draft]` → human edits/approves before any send.
- **Contract:** `{draft_id, featured_skus[], blurbs:{sku:text}, deals:[], status:"draft", send_gate:"human"}`
- **TDD:** draft never marks itself sent; featured set drawn from surplus/velocity, not random.
- **Commit:** `feat(marketing): human-gated newsletter/catalogue draft`

---

## 5. Data-source truth table (real / seed / build)

| Metric / capability | Source | Status |
|---|---|---|
| Profit margin (list→wholesale) | `economics.py` + `cheapest_wholesale_cents` | ✅ real (seeded) |
| Wholesale @ bulk (volume breaks) | `supplier_products.price_breaks` | ✅ real |
| Projected 30-day profit | margin × forecast | ⚠️ assemble |
| Shelf/stock position | `_inventory_position` | ✅ real |
| Demand trend / forecast (EWMA) | `market_analysis` | ✅ real (needs seeded signals) |
| Velocity / DSI | **new detector** | ❌ build (3b) |
| Bulk-order frequency | count `fulfillment_cases` | ❌ build; 0 until RFQs drafted |
| Combined network availability + transfer | `multi_location_availability` | ✅ real |
| Supplier availability | — (`external_stock` missing) | ⚠️ **RFQ-based, not a live feed** |
| Governed replenishment | `market_action_policy` | ✅ real |
| Marketing/newsletter draft | `campaign_correlator` + new gen | ⚠️ thinnest |
| Supplier scorecard | `supplier_score_audits` (821) | ✅ real |
| Margin intelligence (catalog) | `bi_intelligence.margin_intelligence` | ✅ real (SQLite-only SQL) |

**Fluctuation model (per the "changes as user interacts" requirement):**
- **Query-reactive** (recompute every chat turn): margin, projected profit, demand trend, which products.
- **Transaction-reactive** (move as orders/RFQs land): velocity/DSI, bulk-order frequency. Stamp `as_of` + `confidence`; don't fake per-keystroke movement on a slow aggregate.

---

## 6. Parked / blocked (not in this build)

- **Voice real-mic** — blocked on `OPENAI_API_KEY`/`ELEVENLABS_API_KEY` in `.env`. Un-snoozed by the full-end-to-end choice; pipeline ([voice_asr.py], [voice_tts.py], [useDualSTT.ts]) is built + tested with mocks. Also wire `VOICE_COLD_CEILING_SECONDS` (dead env var) or add pre-warm to runbook.
- **Concurrency load test** — held; needs real infra (read replicas, CDN, k8s, autoscaling).
- **`recommend.py` archive** — 7 coupled endpoints remain (`checkout_upsell` 11879, `why_product` 12083, `interaction` 12162, `feedback` 12245, `nqe_slots` 12350, `nqe_feedback` 12411, `admin/nqe_feedback_summary` 12506); + human label seal (`relevance_labels.json` — `human_reviewed_by:null`); gated on real traffic. No demo value.

---

## 7. Two-agent coordination (avoid collisions)

Both agents touch the same core files. Suggested split:
- **Agent A (routing/core internals):** `turn_router.py`, `core.py`, `recommend_fulfillment_stage.py`, `market_analysis.py` detectors, `recommend_intelligence_stage.py`. (Already mid-flight here — it did 1b + a `material_pre_retrieval_clarify`.)
- **Agent B (frontend + net-new modules + endpoints):** `DecisionTrace.tsx`, `MerchantBIPro.tsx`, `api.ts`, the `/product-projection` endpoint, action cards, the seed.
- Commit in one-concern slices; rebase/pull between agents; never two hands on one file.

---

## 8. Recommended execution order (dependencies)

1. **2a** economics strip (fastest visible win; backend already exists).
2. **2b** combined-availability (the "honest can't-fulfil → governed options" beat; central ask).
3. **3b** velocity/DSI detectors (unblocks 3a columns + 4a surplus).
4. **3a** market_projection event + tab (keystone; needs 3b).
5. **4a → 4b → 4c** governed actions (the bounded-autonomy showcase).
6. Admin BI panels (§3.4) — parallel, pure frontend wiring, any time after seed.

Each ships behind the existing off→shadow→canary posture where applicable; commit on green with its test.
