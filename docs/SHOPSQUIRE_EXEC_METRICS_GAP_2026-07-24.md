# ShopSquire — Executive Metrics Gap Analysis & Phase 5-7 Roadmap (2026-07-24)

Continues `SHOPSQUIRE_DEMO_BUILD_HANDOFF_2026-07-24.md` (Phases 0-4 ✅ complete through `9c4b21d`).
Question answered here: **what business-intelligence metrics do real executives run commerce on,
which does ShopSquire have, which are missing, why close the gap, and in what order?**

---

## 1. WHY — the comprehensive reason (read this first)

1. **Executives evaluate software through the metrics they already run their business on.**
   A CFO doesn't ask "is the AI smart?" — they ask "what's my GMROI, and will this protect it?"
   If the platform speaks GMROI / OTIF / forecast-accuracy natively, it reads as *built by people
   who understand retail*. If it doesn't, no amount of AI polish lands. These metrics are the
   demo's credibility currency.
2. **The gates are starving for exactly this evidence.** gpt5.6's live proof showed
   `authorize_replenishment` correctly BLOCKING (insufficient ATP/demand/cost evidence) and the
   discount gate BLOCKING (no validated landed cost). The governance works; what's missing is the
   **business-grade evidence that lets it authorize**. The exec metrics below ARE that evidence.
   Closing the gap converts "the platform refuses" into "the platform refuses *until the numbers
   justify it* — then acts, bounded, with audit."
3. **It completes the positioning.** Hyperscalers (ChatGPT checkout, Rufus, Agentforce) own
   buyer-side conversion. ERPs (SAP IBP, NetSuite, Blue Yonder) own planning — batch, form-based,
   no per-decision audit, no conversational surface. ShopSquire's defensible square is the
   **governed intelligence layer between the commerce stack and the ERP**: reads canonical facts,
   proposes evidence-backed actions, humans authorize, everything traced. The metric pack makes
   that sentence concrete instead of aspirational.
4. **Graduated autonomy needs a measured yardstick.** `authorize_replenishment` already takes
   `min_confidence` ([market_action_policy.py:29-32](../src/app/services/market_action_policy.py#L29)).
   Today nothing *measures* how good the platform's forecasts actually are. Persist forecasts →
   compare to actuals → MAPE/bias per SKU → **feed measured accuracy into the gate's confidence**.
   That is "the agent earns wider autonomy by demonstrated accuracy" — a genuinely differentiated,
   defensible mechanism no competitor demos, and it drops into an existing parameter.

---

## 2. What executives actually watch — persona × metric × ShopSquire status

### CFO
| Metric | What it is | Status | Anchor |
|---|---|---|---|
| **GMROI** | gross margin $ ÷ avg inventory cost $ — THE retail capital-efficiency metric | ❌ **computable NOW** (margin ✅ + inventory ✅) | extend [market_projection.py:154](../src/app/services/market_projection.py#L154) / [bi_intelligence.py:19](../src/app/services/bi_intelligence.py#L19) |
| Contribution margin after returns | margin net of return/refund cost | ⚠️ margin ✅, returns flows exist, not joined | [economics.py:37](../src/app/services/fulfillment/economics.py#L37) + returns/orders |
| Cash conversion cycle (DIO/DPO/DSO) | days inventory + receivables − payables | ⚠️ DIO≈DSI ✅; DPO needs payables (payment spine exists: `payment_ledger.py`) | Phase 7 |
| Markdown % / discount leakage | how much margin is given away | ⚠️ discount proposals now audited (`a246dee`) → aggregating them = the metric | [commercial_action_proposals.py:81](../src/app/services/commercial_action_proposals.py#L81) |
| PPV (purchase price variance) | quoted vs invoiced vs list cost | ⚠️ foundation exists: `supplier_last_invoice_cents` | [margin_advisor.py:79](../src/app/services/fulfillment/margin_advisor.py#L79) |
| Working capital in dead stock | $ tied in `dead_stock=True` SKUs | ❌ trivial join of 3b detector × wholesale cost | [market_analysis.py:515](../src/app/services/market_analysis.py#L515) |

### COO / Logistics
| Metric | Status | Anchor |
|---|---|---|
| **OTIF / fill rate / perfect order** | ⚠️ derivable: `orders.tracking_number/carrier` exist; fulfillment cases carry promise vs actual | orders schema + [fulfillment repository] |
| Lead-time variance by supplier | ⚠️ scorecard has lead AVG ([bi_intelligence.py:63](../src/app/services/bi_intelligence.py#L63)); variance not computed | extend scorecard |
| **ROP / safety stock** (reorder point = demand×lead + z·σ) | ❌ inputs all present (velocity ✅ lead ✅) — makes replenishment *quantity* defensible ("reorder 25" not "reorder some") | feed [market_action_policy.py:29](../src/app/services/market_action_policy.py#L29) proposals |
| Backorder rate | ⚠️ shortfall events exist (`a2e74ce`) → aggregate | [multi_location_availability.py:46](../src/app/services/multi_location_availability.py#L46) |
| Cost-to-serve / freight % | ❌ needs carrier cost data — honest external gap | landed-cost fields are the entry point |

### CMO
| Metric | Status | Anchor |
|---|---|---|
| CLV / churn | ✅ **built, dark** — endpoints exist, no UI | [admin_bi.py:458,470](../src/app/routers/admin_bi.py#L458) |
| Campaign → margin attribution | ⚠️ attribution loop (M6) + `campaign_correlator.py` exist; not joined to margin | attribution + economics |
| Sell-through % / full-price sell-through | ❌ trivial from velocity + discount audit — **the luxury metric** (LVMH runs on full-price ST) | 3b detectors + 4a audit |
| CAC / ROAS | ❌ needs ad-platform connectors — honest external gap | Phase 7 connector |

### CEO / Merchandising
| Metric | Status |
|---|---|
| Inventory turns (annualized velocity) | ⚠️ = 365/DSI — one line on existing detector |
| **Weeks of supply (WOS)** | ❌ = stock ÷ units-per-week — one line on existing detector |
| ABC/XYZ classification (value × variability) | ❌ cheap batch; standard in every ERP |
| **Forecast accuracy (MAPE/bias)** | ❌ **the credibility metric** — we forecast (EWMA) but never score ourselves. SAP IBP/NetSuite always report it. See §1.4 |
| Demand anomaly / seasonality | ✅ real ([market_analysis.py](../src/app/services/market_analysis.py) detectors) |
| Executive pulse | ✅ built + in UI ([admin_bi.py:498](../src/app/routers/admin_bi.py#L498)) |

---

## 3. Scale tiers — what changes from corner store to Walmart

| Tier | What they need | ShopSquire fit | Gap |
|---|---|---|---|
| **Small store** (no ERP) | zero-config cash answers: what to reorder, what to discount, don't stock out, don't drown in dead stock | ShopSquire IS their ops brain — GMROI-lite, WOS, reorder alerts from existing detectors | metrics must render with no setup (seeded → real facts path already built by gpt5.6) |
| **Mid-market** (Macy's-tier) | OTIF, multi-location allocation, supplier scorecards, forecast accuracy, ABC | transfer-plan ✅, scorecard ✅, alloc ✅ — add MAPE + ABC + OTIF | Phase 5-6 |
| **Giants** (Walmart/Costco/Woolworths) | already own SAP/Blue Yonder — will NOT replace planning | positioning = **conversational governed-action layer + per-decision audit** (EU AI Act / NIST AI RMF demand decision-level audit — we have it natively) reading THEIR facts via connectors | read-only fact importers (Phase 7b); push metric compute down to their warehouse at that scale (§5.2) |
| **Grocery** (Woolworths) | perishables: expiry/FEFO, freshness | ❌ no shelf-life attribute — honest gap; the vertical-blind attribute registry can carry `expiry_days` without core changes | note only; not demo-relevant |
| **Luxury** (LVMH) | **full-price sell-through, scarcity, NEVER auto-discount**, brand-safe narration | the SAME gate infra with a different policy: discount gate hard-off per tenant | Phase 7a policy packs |

**Key insight:** the tiers don't need different *engines* — they need different **policy packs** on the
same bounded-autonomy gates. Luxury = discount-gate off + full-price ST emphasized; club/bulk =
bulk-economics emphasized; grocery = FEFO note. Policy as tenant config, not code — the
vertical-blind doctrine already supports exactly this.

---

## 4. Competitive / ERP delta (who has what)

- **SAP IBP / NetSuite / Blue Yonder:** own ROP/EOQ/MAPE/ATP planning — batch, form-based,
  no conversational surface, no per-decision bitemporal audit, no human-gated agentic actions.
- **Salesforce Agentforce Commerce:** conversational + merchant agent, but conversion-centric;
  no open decision trace, no procurement/RFQ governance, no margin-gated action authorization.
- **ChatGPT/Gemini/Rufus/Perplexity:** buyer-side only.
- **ShopSquire delta = the intersection nobody holds:** ERP-grade metrics *feeding* bounded-autonomy
  gates *surfaced* conversationally *with* per-decision audit. Each column exists somewhere;
  the intersection doesn't.

---

## 5. Architectural trade-offs (name them before building)

1. **System-of-intelligence, never system-of-record.** ShopSquire reads canonical facts
   (`marketing_event_fact` contract gpt5.6 established; ERP adapters [erp/sync.py], shopify/magento
   adapters exist) and writes only **drafts + audit**. Never own the financial ledger — that's how
   you sell *alongside* SAP instead of losing to it. All Phase 5-7 metrics obey this.
2. **Metric compute location:** portable Python detectors (current choice — right for tenant
   isolation + SQLite/Postgres portability) caps out at mid-market data volumes. At giant scale,
   push down to the tenant's warehouse/OLAP. The canonical-fact contract makes that swap possible
   without touching the gates. Accept the cap now; note the seam.
3. **Freshness tiers (extend the existing model):** query-reactive (margin, trend) ·
   transaction-reactive (velocity, bulk-frequency) · **NEW planning-cycle batch** (MAPE, ABC/XYZ,
   GMROI trend — daily/weekly). Don't compute MAPE per keystroke; stamp `as_of` everywhere.
4. **Graduated autonomy via measured accuracy (§1.4):** forecast-accuracy per SKU/category becomes
   the confidence input to `authorize_replenishment`. Poor MAPE → gate stays conservative;
   demonstrated accuracy → wider bounds. Autonomy is *earned from evidence*, never configured on.
5. **Policy packs per tenant (§3):** gate parameters (discount floor, autonomy thresholds,
   emphasis) move to tenant config. Same engine, LVMH-safe and Costco-ready.

---

## 6. Roadmap — Phases 5-7 (continues handoff numbering)

### Phase 5 — CFO pack (compute from data we already have; demo-visible fast)
| # | Item | Build | Anchor |
|---|---|---|---|
| 5a | **GMROI + WOS + inventory turns + sell-through%** — extend the projection assembly + MI tab columns + admin BI panel | S (derivations on existing detectors) | [market_projection.py:90](../src/app/services/market_projection.py#L90), [bi_intelligence.py:19](../src/app/services/bi_intelligence.py#L19) |
| 5b | **Forecast-accuracy loop**: persist `forecast_units_30d` snapshots → nightly compare vs actuals → MAPE/bias per SKU → feed gate confidence | M (new small module + snapshot table) | new `forecast_accuracy.py`; wires into [market_action_policy.py:29](../src/app/services/market_action_policy.py#L29) |
| 5c | **Dead-stock capital + margin-after-returns** | S | 3b detector × wholesale; returns join |
| 5d | Surface CLV/churn (already built, dark) + discount-leakage rollup in admin BI | S (frontend) | [admin_bi.py:458,470](../src/app/routers/admin_bi.py#L458), [api.ts:150 pattern](../src/frontend/admin-react/src/api.ts#L150) |

### Phase 6 — Ops/procurement pack
| # | Item | Build | Anchor |
|---|---|---|---|
| 6a | **ROP/safety-stock on replenishment proposals** (demand×lead + z·σ → "reorder 25, not 'some'") | M | proposals in [commercial_action_proposals.py](../src/app/services/commercial_action_proposals.py) |
| 6b | **OTIF / fill-rate / backorder rate** from orders+cases+shortfall events | M | orders (`tracking_number`,`carrier`), availability events |
| 6c | **PPV**: quoted vs last-invoice vs list on the economics strip | S | [margin_advisor.py:79](../src/app/services/fulfillment/margin_advisor.py#L79) |
| 6d | **ABC/XYZ** batch classification + supplier lead-time *variance* | S | scorecard + sales facts |

### Phase 7 — Positioning pack (sell-alongside-ERP)
| # | Item | Build |
|---|---|---|
| 7a | **Tenant policy packs** (luxury no-discount / club bulk / grocery FEFO note) as gate config | M |
| 7b | **Read-only canonical-fact importers** for NetSuite/SAP exports → `marketing_event_fact` (extends [erp/sync.py], adapters) | M-L |
| 7c | CCC (DIO/DPO/DSO) once payables read from the payment spine | M |

**Honest external gaps (don't fake):** freight/cost-to-serve (needs carrier cost feed), CAC/ROAS
(needs ad connectors), shrink (needs physical counts), perishable/FEFO (needs expiry attribute).
Label absent, never estimate silently — same doctrine as `external_stock`.

---

## 7. Updated wireframes

### 7.1 Market Intelligence tab v2 (adds CFO columns to the shipped tab)
```
┌─ Decision Trace · Market Intelligence ──────────────── [● live] ─┐
│ Scope: (●) LAP-69763798      as_of 09:41 · basis: observed_sales │
│──────────────────────────────────────────────────────────────────│
│ Product      Vel/DSI  WOS  GMROI  Margin  Proj30d  Fcst-acc      │
│ LAP-69763798  12d    1.7w  3.4×   22.4%   $6.4k   ±9% (good)     │
│ LAP-858DC749  34d    4.9w  1.1×   17.1%   $1.9k   ±31% (weak)    │
│──────────────────────────────────────────────────────────────────│
│ INSIGHT  GMROI 3.4× + fcst-acc ±9% ⇒ replenishment gate          │
│  confidence RAISED for this SKU (earned autonomy)                │
│ DEAD-STOCK CAPITAL  $18.2k tied across 6 surplus SKUs → actions  │
│ ⚠ estimates · confidence-scored · as_of stamped                  │
└──────────────────────────────────────────────────────────────────┘
```

### 7.2 Replenishment card v2 (ROP-quantified, gate-fed)
```
┌─ SHORTAGE · LAP-69763798 ────────────────────────────────────────┐
│ Governed replenishment PROPOSED — quantity is COMPUTED:          │
│  ROP = 2.1/day × 7d lead + safety(z=1.65,σ=0.8) = 21 units       │
│  on-hand 6 → REORDER 25 (next MOQ break: 25 → −5% wholesale)     │
│  evidence: demand ✓ fresh · ATP ✓ · fcst-acc ±9% ✓ · econ HEALTHY│
│  [ Approve reorder ]      supplier send HUMAN-ONLY (GATE 2)      │
└──────────────────────────────────────────────────────────────────┘
```

### 7.3 Admin BI — CFO strip (adds to §3.4 panels)
```
┌─ Admin · Merchant BI ── [Transactions][Pulse][Margin][Suppliers] ─┐
│ [CFO ◀NEW]  GMROI 2.6× ↑ · Turns 8.1/yr · Dead-stock $18.2k ↓    │
│ Discount leakage 1.9% of rev (audited: 7 approvals / 30d)         │
│ Forecast accuracy (portfolio) ±14% MAPE · bias +3% (over-fcst)    │
│ CLV median $1,240 · churn-risk 8% (◀ surfaced from dark endpoints)│
│─ Policy pack: [Standard ▾]  (Luxury: discounts OFF · Club: bulk) ─│
└───────────────────────────────────────────────────────────────────┘
```

---

## 8. Execution order recommendation

**5a → 5d → 6c** are small and demo-visible (GMROI/WOS columns, CLV surfacing, PPV on the strip) —
do before recording if time allows. **5b (forecast-accuracy loop)** is the strategic centerpiece —
it makes "earned autonomy" real and is the single strongest differentiator to narrate. **6a (ROP)**
turns the replenishment card from qualitative to quantitative. Phase 7 is post-demo /
commercialization positioning. Same rules as Phases 0-4: one-concern commits, tests first,
`as_of`+confidence on every number, absent data labeled absent.
