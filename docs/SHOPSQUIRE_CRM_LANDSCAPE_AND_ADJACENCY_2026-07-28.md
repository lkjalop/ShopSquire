# ShopSquire — CRM Landscape, Competitive Position, and Where the Line Is (2026-07-28)

*External research + a grounded audit of what ShopSquire already has. Answers: how do we compare to
HubSpot / Salesforce / Agentforce / Sierra and others; where can we improve market intelligence,
customer engagement, the procurement journey, supplier communications and sales metrics; what's the
low-hanging fruit; why would anyone care; and how do we stop overreaching.*

---

## 0. TL;DR

1. **CRM is a $80B market with a 30–63% failure rate, and the cause is structural, not technical.**
   76% of CRM users say less than half their data is accurate; 38% of failures are adoption failures;
   32% of reps spend >1hr/day on manual entry. The best line in the whole research sweep:
   *"you cannot train or incentivize your way to complete, accurate CRM data when the mechanism for
   producing it is manual."*
2. **ShopSquire has zero CRM and shouldn't build one.** But it has something structurally rarer:
   the customer record as a **byproduct of a governed transaction**, not as data entry.
3. **Correction to yesterday's assessment:** I said decision-level audit becomes non-optional under
   the EU AI Act. Research says **ecommerce recommenders are NOT Annex III high-risk** — they're
   limited/minimal risk. The compliance pull is real for **procurement and spend controls**, not for
   the shopper lane. That reframe strengthens the procurement wedge and weakens the shopper one.
4. **The asymmetry in the codebase is the strategy, and it's currently backwards from the demo.**
   35 fulfillment + 10 supplier modules vs **6** customer-engagement modules. The procurement side
   is the deep, defensible, hard-to-copy asset. The shopper chat is the commoditised part everybody
   is racing on.
5. **The line:** ShopSquire writes **drafts + evidence + audit**. It never becomes a system of record,
   never needs daily manual data entry, and never ships a feature that cannot refuse.

---

## 1. What CRM actually is in 2026 (research)

### Market and the agentic shift
- Global CRM projected **>$80B in 2026 → ~$130B by 2030**.
- **Salesforce Agentforce:** ~18,500 customers, **>3B monthly agent workflows**. Pricing has been
  rewritten **three times in ~18 months** — $2/conversation → Flex Credits ($500/100k credits,
  ~$0.10/action) → per-user licences ($125–150/user/mo add-ons). The original $2/conversation model
  "immediately priced out nonprofits, SMBs, and any organization without a large AI budget."
- **HubSpot Breeze:** 288,706 paying customers (vs Salesforce's 150,000+), Spring 2026 launch
  targeting the enterprise. 39% of enterprises expect GenAI delivered via task-automating agents.
- **Salesforce's own framing:** brands that win will have their Shopper Agent live *on their own
  properties* for the 2026 season — discovery moves to third-party AI surfaces, but commercial
  control stays with what the brand can operationalise in its own environment.

### The failure data — this is the important part
| Stat | Value |
|---|---|
| CRM implementation failure rate | **30–63%** (enterprise 38%, SMB 22%) |
| Users saying <half their CRM data is accurate | **76%** |
| Failures caused by poor user adoption | **38%** (+22% change mgmt, +18% data quality = **>75% people/process**) |
| Reps spending >1 hr/day on manual data entry | **32%** |
| Cost of poor data quality to US business | **>$600B/yr** |

**The structural read:** CRM fails because the data-production mechanism is a human typing after the
fact. Every AI-CRM vendor is applying intelligence *on top of* that broken mechanism.

### The adjacent AI-agent market (where the money is moving)
| Vendor | Model | Price | Notes |
|---|---|---|---|
| **Sierra** (Bret Taylor) | outcome-based — pay per resolution | six figures/yr, unpublished | $950M raise @ **$15.8B**, >$150M ARR, 40%+ of Fortune 50. **3–7 month deployments.** |
| **Decagon** | platform fee + per-conversation | ~$95k–$590k/yr | pays for failures too |
| **Intercom Fin** | **$0.99 per resolution**, published | +$29/seat helpdesk | 76% avg resolution — leads independent benchmarks |
| **Zendesk** | partially published; Advanced AI gated behind sales | — | |

AI customer-service market: **$15.12B in 2026**, +25% in two years.

---

## 2. What ShopSquire already has (audited, not assumed)

### There is no CRM
`find src -iname "*crm*"` → **zero modules**. No customer-entity service, no pipeline, no deal object.

### But the primitives exist
| Primitive | Where | State |
|---|---|---|
| `customers` table | demo.sqlite | **7 rows** |
| `customer_trust_scores` | demo.sqlite | present |
| `contact_consent` / `contact_audit` / `contact_event` | `contact_governance.py` | consent + audit spine ✅ |
| `orders` | demo.sqlite | **710 rows** |
| `chat_messages` | demo.sqlite | **3,660 rows** — every conversation already captured |
| `tickets`, `support_objection` | routers/support | present |
| `traffic_source_session` | attribution | present |
| **RFM / CLV** | `bi_intelligence.clv_prediction` | ✅ real, tenant-scoped, currency-partitioned |
| **Churn** | `bi_intelligence.churn_prediction` | ✅ real |
| Attribution, campaign correlation, newsletter draft, upsell | 6 modules | thin |

**The CLV implementation is worth calling out.** Its docstring says *"Tenant-scoped RFM estimate,
**not** a trained lifetime-value prediction"*; it partitions by `(uid_hash, currency)` so it can't mix
AUD and USD; it reads from the canonical `marketing_event_fact` contract; and on missing data it
returns `_unavailable(reason="canonical_customer_events_unavailable")` rather than a fake number.
**That is better currency hygiene than the recommend lane currently has** (see B1 in yesterday's
assessment) and it is exactly the honesty posture a CRM buyer never gets from a CRM.

### The revealing asymmetry
| Domain | Modules |
|---|---:|
| Fulfillment / procurement (`services/fulfillment/`) | **35** |
| Supplier comms + sourcing | **10** |
| Market intelligence | **20** |
| **Customer engagement / lifecycle** | **6** |

The procurement stack is deep, governed, and genuinely hard to reproduce (approval policy, budget
gate, three-way match, change orders, outbound queue + integrity, supplier channel stability,
procurement fraud signals, sandbox transport). **The customer-engagement stack is a stub.**

The demo leads with the shopper chat. The moat is on the other side of the codebase.

### Dark flags (relevant here)
`DECISION_LOG_WRITES_ENABLED` · `EXTERNAL_RESEARCH_ENABLED` · **`STEAM_REQUIREMENTS_LIVE_ENABLED`**
· `FULFILLMENT_AUTONOMOUS_RFQ` · `FULFILLMENT_BUYER_AUTO_REPLY` · `IMAGE_SIMILARITY_ENABLED`

Note: **the live-Steam flag already exists and is already wired as a flag** — it is simply never read
at the call site. That makes yesterday's B7 even cheaper than estimated.

---

## 3. ⚠️ Correction: the EU AI Act argument was overstated

Yesterday's assessment (and `SHOPSQUIRE_EXEC_METRICS_GAP_2026-07-24.md` §3) argued that EU AI Act /
NIST AI RMF make decision-level auditability mandatory, and treated that as the moat.

**That is not right for the shopper lane.** Research is consistent: *recommendation engines used in
ecommerce are typically not high-risk under the EU AI Act*; retail personalisation, AI search, demand
forecasting and merchandising algorithms fall into **limited or minimal risk**, carrying at most
Article 50 transparency duties. Annex III high-risk is biometrics, critical infrastructure, education,
employment, essential services (incl. creditworthiness), law enforcement, migration, justice.

**Where the audit argument genuinely holds:**
- **Procurement / spend controls** — segregation of duties, approval thresholds, three-way match are
  audited under ordinary financial-controls regimes regardless of AI. ShopSquire already implements
  these as first-class objects.
- **Agent-to-database access** — 61% of orgs have fragmented logs, 33% lack evidence-quality audit
  trails, 78% have taken no meaningful compliance steps. The general governance pressure is real even
  where the Act's high-risk articles don't bite.
- **Australian Consumer Law** — misleading claims about product capability. The cite-or-suppress
  narration guard maps to this directly and is a *better* ANZ argument than the EU AI Act.

**Net effect on strategy:** don't sell the shopper agent on compliance. Sell the *procurement and
spend* side on compliance, and the shopper side on being right. This reframe **strengthens** the case
for where the codebase is already deepest.

---

## 4. How ShopSquire compares

| Player | What they own | Their pricing/adoption reality | What they will not do |
|---|---|---|---|
| **Salesforce / Agentforce** | the SoR + enterprise distribution | 3 pricing models in 18 months; SMB priced out | governed *procurement* actions; supplier comms; margin-gated authorization |
| **HubSpot / Breeze** | SMB→mid-market CRM, 288k customers | far better SMB motion than SFDC | commerce depth, procurement, supplier side |
| **Sierra** | autonomous CX agents, outcome pricing | $15.8B, F50, **3–7 month deployments**, six figures | mid-market; merchant-side ops; procurement |
| **Decagon / Fin / Zendesk** | support deflection | Fin $0.99/resolution published | anything outside the ticket |
| **Klaviyo** | ecommerce CDP + lifecycle messaging | the default B2C ecommerce data layer | decisions, governance, procurement |
| **Gorgias** | ecommerce support desk | integrates *with* Klaviyo, not a CRM | same |
| **Shopify Sidekick** | merchant copilot inside Shopify | free-ish, shallow | cross-stack; deep procurement |
| **Coupa / SAP Ariba** | enterprise source-to-pay | F500, heavy, expensive | conversational surface; mid-market |
| **Zip** | intake-to-procure **orchestration on top of existing tools** | explicitly startup→mid-market | commerce/buyer side; catalog truth |
| **ShopSquire** | governed decision layer spanning **buyer ↔ merchant ↔ supplier** with one audit trail | pre-pilot | — |

**Zip is the closest structural analogue and the most useful mental model.** It won by being an
*orchestration layer on top of existing procurement tools* rather than replacing them, aimed at
mid-market. That is exactly ShopSquire's doctrine ("system of intelligence, never system of record"),
and it validates the shape. It also means the procurement-orchestration category has a funded,
focused incumbent — so the differentiator has to be the thing Zip doesn't have: **the buyer-side
catalog truth and the CV/security lane feeding the same audit trail.**

**The genuinely unoccupied square:** nobody spans *buyer conversation → catalog truth → margin →
procurement → supplier communication* with **one** per-decision evidence trail. CRM vendors own the
customer. Support vendors own the ticket. Procurement vendors own the PO. **Nobody owns the join.**

---

## 5. Where to improve — by the four areas you named

### 5.1 Market intelligence (20 modules — broad, but unmeasured)
| Gap | Why it matters | Cost |
|---|---|---|
| **Forecast accuracy loop (WAPE/MAPE + bias)** | you forecast but never score yourself. SAP IBP/NetSuite always report it. It is also the input that lets autonomy be **earned** rather than configured | **M** |
| **GMROI / WOS / inventory turns / sell-through** | the metrics a CFO actually runs on; all computable from data you already have | **S** |
| **Dead-stock capital ($ tied in surplus)** | one join; instantly legible to an owner | **S** |
| **ABC/XYZ classification** | standard in every ERP; cheap batch | **S** |

### 5.2 Customer engagement (6 modules — the thinnest area)
| Gap | Why | Cost |
|---|---|---|
| **Surface the dark CLV/churn endpoints** | already built and correct; zero UI. Free credibility | **S (frontend)** |
| **Conversation → customer profile** (chat_messages 3,660 rows are unmined) | this is the CRM-without-CRM play (§6.1) | **M** |
| **Post-purchase lifecycle triggers** (replenishment reminder for consumables, warranty window) | the honest, non-spammy half of lifecycle marketing | **M** |
| **Preference persistence across sessions** | you already have Redis session memory + `preferences` router; it doesn't survive as a durable profile | **M** |

### 5.3 Procurement journey (deepest asset — polish, don't extend)
| Gap | Why | Cost |
|---|---|---|
| **ROP / safety-stock quantity on proposals** | turns "reorder some" into "reorder 25, next MOQ break at 25 → −5%". Quantitative proposals are what make a gate credible | **M** |
| **`external_stock` / supplier ATP** | today supplier availability is **RFQ-based, not a live feed** — you must never claim otherwise on camera. Even one real connector changes the story | **M-L (external)** |
| **Cadence/consumption-based replenishment** | today it's event-triggered only; no standing-order primitives | **M** |
| **PPV (quoted vs invoiced vs list)** | one strip on economics; procurement people care intensely | **S** |
| **`fulfillment_cases` table is missing in the demo DB** | bulk-order frequency starts at 0 — honest, but it means the procurement analytics have no history to show | **S (seed)** |

### 5.4 Supplier communications (strong; two real gaps)
| Gap | Why | Cost |
|---|---|---|
| **Supplier-channel stability regression lock** | an amendment must never silently switch email→API→EDI. You have `supplier_channel.py`; pin it with a test | **S** |
| **Supplier scorecard → lead-time *variance*** | you have 859 audit rows and average lead time; variance is what feeds safety stock | **S** |
| **Inbound reply → structured evidence** | you just built quarantine + dispositions (uncommitted); finish the loop so a supplier reply updates the case's evidence, not just its status | **M** |

### 5.5 Sales metrics
| Gap | Why | Cost |
|---|---|---|
| **Attach/upsell rate + margin-mix by decision** | you have `upsell_engine`, `checkout_upsell`, `attribution` — but no rollup that says "the assistant added $X margin" | **S** |
| **Assisted-conversion attribution** | the single number a merchant will judge a pilot on | **M** |
| **Discount leakage rollup** | proposals are audited; aggregate them into "% of revenue given away" | **S** |
| **Refusal → recovery rate** | *your* metric, nobody else's: when the platform refused, what happened next? (RFQ raised / alternative bought / lost). This is how you prove refusals make money | **M** |

---

## 6. Low-hanging fruit, ranked — with why anyone cares

### 6.1 🥇 The "CRM without a CRM" play — *conversation → customer profile*
**Build:** derive a durable customer profile from data you **already capture** — 3,660 chat messages,
710 orders, support tickets, consent records — and write it as evidence with provenance and `as_of`.
Constraints stated by the buyer ("I need 16GB", "not Apple", "budget $1,800"), workload intents,
refusals encountered, and what they actually bought.

**Why anyone cares:** this attacks the *structural* CRM failure directly. 76% of CRM data is
inaccurate because a human types it after the fact; 32% of reps burn an hour a day on entry. A
profile that is a **byproduct of a governed transaction** cannot rot the same way. That is a sentence
a CRM buyer has never heard from a CRM vendor.

**Cost:** S–M. The data is already in the DB. **This is the highest value-per-line item on the list.**

### 6.2 🥈 Surface CLV / churn / RFM in the admin UI
Built, correct, honest about its limits, **and completely invisible**. Pure frontend wiring against
existing endpoints (`admin_bi.py:731,745`). **Cost: S.** Instant "this is a real product" signal.

### 6.3 🥉 Turn on the live Steam lane
The flag **already exists** (`STEAM_REQUIREMENTS_LIVE_ENABLED`) and is simply never read at
[recommend_workload_stage.py:171](../src/app/services/recommend_workload_stage.py#L171). Kills the
single most obvious "this demo is rigged" criticism and is the concrete proof of the BYO-model thesis.
**Cost: S.**

### 6.4 CFO metric strip — GMROI · WOS · turns · dead-stock capital
All derivable from data you have. Four numbers that make an owner say "these people know retail."
**Cost: S.**

### 6.5 Refusal → recovery rate
Nobody else can even measure this, because nobody else refuses. It converts your central design
choice from a liability ("it says no a lot") into a P&L line. **Cost: M.**

### 6.6 Flip `DECISION_LOG_WRITES_ENABLED` on locally + fix the new silent swallow
From yesterday's B0.5. The audit trail is the product; it doesn't write in the config you demo from.
**Cost: 30 min.**

---

## 7. Where the line is — how to stop overreaching

You have 390k lines, 704 routes and no customer. The failure mode is not "not enough features."
Three tests, applied to every proposed feature:

### Test 1 — The System-of-Record test
> *If a merchant loses ShopSquire tomorrow, do they lose data they cannot reconstruct?*

If **yes**, you have overreached. Customer master records, the financial ledger, order truth,
inventory truth belong to Shopify / NetSuite / SAP. ShopSquire reads canonical facts and writes only
**drafts, evidence, and audit**. This is already your stated doctrine — the discipline is applying it
when a feature is tempting.

**Concretely this forbids:** owning the customer record, owning the ledger, owning the PO of record.
**It permits:** deriving a profile *from* their data, drafting a PO *for* their system, auditing every
decision *about* their data.

### Test 2 — The seat test
> *Does this feature require a human to log in daily and type things in?*

If **yes**, you've built a CRM and you have just inherited its 30–63% failure rate and 38%
adoption-failure mode. Everything ShopSquire produces should be a **byproduct of a transaction that
already happened**. No data-entry screens. Ever.

### Test 3 — The refusal test
> *Can this feature refuse?*

If a feature has no bounded vocabulary, no evidence requirement and no gate, it isn't ShopSquire
architecture — it's a generic LLM feature that Sierra, Fin or Agentforce will do better, cheaper, and
with distribution you don't have. **Your architecture is the refusal.** A feature that can't refuse
doesn't belong in it.

### The explicit "don't build" list
| Don't build | Because |
|---|---|
| Inbox / ticketing UI | Gorgias and Zendesk own it; you'd spend a year on table stakes |
| Email sending infrastructure | Klaviyo owns the ecommerce lifecycle layer |
| Sales pipeline / deals / opportunities | Salesforce and HubSpot; this is the actual CRM, don't |
| A payments ledger | you integrate; you never become the SoR for money |
| General-purpose support deflection | Fin is $0.99/resolution at 76% — you cannot win this |
| A second vertical **before a first pilot** | pharmacy is a great idea *after* someone real uses it |

### The line, in one sentence
> **ShopSquire is the layer that decides and proves — never the layer that stores or sends.**

Everything upstream of "decide" (catalog, customer, inventory, money) belongs to their stack.
Everything downstream of "prove" (send, post, charge) belongs to a connector behind a human gate.

---

## 8. What this means for the roadmap

The pilot blockers from yesterday (B0 commit · B1 currency · B2 tenant identity · B3 labels ·
B0.5 silent-swallow + decision-log) are **unchanged and still first**. Nothing in this document
should start before them.

After those, the ordering this research suggests:

1. **6.2 + 6.4 + 6.3** — one week, pure surfacing of things that already work. Highest
   credibility-per-hour in the repo.
2. **6.1 conversation → customer profile** — the strategically distinctive item, and the one that
   makes "CRM" a thing you *displace* rather than a thing you build.
3. **5.5 refusal → recovery + assisted-conversion** — the metrics that let a pilot partner answer
   "did it help?", which is pilot-readiness condition #5.
4. **5.3 ROP quantities + PPV** — makes the procurement gates quantitative, which is where the
   compliance argument actually holds (§3).
5. Everything else — second vertical, connector registry, voice, MCP — **after a pilot**.

**The strategic reframe worth sitting with:** the demo leads with the shopper chat, which is the most
crowded, best-funded, least defensible square on the board. The codebase's real asset — 45 modules of
governed procurement and supplier communication with an audit trail — is the part nobody in the CRM,
CX-agent, or shopper-agent race is building, *and* it is the part where the compliance argument is
genuinely true rather than aspirational.

---

## Sources

- [Can HubSpot's agentic AI bet disrupt enterprise CRM's old guard? — Futurum Group](https://futurumgroup.com/insights/can-hubspots-agentic-ai-bet-disrupt-enterprise-crms-old-guard/)
- [CRM: AI Shift to Autonomous Agents — Klover.ai](https://www.klover.ai/crm_ai_shift_to_autonomous_agents_and_self_driving_software_indepth_analysis_2026/)
- [HubSpot Market Share 2026 — Resonate](https://www.resonatehq.com/blog/hubspot-market-share)
- [Salesforce CRM Trends in 2026](https://amroar.com/salesforce-crm-trends-2026/)
- [Agentforce Cost in 2026: Flex Credits and Pricing Models — MagicFuse](https://magicfuse.co/blog/agentforce-cost)
- [The Doomed Evolution of Salesforce's Agentforce Pricing — Monetizely](https://www.getmonetizely.com/blogs/the-doomed-evolution-of-salesforces-agentforce-pricing)
- [Salesforce Agentforce Pricing](https://www.salesforce.com/agentforce/pricing/)
- [Sierra AI: The Complete Guide (2026) — Macha](https://www.getmacha.com/blog/sierra-ai-complete-guide)
- [Sierra Is Building the AI Agent Layer for the Fortune 500 — ChatForest](https://chatforest.com/reviews/sierra-ai-enterprise-agent-platform-bret-taylor-950m-series-e-2026/)
- [Bret Taylor of Sierra on AI agents and outcome-based pricing](https://sierra.ai/resources/podcasts/bret-taylor-of-sierra-on-ai-agents-outcome-based-pricing-and-the-openai-board)
- [Sierra vs Decagon vs Fin vs Ada (2026): The Honest Comparison — Drag](https://www.dragapp.com/blog/ai-support-agents-compared/)
- [AI Agent Pricing Comparison 2026 — Fin](https://fin.ai/learn/ai-customer-service-agent-pricing-comparison)
- [What Is Klaviyo? Core Features & Pricing Guide (2026) — SHOPLINE](https://www.shopline.com/blog/what-is-klaviyo)
- [Is Gorgias a CRM? Gorgias vs a CRM, Explained (2026) — Macha](https://www.getmacha.com/blog/is-gorgias-a-crm)
- [Why Do 70% of CRM Projects Fail? — VantagePoint](https://vantagepoint.io/blog/hs/why-70-of-crm-projects-fail-and-how-the-people-process-technology-framework-prevents-it)
- [CRM Statistics 2026 — Axis Intelligence](https://axis-intelligence.com/crm-statistics/)
- [CRM Adoption: Why It Fails and What Actually Fixes It — Backstory](https://www.backstory.ai/sales-activity-capture-cluster-pages/crm-adoption-why-it-fails-and-what-actually-fixes-it)
- [EU AI Act for Ecommerce: What to Do Before August 2026 — Alhena](https://alhena.ai/blog/eu-ai-act-ecommerce-compliance/)
- [Annex III: High-Risk AI Systems — EU Artificial Intelligence Act](https://artificialintelligenceact.eu/annex/3/)
- [EU AI Act for eCommerce FAQ — Scandiweb](https://scandiweb.com/blog/eu-ai-act-for-ecommerce-frequently-asked/)
- [The EU AI Act and AI Agent Audit Trails — AI2sql](https://ai2sql.io/ai-blog/eu-ai-act-agent-audit-trails-database)
- [AI Agent Governance: Policy and Compliance 2026 Guide — Digital Applied](https://www.digitalapplied.com/blog/ai-agent-governance-policy-compliance-2026)
- [Zip vs Coupa 2026 — ProcureDesk](https://www.procuredesk.com/zip-vs-coupa/)
- [AI for Procurement: A 2026 guide to ROI & orchestration — Zip](https://zip.com/blog/ai-in-procurement)
- [Australia CRM Market — Ken Research](https://www.kenresearch.com/australia-customer-relationship-management-crm-market)
- [Supplier Relationship Management Software Market Forecast](https://www.verifiedmarketreports.com/product/supplier-relationship-management-software-market/)
- [Agentic Commerce Standards: UCP vs ACP vs AP2 in 2026 — Digital Applied](https://www.digitalapplied.com/blog/agentic-commerce-standards-ucp-acp-ap2-2026-merchant-guide)

*Research + audit only. No code changed.*
