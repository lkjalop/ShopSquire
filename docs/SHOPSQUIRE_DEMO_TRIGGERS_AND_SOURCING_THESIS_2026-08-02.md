# ShopSquire — Decision Trace Demo Triggers + the Sourcing/Dropship Question (2026-08-02)

*What the shopper-side trace (5173) actually renders, exactly how to trigger it, three demo paths,
and an honest answer on dropshipping.*

---

## 1. Yes — it's all there. Verified in the render paths.

### Market Intelligence tab — real, and richer than expected
Renders per shown SKU (`DecisionTrace.tsx:4084-4118`):
- **Demand** — trend + `forecast_units_30d`
- **Inventory** — `stock_on_hand` + **DSI** (`velocity_dsi_days`)
- **Per-metric drill-down** — value, unit, **status**, **confidence %**, and
  **`Lineage: provenance_chain.join(' → ')`**

That lineage row is the sleeper. Most BI panels show a number; this one shows *where the number came
from*, and prints `unavailable` / `not supplied` rather than a zero when it doesn't have it.

### Procurement tab — RFQ-first by design
The code comment states the intent outright:
> *"RFQ-FIRST: the drafted supplier RFQ is the first-class object of this tab… The RFQ/email card
> should be the first-class object"*

Renders: the drafted supplier email (`procCase.state_json.draft`), the **send gate**, deal economics
(`margin_advice.deal_projection`), discount authorisation, and — the best one —
> *"Outbound integrity blocks — the platform quarantining its OWN drafted supplier mail"*

Agents surfaced: `Market_Intelligence_Agent`, `Procurement_Agent`, `Alternatives_Agent`,
`Supplier_Selection_Agent`, `Procurement_Split_Agent`, `Supplier_Channel_Agent`.

---

## 2. The triggers (this is the part you need)

| Panel | Trigger | Source |
|---|---|---|
| **Market Intelligence** | any product turn where the intelligence stage runs — emits `market_projection` trace events | `recommend_intelligence_stage._market_projections()` → `market_projection.emit_projection_events()` |
| **Procurement** (● dot) | `procurementCaseId` exists, **or** any event whose `source_id`/`event_type` contains `procurement · split · supplier · sourcing · availability · channel` | `DecisionTrace.tsx:1321` |
| **PROCUREMENT lane** | **`quantity >= 2`** | `turn_router.py:498` — `lane="PROCUREMENT" if quantity is not None and quantity >= 2 else "SEARCH"` |
| **Drafted RFQ email** | materialises at **cart → "Confirm delivery plan" (GATE 1)** | `fulfillment/draft.py::draft_and_record` |
| **Deal economics + draft body** | **`canSeeOperatorDraft = !!getOwnerApiKey()`** | `DecisionTrace.tsx:716` |

### ⚠️ The one that will bite you on camera
`VITE_OWNER_API_KEY` **must be set and must match backend `OWNER_API_KEY`**, or the procurement tab
renders without the drafted email and without deal economics — and you'll be demoing the empty half.

```bash
# frontend/.env.development.local
VITE_API_KEY=local-merchant-key
VITE_OWNER_API_KEY=local-owner-key    # must equal backend OWNER_API_KEY
```
**Verify before recording:** open the trace on a bulk query and confirm the deal-economics card
renders green (`proc-deal-economics`), not the amber "Deal economics unavailable" state.

---

## 3. Three demo paths — each proves a different thing

### Path A — "It changes because the situation changed" *(prove it's not scripted)*
**Do:** run three related queries back to back and leave the Market Intelligence tab open.
1. `"gaming laptop under $2000"`
2. `"what about 15 of them"` ← crosses `quantity >= 2` → **PROCUREMENT lane, procurement dot appears**
3. `"actually make it 40"` ← economics shift, bulk break changes

**Show:** the demand/DSI/forecast values differ per SKU, the confidence percentages differ, and the
lineage row names a different provenance chain per metric.

**Why this one first:** the single most common accusation against an AI demo is *"it's hardcoded."*
Fluctuation that tracks a stated reason kills that in 20 seconds. **Do not narrate the numbers —
narrate that they moved and why.**

**Signals to an architect:** the intelligence stage is a real pipeline stage with per-SKU evidence,
not a template. The `status`/`confidence`/`lineage` triple says someone thought about *unavailable*
as a first-class value.

---

### Path B — "The agent drafted a supplier email, then quarantined its own draft" 🥇
**Do:** bulk query (qty ≥ 2) → add to cart → **Confirm delivery plan (GATE 1)** → open Procurement.

**Show, in this order:**
1. The **drafted RFQ email** — recipient, subject, body, quantity, terms
2. The **send gate** — `send_gate: human`, `auto_sent: false`
3. **Deal economics** — list → wholesale → margin, bulk break, max buyer discount (operator-only)
4. **The outbound integrity block** — the platform refusing to release *its own* drafted mail

**Why this is the video:** every agent demo shows an agent doing something. Almost none show an agent
*being stopped by its own platform*. The moment the system quarantines mail it wrote itself is the
most memorable 15 seconds you have, and it's the perfect answer to David's *"what if the RFQ email is
wrong?"*

**Signals to an architect:** segregation of duties is architectural, not procedural. Model proposes ▸
gate authorizes ▸ connector executes ▸ observer records — visible as four distinct agents in one
trace.

**Signals to a business owner:** *"your agent cannot email your supplier without you. That's not a
setting, it's the design."*

---

### Path C — "Ask it something it can't know"
**Do:** a cross-currency comparison, or a bulk quantity exceeding known stock.

**Show:** the refusal + the reason (missing FX authority / ATP `unknown` because reservations weren't
supplied), then cut to `currency_authority.py` — 188 lines, 8 refusals.

**Why:** it's the differentiator, it's 30 seconds, and it's the one thing no competitor demo will
show you.

**Signals to an architect:** abstention is enforced in a deterministic authority, not prompted. There
is no jailbreak for `convert_minor_units` refusing without an approved rate.

---

### Sequencing for a single LinkedIn video
**A (30s) → B (90s) → C (30s) → the concession (15s).** Under three minutes. Lead with fluctuation to
kill "it's scripted", spend the middle on the self-quarantine, close on the refusal, and end with
*"no customer, synthetic data, here's what I can and can't prove."*

---

## 4. Why a business owner wants this *native* to their stack

The architecture argument that lands with an owner, in their language:

| Their system | What it does | What it doesn't do | Where ShopSquire sits |
|---|---|---|---|
| **ERP / SAP / NetSuite** | records what happened | doesn't decide what should happen next, doesn't explain itself | reads canonical facts, proposes the next action with evidence |
| **Inventory management** | tells you the count | conflates on-hand with available; can't tell you what it *doesn't* know | ATP with an explicit `unknown` and a reason |
| **CRM** | stores what a human typed | 76% of CRM data is inaccurate because entry is manual | derives account facts from transactions — *"never typed"* |
| **Their database** | the truth | no semantics — a column can't refuse | authorities that make an invalid comparison unconstructable |

**The sentence for owners:**
> *"It doesn't replace your ERP — it reads it. Your ERP is the system of record; this is the layer
> that decides and proves. Turn it off tomorrow and you lose no data you can't rebuild."*

**Why native matters:** the value compounds with *their* data. A SaaS assistant sees a slice through
an API. A system inside the perimeter reads the ledger, the inventory, the supplier history and the
conversation — and can therefore refuse on grounds a slice can't see.

---

## 5. The dropshipping question — half right, and the good half isn't dropshipping

### Where the instinct is correct
Dropshipping removes the seeded-inventory problem for a **demo**, and that is genuinely useful. You
don't need 500 inventory rows to tell the story.

### Where it's wrong as a market
| Dropshipping reality | Effect on ShopSquire |
|---|---|
| Buyers are solo/small operators | Won't self-host, won't pay much, have no ERP |
| They want SaaS, cheap, instant | Contradicts the sovereign/self-hosted thesis entirely |
| No SoD, no procurement governance, no audit need | Your entire differentiator is irrelevant to them |
| Crowded tooling market (AutoDS, Zendrop, Spocket, DSers) | You'd compete on features against funded incumbents |
| Many tiny customers | Moves you away from "one design partner" — the thing you actually need |

**Verdict: dropshipping as a demo simplification, yes. As a market, no.** It walks away from every
advantage you have.

### 🎯 But the last line of your question is the good idea

> *"how will that help product buyers source new products for their own range?"*

**That isn't dropshipping — that's assortment planning / new product introduction.** And it is a real,
high-value B2B problem that *strengthens* the wholesale wedge rather than replacing it:

- Which products should I add to my range?
- Which supplier do I source from, and are they legitimate?
- What's the **landed** cost — freight, duty, GST — not the quoted unit price?
- What's the lead-time **variance**, not the promised lead time?
- What demand evidence supports carrying it at all?

**Every one of those is something you already built:**

| Sourcing question | Existing capability |
|---|---|
| Which supplier? | supplier composite: OTIF · quality · `reliability = exp(-σ_lead/mean_lead)` · `insufficient_evidence` |
| Real cost? | landed-cost quote comparison (freight + duty + breaks), refuses cross-currency without dated FX |
| Delivery risk? | lead-time variance feeding safety stock |
| Legit supplier? | supplier domain guard, procurement fraud signals, hostile-reply quarantine |
| Worth stocking? | demand evidence with provenance, forecast + WAPE, dead-stock capital |
| Product authentic? | CV forensics, near-duplicate/counterfeit detection |

### Why Asian sourcing makes it *stronger*, not weaker
Sourcing from China/Vietnam/etc. is where your specific authorities earn their keep:
- **Cross-currency is the default case**, not an edge case — USD/CNY/AUD. Your FX refusal stops being
  a curiosity and becomes table stakes.
- **Landed cost is where the margin actually lives** — a quoted unit price from Shenzhen is
  meaningless without freight, duty and GST. Most tools compare list price and lie.
- **Lead-time variance is the whole risk.** 30 days ± 3 vs 21 days ± 14 — your reliability formula is
  literally built for this and most tools score on average speed.
- **UoM ambiguity is constant** — "per piece" vs "per carton" vs "per pallet". `uom_category_mismatch`
  is not academic here; it's the single most common costly error in import sourcing.
- **Supplier legitimacy is a live fraud surface** — new supplier, first order, wire transfer. Your
  procurement fraud signals and quarantine have an actual job.

### The reframe
> **Not "dropshipping tool." A sourcing-decision layer for buyers building a range — where the
> supplier is overseas, the cost is landed not quoted, and the risk is variance not speed.**

This keeps the wholesale/B2B buyer, keeps self-hosted (a real importer has an ERP and margin data
they won't upload), keeps the governance story (spend controls, SoD, three-way match), and **removes
your weakest dependency** — you no longer need a deep seeded inventory to be credible, because in
sourcing the interesting evidence is about the *supplier*, not your shelf.

**One honest caveat:** it makes `external_stock` (supplier ATP) matter *more*, not less. In sourcing
you genuinely never know the supplier's stock — which means the honest `unknown` is exactly the right
answer and you should say so on camera rather than hide it.

---

## 6. Recommendation

1. **Record Path B this week.** Set `VITE_OWNER_API_KEY` first, verify the green economics card
   renders, then shoot A→B→C in one take under three minutes.
2. **Frame it as sourcing, not dropshipping.** "Helping a buyer source a new range from overseas
   suppliers" is a sharper, higher-value story than "dropshipping tool," and it's the same demo.
3. **Do not build a dropshipping integration.** The demo framing costs nothing; the market pivot
   would cost you every advantage you have.

---

*Verified against `DecisionTrace.tsx`, `turn_router.py`, `fulfillment/draft.py`, and
`recommend_intelligence_stage.py` at HEAD `b3dca021`. No code changed.*
