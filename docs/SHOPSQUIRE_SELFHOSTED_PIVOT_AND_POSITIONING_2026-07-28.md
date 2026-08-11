# ShopSquire — Self-Hosted Posture, CRM Connectivity, Wholesale Pivot & Positioning Axes (2026-07-28)

*Reassessment under a deliberately lower-liability posture: ship self-hosted software, let the
customer own the data, the model, and the perimeter. Covers CRM connectivity (native vs API/MCP/
network), decision-trace tab strategy, sales/market metrics, the wholesale→brick-and-mortar pivot,
ERP relationships, and where ShopSquire sits on the competitive plane.*

---

## 0. TL;DR — the self-hosted reframe is the single best strategic move available

Going self-hosted is not "the easy route." It is the route that **deletes four of your six pilot
blockers by construction** and moves you into the one quadrant nobody is fighting over.

| Yesterday's blocker | What self-hosted does to it |
|---|---|
| **B2 tenant identity from `X-Tenant-Id`** | **Mostly dissolves.** Single-tenant deployment = one tenant per perimeter. The header becomes a label, not an authorization boundary. |
| **Data residency / privacy liability** | **Transfers to the customer.** You never hold their customer data, so you can't leak it. |
| **Audit retention obligations** | **Theirs.** Their infrastructure, their retention policy, their DPO. |
| **Multi-tenant isolation proof** | **Not required for v1.** You can ship without it and add it later for a managed tier. |
| B1 currency authority | unchanged — still yours to fix |
| B3 labels | unchanged — still yours to seal |

And the market has moved to meet it: **sovereign cloud IaaS is projected at $80B in 2026**;
NVIDIA's sovereign-AI revenue **tripled past $30B**; the research consensus is that the multi-tenant
SaaS model *"is losing regulated buyers in 2026"* and self-hosted has shifted **from a nice-to-have to
a procurement filter**. On-prem open models now handle 85–90% of enterprise use cases at quality
"indistinguishable from cloud APIs."

**You already built for this without naming it.** BYO-model is a doctrine in your router
(`ROUTER_MODEL → CLASSIFIER_MODEL → certified default`, clamped so a weak model can't break the
system). Ollama-first. Postgres/SQLite portable. Docker-compose ×8. That is a sovereign-AI product
that has been describing itself as a SaaS demo.

---

## 1. How to market it (the positioning that follows)

### The sentence
> **ShopSquire runs inside your perimeter, on your model, against your data — and every decision it
> makes leaves an auditable trace you own. It proposes; your people authorize; nothing leaves without
> a human.**

### The four marketing pillars, in priority order

**1. "Your data never leaves."**
The strongest opening line for any ANZ mid-market buyer nervous about US-cloud exposure (CLOUD Act),
and the *only* line that works for a wholesaler whose supplier pricing is their competitive edge.
Their margin data is the crown jewels. SaaS asks them to upload it. You don't.

**2. "Bring your own model."**
Not a technical footnote — a **cost and independence** argument. Compare honestly:

| Vendor | Pricing |
|---|---|
| Agentforce | $2/conversation → $0.10/action → $125–150/user/mo (3 models in 18 months) |
| Sierra | six figures/yr, 3–7 month deployment, unpublished |
| Decagon | ~$95k–$590k/yr |
| Fin | $0.99/resolution + $29/seat |
| **ShopSquire self-hosted** | **your licence + your GPU. Zero marginal cost per conversation.** |

A wholesaler doing 4,000 order-support interactions a month is looking at $8k/mo on Agentforce
conversation pricing. Self-hosted, that's electricity.

**3. "It refuses, and it shows you why."**
Every competitor optimises conversion — a refusal is a lost sale to them. For a distributor, a wrong
bulk order is a real, expensive, hard-to-reverse mistake. **Reframe the refusal as the feature**, and
make the decision trace the proof.

**4. "Software, not a service."**
You ship a container and a licence. You don't process their data, don't hold their PII, don't become
a sub-processor, don't need SOC 2 to start a conversation. **This is the responsibility ladder you
asked about and it is a legitimate, well-trodden commercial position** — it's how GitLab, Metabase,
Odoo, and every sovereign-AI vendor sells.

### The honest downsides — name them before a buyer does
- **You lose telemetry.** No aggregate learning across customers, no "we see 40% empty-rate across
  the fleet." Mitigate with an **opt-in, aggregate-only, no-PII** telemetry channel.
- **Support is harder.** You debug blind. Mitigate: ship a `support-bundle` command that packages
  logs + metrics + decision-trace samples (redacted) that they choose to send you.
- **Upgrades are theirs.** Versions fragment. Mitigate: a narrow supported-version window, migrations
  that are strictly forward-only, and a loud version banner.
- **You still own correctness.** Self-hosting transfers *data* liability, not *"your software gave
  bad advice"* liability. The narration guard, the refusal gate, and the audit trail are what protect
  you there — which is another reason they are the product.
- **Slower revenue.** Licence + support beats usage-based pricing on trust and loses on expansion.

---

## 2. CRM: what's native, and how you connect the rest

### 2.1 What you have natively (audited)
| Capability | Where | Real? |
|---|---|---|
| RFM / CLV estimate | `bi_intelligence.clv_prediction` | ✅ real, tenant-scoped, currency-partitioned, honest `_unavailable` |
| Churn estimate | `bi_intelligence.churn_prediction` | ✅ real |
| Consent + contact audit | `contact_governance.py`, `contact_consent/audit/event` | ✅ real |
| Conversation history | `chat_messages` — **3,660 rows** | ✅ captured, **unmined** |
| Order history | `orders` — 710 rows | ✅ |
| Customer trust score | `customer_trust_scores` | ✅ |
| Support tickets / objections | `tickets`, `support_objection` | ✅ |
| Attribution / traffic source | `attribution.py`, `traffic_source_session` | ✅ |
| Campaign correlation, newsletter draft, upsell | 4 modules | ⚠️ thin |
| **Customer entity / profile service** | — | ❌ **does not exist** |
| Pipeline / deals / opportunities | — | ❌ (correctly — don't build) |

**You have CRM *facts* and no CRM *object*.** That is the right side of the line to be on.

### 2.2 The connector surface that already exists

```
src/app/erp/
  provider_registry.py      8 providers registered
  connectors/
    netsuite.py             241 ln  ✅ REAL (customers, sales orders, inventory)
    provider_sync.py        230 ln  ✅ REAL generic engine: OAuth client-creds / bearer / API-key,
                                       retry+backoff, erp_sync_state cursor table, SSRF url_guard,
                                       push_entity(entity_type, payload) → outbound_map
    shopify_inventory.py    133 ln  ✅ REAL
    http_inventory.py       112 ln  ✅ REAL generic HTTP
    csv_inventory.py         61 ln  ✅ REAL  ← the underrated one (§2.4)
    sqlite_catalog.py        56 ln  ✅ REAL
    salesforce.py             7 ln  ⚠️ STUB → {lead,account,opportunity}/upsert
    hubspot.py                7 ln  ⚠️ STUB → {contact,company,deal}/upsert
    sap.py / ariba / coupa / dynamics / quickbooks   7 ln each  ⚠️ STUBS
```

**The important nuance:** the CRM stubs are *architecturally correct and functionally fictional*. They
map to `/contacts/upsert`, `/deals/upsert` — paths that do not exist. Real HubSpot is
`/crm/v3/objects/contacts`; real Salesforce is `/services/data/vXX.X/sobjects/Contact`. So you have
**the write path, the auth, the retry, the cursor and the SSRF guard already built** — and no real
endpoint mapping. That is ~a day per provider, not a project.

### 2.3 The four connection modes, and when each is right

| Mode | What it is | Use it for | Effort |
|---|---|---|---|
| **REST connector** (`DeepProviderConnector`) | outbound push + delta pull, OAuth/bearer/key | HubSpot, Salesforce, NetSuite, Shopify — the systems with real APIs | **S per provider** (auth + endpoint map) |
| **MCP server** | expose ShopSquire's *governed* capabilities as tools to *their* agent | letting their Copilot/Claude/ChatGPT ask **your** system for a governed answer. **This is the strategic one** (§2.5) | **M** |
| **Direct DB read** (read-replica / views) | you read their canonical facts from a replica | on-prem ERPs with no usable API (the mid-market reality), legacy WMS, POS systems | **S** — you already have `sqlite_catalog` + `http_inventory` patterns |
| **Network layer** (IPsec/WireGuard/private link) | not an integration — a *transport* | connecting your on-prem container to their on-prem ERP/POS across sites | **ops, not code** |

**On BGP/IPsec specifically:** this is a deployment concern, not an application concern, and treating
it that way is correct. Your job is to be a well-behaved container that talks to a hostname over TLS
and honours `INTERNAL_SERVICE_ALLOWLIST` + `ensure_safe_outbound_url`. Their network team runs the
tunnel. **Do not build networking.** Do publish a reference topology diagram — it is a
sales asset, not an engineering one.

### 2.4 The most underrated connector you already have: **CSV**
`csv_inventory.py` is 61 lines and it is the one that will actually win mid-market and wholesale
deals. Every distributor on a 15-year-old ERP can export a CSV. **Nightly SFTP/file-drop ingestion is
the integration that closes deals the API-first vendors can't reach.** Elevate it from a test fixture
to a supported, documented ingestion path with schema validation and a rejection report.

### 2.5 MCP — the direction that matters
You already treat MCP as an **audited attack surface** (`log_mcp_tool_invocation`,
`record_mcp_security_block(tool, "prompt_injection")` in `tools/runner.py`). Nobody else does that.

The move is to **become an MCP server**, exposing tools like:
```
shopsquire.check_availability(sku, qty)        → network availability + transfer plan
shopsquire.price_for_account(sku, qty, account)→ contract price + break, with evidence
shopsquire.draft_reorder(sku)                  → governed proposal, NEVER sent
shopsquire.explain_decision(trace_id)          → the full evidence trail
```
Their agent asks; **your gates still apply**; the trace still gets written. That is agent-native
commerce where *you keep the governance* — and it's a far better fit for self-hosted than trying to
own the conversation surface.

---

## 3. Decision trace — you have 14 tabs. Do not add a 15th.

Current tabs: `events · execution · summary · why · intent · multimodal · complexity · memory ·
security · market · procurement · evidence · audit · raw`.

**Do NOT add a CRM tab.** Fourteen tabs is already past the point where a viewer explores; it reads
as a debug console, not a product. Adding "CRM" makes it worse and signals you're building a CRM.

### The restructure: 3 audience-scoped views, not 14 peer tabs

```
┌─ BUYER VIEW (default, always visible) ───────────────────────────┐
│  Why this  ·  What I couldn't confirm  ·  Sources                │
│  ← merge: why + evidence + the honest-unknown half of intent     │
└──────────────────────────────────────────────────────────────────┘
┌─ OPERATOR VIEW (role-gated) ─────────────────────────────────────┐
│  Account  ·  Margin & Market  ·  Procurement  ·  Actions         │
│  ← "Account" is where CRM lives — as a PANEL, not a tab          │
└──────────────────────────────────────────────────────────────────┘
┌─ AUDIT VIEW (compliance/dev) ────────────────────────────────────┐
│  Decision chain  ·  Security  ·  Raw                             │
│  ← merge: events + execution + audit + security + raw + complexity│
└──────────────────────────────────────────────────────────────────┘
```

### The three genuine content gaps (regardless of layout)

**1. "Why NOT" is missing.** Every tab explains what was shown. Nothing explains what was *excluded
and why* — out of budget, failed a requirement, wrong currency, not sold, out of stock. **This is
your most differentiated single screen** and the data already exists (`diagnosis.top_failed_keys`
showed `gpu_vram_gb: 14` in yesterday's replay — 14 products failed a VRAM floor and nobody can see
that).

```
┌─ WHY NOT ────────────────────────────────────────────────────┐
│ 47 considered → 10 shown.  33 excluded:                      │
│   14  below GPU VRAM floor (8GB needed, evidence: Steam)     │
│    9  over budget ceiling ($1,800 AUD)                       │
│    6  currency not resolvable (USD, no approved FX)   ⚠️     │
│    3  not sold in this catalog (taxonomy refusal)            │
│    1  inactive / out of stock                                │
│ [ Widen budget ]  [ Relax GPU ]  [ Source via supplier RFQ ] │
└──────────────────────────────────────────────────────────────┘
```
Every exclusion is a **recovery affordance**. This is how a refusal becomes a conversion path.

**2. The Account panel (the CRM answer).** Not a tab — a panel inside the Operator view, and it should
show only what is *derived from transactions*, with provenance:
```
┌─ ACCOUNT · Northside Electrical (acct #4471) ────────────────┐
│ RFM  R 12d · F 8 orders/90d · M $42,180        conf 0.78    │
│ Reorder cadence  ~every 14d (σ 3d)   next due ~2026-08-04    │
│ Stated constraints (from conversation, 3,660 msgs mined):     │
│   "must be 240V" ·  "no Brand X" ·  "net-30 only"            │
│ Refusals hit  2 (both currency) → 1 recovered via RFQ        │
│ Open case  PR-2026-0728-A4  ·  Credit terms  net-30          │
│ ⚠ derived from transactions · as_of 09:41 · never typed      │
└──────────────────────────────────────────────────────────────┘
```
The footer line — *"derived from transactions, never typed"* — **is the entire CRM pitch on one row.**

**3. Trace continuity across a journey.** Traces are per-turn. An account relationship is a
*sequence*. Add a per-account timeline that stitches decisions → orders → cases → refusals.

---

## 4. Sales & market metrics that ecommerce people actually act on

The test for every metric: **does it change what someone does on Monday?**

### Tier 1 — build now, all computable from existing data
| Metric | Formula | The Monday action |
|---|---|---|
| **Assisted revenue & margin** | Σ orders with a decision trace | "is this thing paying for itself?" — the pilot's verdict metric |
| **Refusal → recovery rate** | refused turns → {RFQ / alt bought / lost} | **your metric alone.** Turns refusals into a P&L line |
| **Attach rate & margin mix** | upsell accepted / shown | which bundles to push |
| **Dead-stock capital** | Σ (surplus qty × wholesale) | "there's $18.2k sitting in aisle 4" |
| **WOS / inventory turns** | stock ÷ weekly units; 365/DSI | reorder now or don't |
| **GMROI** | gross margin $ ÷ avg inventory cost | the retail capital-efficiency number |

### Tier 2 — the credibility layer
| Metric | Why it earns trust |
|---|---|
| **Forecast accuracy (WAPE/bias)** | you forecast and never score yourself. Every ERP reports this. And it's the input that lets autonomy be **earned**, not configured |
| **Full-price sell-through** | the merchandising quality metric |
| **Discount leakage %** | proposals are already audited — just aggregate |
| **PPV** (quoted vs invoiced vs list) | procurement people care intensely |
| **Supplier lead-time variance** | you have 859 audit rows and only compute the mean; variance is what feeds safety stock |

### Tier 3 — honest external gaps. Label absent, never estimate.
Freight/cost-to-serve (needs carrier costs) · CAC/ROAS (needs ad connectors) · shrink (needs counts)
· supplier ATP (`external_stock` **does not exist** — supplier availability is **RFQ-based**; never
claim otherwise on camera).

---

## 5. The wholesale → brick-and-mortar pivot

**This is the strongest idea in the conversation.** Take it seriously.

### Why it fits the code you already wrote
| Wholesale need | ShopSquire today |
|---|---|
| Procurement **is** the product, not a side lane | **45 modules** of governed procurement + supplier comms |
| Repeat/cadence replenishment | `market_action_policy`, `reorder_supplier_flow`, velocity/DSI |
| Account-based catalogs + tiered pricing | `supplier_products.price_breaks`, `supplier_catalog` |
| Multi-location stock + transfers | `multi_location_availability` (499 inventory rows) |
| Credit terms / approval thresholds | `budget_gate`, `approval_policy`, `three_way_match` |
| ERP integration is mandatory | NetSuite ✅ real, Shopify ✅ real, CSV ✅, 6 stubs |
| Supplier scorecards | 859 audit rows |
| **Deep security on supplier email** | email XDR, quarantine, dispositions — **B2B is where invoice fraud actually happens** |

### What it fixes, structurally
1. **It inverts the asymmetry.** In wholesale, your 45 procurement modules *are* the product and the
   chat is just the order-entry surface. The thin engagement layer stops being a gap.
2. **The overfit problem shrinks.** A distributor has ONE catalog they own. You're not trying to know
   every product on earth — you're grounding on their price list. The Steam/game problem doesn't exist.
3. **The catalog problem shrinks.** 134 laptops is a joke storefront. As a *wholesaler's* catalog it's
   a plausible starting SKU count.
4. **You need ONE design partner, not a market.** B2B distribution is a few high-value accounts.
   Pilot-readiness condition #5 ("a measurable did-it-help") becomes achievable with one customer.
5. **Refusals have money attached.** A wrong 200-unit order costs real money. Governance stops being
   a philosophy slide and becomes a purchase justification.
6. **Self-hosted is *expected*.** Distributors already run on-prem ERP. You're not asking them to
   change posture — you're matching it.
7. **B2B ecommerce is 16% of manufacturing/distribution sales and growing**; mid-market distributors
   are actively buying to compete with giants; "AI tools integrate directly with NetSuite, SAP
   Business One, Dynamics, Sage, QuickBooks."

### What it costs
- **Buyer-side polish becomes less valuable.** The consumer chat UX work partially depreciates.
- **You need B2B primitives you don't have:** customer-specific contract pricing, credit limits /
  terms enforcement, quote→order conversion, minimum order quantities per account, backorder
  handling, standing orders. (`price_breaks` gets you part-way; per-account contract price is new.)
- **The vertical-blind core gets tested for real** — a distributor's catalog is not laptops.
- **Longer sales cycles.** B2B distribution buys slowly. Offset by: fewer, bigger, stickier.

### The verdict
**Wholesale → brick-and-mortar retail is the better wedge than DTC ecommerce.** It matches where your
code is deep, where governance is a purchase justification instead of a philosophy, where self-hosting
is expected rather than explained, and where one design partner is a real pilot.

The DTC shopper chat doesn't get thrown away — it becomes the **retailer's ordering portal**: a store
owner asking "what do I need to restock for the long weekend?" is the same conversational surface
with far higher intent and far more forgiving latency tolerance.

---

## 6. NetSuite / SAP / ERP — integrate, never compete

**Position: system of intelligence, never system of record.** The ERP owns the ledger, the PO of
record, the inventory truth. You read canonical facts and write **drafts + evidence + audit**.

| ERP | Reality for you |
|---|---|
| **NetSuite** | **your best first target.** Real 241-line connector exists; dominant in ANZ mid-market distribution; good REST API. Finish it. |
| **SAP Business One** | mid-market SAP, common in distribution. (Not SAP S/4 — that's F500 and not your buyer.) Stub only. |
| **MS Dynamics BC** | very common ANZ mid-market. Stub only. |
| **SAP S/4 / Ariba / Coupa** | **do not chase.** Enterprise, long cycles, and Zip already owns the orchestration-on-top position. |
| **QuickBooks / Xero** | ⚠️ **Xero is missing entirely and it is the ANZ SMB default.** Add it. |
| **The long tail on legacy ERPs** | **CSV/SFTP ingestion.** This is how you reach the buyers the API-first vendors can't. |

**The rule that keeps you safe:** if losing ShopSquire means they lose data they cannot reconstruct
from their ERP, you have overreached.

---

## 7. Where you sit — the positioning plane

### Axis 1 — Who you serve × What you optimise

```
                    OPTIMISES FOR CONTROL / GOVERNANCE
                                  ▲
                                  │
   Consent & privacy tools        │        Coupa · SAP Ariba  (enterprise, heavy)
   (narrow, compliance-only)      │        Zip  (orchestration, mid-market) ◀ closest analogue
                                  │        Ivalua · ORO
                                  │
                                  │             ★ WHERE SHOPSQUIRE SHOULD GO
                                  │               (self-hosted · wholesale ·
                                  │                governed buyer↔supplier)
                                  │
   BUYER-SIDE ◀━━━━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━▶ SUPPLY-SIDE
                                  │
                        ◆ SHOPSQUIRE                  OroCommerce · WizCommerce
                          (as demoed today)           (B2B wholesale, no governance)
                                  │
   ChatGPT Instant Checkout       │        Klaviyo (lifecycle)
   Amazon Rufus · Gemini AI Mode  │        NetSuite · SAP (SoR, not decisions)
   Sierra · Decagon · Fin         │
   Gorgias · Shopify Sidekick     │
   Agentforce Commerce            │
                                  ▼
                    OPTIMISES FOR CONVERSION / THROUGHPUT
```

**Read it:** the bottom-left is a knife fight against companies with billions and distribution. The
**upper-right is nearly empty at mid-market** — Zip is the only serious occupant and it has no
buyer-side catalog truth, no CV/security lane, and no conversational grounding.

**You are demoing from the bottom-left. Your code lives in the upper-right.** That gap is the whole
strategic problem, and it is fixable by changing *what you show*, not what you build.

### Axis 2 — Deployment model × Governance depth (the self-hosted case)

```
                          SELF-HOSTED / SOVEREIGN
                                  ▲
                                  │
              Onyx · open agent   │          ★ SHOPSQUIRE (self-hosted +
              frameworks          │            governed + BYO-model)
              (sovereign, no      │            ── essentially uncontested ──
               commerce governance)│
                                  │
   LOW GOVERNANCE ◀━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━▶ HIGH GOVERNANCE
   (black box)                    │                    (gated · evidence · audit)
                                  │
              ChatGPT · Rufus     │          Coupa · Ariba · Agentforce
              Sierra · Fin        │          (governed, but SaaS-only,
              Klaviyo · Gorgias   │           enterprise-priced)
                                  │
                                  ▼
                          MULTI-TENANT SaaS
```

**This is the sharper picture.** Everything with real governance is SaaS-only and enterprise-priced.
Everything self-hosted is a generic agent framework with no commerce governance. **The top-right
quadrant — sovereign *and* governed *and* commerce-specific — has essentially no occupant**, and
sovereign infrastructure spend is heading to $80B in 2026.

### Where you are vs where to go
| | Now | Target |
|---|---|---|
| **Buyer** | DTC consumer shopping for a laptop | **wholesale distributor** selling to B&M retailers |
| **Deployment** | undeclared (implicitly SaaS) | **self-hosted / BYOC, declared loudly** |
| **Hero surface** | shopper chat | **decision trace + governed procurement** |
| **Model** | assumed local Ollama | **BYO-model as a stated commercial feature** |
| **Compliance story** | EU AI Act (**overstated** — retail recs aren't Annex III) | **spend controls + SoD + data sovereignty** (actually true) |
| **Pricing** | undefined | **licence + support, zero marginal cost per conversation** |

---

## 8. What to build — revised, in order

**Unchanged and still first:** B0 commit the cutover · B0.5 silent-swallow + decision-log flag ·
B1 currency authority · B3 seal the labels. Nothing below starts before these.

| # | Item | Why now | Effort |
|---|---|---|---|
| 1 | **"WHY NOT" panel** | most differentiated screen you can build; data already exists; turns refusals into recovery paths | **S** |
| 2 | **Declare the self-hosted posture** — README, deploy guide, reference network topology, `support-bundle` command | it's a marketing + packaging change, not code. Highest leverage per hour in this whole document | **S** |
| 3 | **Conversation → Account profile** (+ the Account panel) | the CRM-without-a-CRM play; "derived from transactions, never typed" | **M** |
| 4 | **Elevate CSV/SFTP ingestion** to a first-class documented path | reaches the mid-market buyers API-first vendors can't | **S** |
| 5 | **Finish the NetSuite connector + add Xero** | ANZ mid-market default stack; NetSuite is already 241 real lines | **M** |
| 6 | **Tier-1 metrics**: assisted margin, refusal→recovery, dead-stock capital, WOS/GMROI | pilot condition #5 — "did it help?" | **M** |
| 7 | **Collapse 14 tabs → 3 audience views** | 14 tabs reads as a debug console | **M** |
| 8 | **MCP server surface** | agent-native commerce where *you* keep the governance | **M** |
| 9 | **B2B primitives**: per-account contract pricing, credit terms, MOQ, standing orders | required if the wholesale pivot is real | **L** |
| 10 | Real HubSpot/Salesforce endpoint maps | ~a day each; the scaffold exists | **S each** |

**Explicitly still deferred:** second vertical, voice, IMAGE V2, hippograph, `chat.py` strangle
(except as needed for the archive).

---

## 9. Where the line is — updated for self-hosted

The three tests from yesterday still hold (System-of-Record · Seat · Refusal). Self-hosting adds a
fourth, and it's the one that keeps this posture honest:

### Test 4 — The blast-radius test
> *If this feature is wrong at 3am with nobody watching, what is the worst outcome?*

- **Acceptable:** a bad recommendation, a wrong metric, an unhelpful refusal, a draft nobody sends.
- **Not acceptable:** money moved, an email sent to a supplier, stock committed, a price changed
  live, a customer record overwritten in *their* CRM.

**Everything in the second list stays behind a human gate — forever, not "until we're confident."**
That invariant is what lets you ship self-hosted software into someone else's perimeter and sleep.

And the corollary that keeps the outbound CRM connector safe: **when you push to their HubSpot or
NetSuite, write to a ShopSquire-namespaced field or a staging object — never overwrite a field a human
owns.** You append evidence; you don't mutate their record.

---

## Sources

- [Best Self-Hosted Enterprise AI Platforms in 2026 — ibl.ai](https://ibl.ai/blog/best-self-hosted-enterprise-ai-platforms-2026)
- [Self-Hosted AI Agent Platforms 2026: CISO & Regulated Buyer Guide — Knowlee](https://www.knowlee.ai/blog/self-hosted-ai-agent-platforms-2026)
- [AI Data Sovereignty in 2026: Why Self-Hosted Is Winning Regulated Industries — Kyra](https://kyra.conversionsystem.com/blog/ai-data-sovereignty-self-hosted-2026)
- [Sovereign AI: Definition, Why It Matters, Top Platforms (2026) — Onyx](https://onyx.app/insights/sovereign-ai)
- [AI and Data Sovereignty in 2026 — AI Magicx](https://www.aimagicx.com/blog/ai-data-sovereignty-cloud-strategy-legal-risks-2026)
- [B2B Ecommerce Trends 2026: AI, ERP Integration & Growth — MageMontreal](https://magemontreal.com/b2b-ecommerce-trends-2026-what-manufacturers-distributors-and-wholesalers-need-to-know/)
- [B2B E-Commerce Platform for Distributors: The Complete Guide (2026) — WizCommerce](https://wizcommerce.com/blog/b2b-ecommerce-software-for-distributors-guide/)
- [The Complete 2026 Distribution Tech Stack Guide — SmarterWay.AI](https://smarterway.ai/resources/guides/distribution-tech-stack)
- [The Best ERP Integration for Wholesale Distributors in 2026 — First Page Sage](https://firstpagesage.com/business/best-erp-integration-for-wholesale-distributors/)
- [Top Use Cases of AI in B2B E-Commerce: A 2026 Wholesale Guide — WizCommerce](https://wizcommerce.com/blog/ai-in-b2b-ecommerce-use-cases/)
- [Zip vs Coupa 2026 — ProcureDesk](https://www.procuredesk.com/zip-vs-coupa/)
- [Agentforce Cost in 2026 — MagicFuse](https://magicfuse.co/blog/agentforce-cost)
- [Sierra vs Decagon vs Fin vs Ada (2026) — Drag](https://www.dragapp.com/blog/ai-support-agents-compared/)
- [Annex III: High-Risk AI Systems — EU Artificial Intelligence Act](https://artificialintelligenceact.eu/annex/3/)

*Research + audit only. No code changed.*
