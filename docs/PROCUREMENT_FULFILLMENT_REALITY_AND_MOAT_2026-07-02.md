# Procurement fulfillment — how it really works, what ShopSquire has, and the moat (2026-07-02)

This answers two things: (1) **are the assumptions right** about shipping, returns, stakeholder
notification, and blind-ship disclosure, and (2) **why is this a defensible platform, not a toy**. It is
grounded in how real e-tailers and B2B procurement actually operate, then mapped to the codebase file:line.

---

## 0. Verdict on the mental model: mostly RIGHT, with one reframe

The questions asked (channel per supplier, delivery/shipping status, stakeholder notification, returns
fraud, blind-ship disclosure) are **exactly the questions a real procurement platform must answer** — not
false assumptions. The one reframe that makes everything downstream click:

**Decide the FULFILLMENT MODEL first — it determines who ships, who discloses, who handles returns.**
- **1P / own-warehouse:** platform holds stock, ships from its own/3PL warehouse. Full control, capital-heavy.
- **Dropship (3P):** platform never holds the item; on order the SUPPLIER ships direct to the buyer. Low
  capital, less control. **Blind shipping** is standard here (buyer sees the platform brand, not the supplier).
- **Marketplace:** third-party sellers list + fulfill.
- **Just-in-time procurement / shortfall-sourcing:** you can't pre-stock 40 of every SKU, so when ecommerce
  stock can't cover a (bulk) order you **source the gap from suppliers on demand** via RFQ/PO.

**ShopSquire is the just-in-time / shortfall-sourcing model** (bulk shortfall → RFQ → supplier), with a
drop-ship-the-gap option. That is *why* the whole procurement subsystem exists: pre-stocking bulk is
impossible, so the platform orchestrates on-demand sourcing under governance + audit.

---

## 1. The real end-to-end fulfillment lifecycle (the research)

Requisition/RFQ → Quote → **PO** → order confirmation → **ASN (Advance Ship Notice, EDI 856)** →
pick/pack → **carrier ship** → in-transit tracking → **delivery** → **invoice (EDI 810)** → payment →
(returns / RMA). Each arrow is a stakeholder-notification point.

**How e-tailers actually talk to suppliers** (this is why the channel router matters):
- **Email** — RFQ/PO as PDF; the SMB default.
- **Phone** — relationship-driven / legacy suppliers. A HUMAN must call; an automated/LLM voice call reads
  as a scam and burns the relationship. (Built this session — never voice-call.)
- **Supplier portal** — log in and submit (Amazon Vendor Central style).
- **EDI (X12 850 PO / 856 ASN / 810 invoice)** over AS2/VAN/SFTP — mandated by big retailers (Walmart/Target).
- **cXML punchout / Ariba–Coupa network** — enterprise procurement networks.
- **Direct API / ERP-to-ERP** (SAP IDoc, NetSuite) — modern suppliers.

**Blind shipping** (the "do we tell the buyer it's from an external supplier?" question): yes, this is a real,
standard concern. In dropship, the parcel/paperwork shows the PLATFORM brand, not the supplier — to protect
supplier relationships + brand. "Double-blind" = neither party sees the other. **ShopSquire is already built
for this** — every buyer-facing projection is supplier-blind.

---

## 2. What ShopSquire HAS vs NEEDS (mapped)

| Real-world concern | Status | Evidence / gap |
|---|---|---|
| Supplier comms channel (email/phone/portal/EDI/cXML/API) | ✅ **BUILT (today)** | `services/fulfillment/supplier_channel.py`; `supplier_channel_resolved` on the journey; phone/portal → human-only |
| Blind-ship / don't disclose supplier to buyer | ✅ **BUILT** | `fulfillment_cases.py:78` `_BUYER_REDACT`; supplier-blind buyer summaries (`recommend_fulfillment_stage.py`) |
| Fulfillment states through delivery | ✅ **BUILT** | `domain.py` FSM → `READY_TO_SHIP / PARTIALLY_READY / COMPLETED` |
| Human email gate (no agent send) | ✅ **BUILT** | `domain.py:177` GATE 2 `HUMAN_OPERATOR`-only |
| Bitemporal audit of the whole journey | ✅ **BUILT** | `repository.py` SCD-2 `valid_from/valid_to`; per-event trace |
| ASN/GeoIP fraud on the request | ✅ **BUILT** | `procurement_fraud_signals.assess_redraft_abuse`; `geoip.py` |
| **Carrier tracking + delivery status** | ❌ **MISSING** | no carrier connector (FedEx/UPS/DHL/AusPost/EasyPost/AfterShip); states exist but no live tracking → **Track 3** |
| **Delivery-progress notification to all stakeholders** | ⚠️ **PARTIAL** | `fulfillment/notifications.py` `notify()` + outbound queue exist, but no per-milestone × per-stakeholder matrix (buyer/operator/supplier/AP/3PL) |
| **Returns / RMA + CV return-fraud** | ⚠️ **PARTIAL** | CV return-fraud triage exists (`cv_*`); `cases` table has `issue_type`; but no RMA state flow + no payment-page return policy |
| **Return policy / FAQ surfaced at cart/payment** | ❌ **MISSING (buyer UI)** | return window / restocking / who-pays-return-shipping / EU 14-day withdrawal not surfaced pre-payment |
| **Verified-payment gate before supplier email** | ❌ **MISSING** | GATE 1 is buyer *commitment*, not captured funds; needs Stripe (Track 3) |

**Returns fraud taxonomy** (to design the returns flow): wardrobing (use+return), empty-box/switch fraud,
bracketing (order many/return most), item-not-received (INR) fraud, friendly-fraud chargebacks. The
legit-mistake-vs-fraud call needs signals (return rate, account age, value, **CV inspection of the returned
item** — which ShopSquire's CV triage already does). Surfacing the policy pre-payment reduces disputes and
is often legally required (EU consumer rights).

---

## 3. Why this is a moat, not a "2-day vibe-coded toy"

**The toy critique does not survive contact with the code.** Vibe-code does not produce:
- a **pure, actor-guarded state machine** with named gates (`domain.py`) that makes "no agent may send" a
  compile-time property, not a hope;
- **bitemporal append-only audit by construction** (SCD-2) — the kind auditors and the EU AI Act (Art. 12
  record-keeping, Art. 14 human oversight) require;
- **agnostic-core discipline enforced by ratchets** (`test_no_flavour_in_core`, `test_no_silent_except_in_core`)
  — a governance most teams never add;
- a **supplier-safety claim cage** that stops an LLM leaking price/PO/URL/foreign-email into a supplier email
  (`draft.py:105-127`) — a genuine agentic-AI-safety innovation against prompt-injection;
- **multi-guarded autonomous send** (confidence floor + $5k/qty-25 caps + kill switch + allowlist+KYV),
  default-OFF;
- ASN/GeoIP fraud + redraft-abuse gate; a full **GDPR privacy router** (consent/export/delete/opt-out).

200+ services, tests, ratchets, and a multi-agent code review this session that found and fixed **real**
bugs. This is a system, not a weekend hack.

**The risk is PERCEPTION, not substance.** From the outside it can look like a demo because it runs on
localhost, uses synthetic data, has no real connectors, and has some UI roughness. Closing that gap:
1. **Make the invisible sophistication visible** — the decision-trace Procurement tab + journey + the new
   channel routing already do this; put them front-and-centre in the demo.
2. **A crisp, recorded clickthrough** (Playwright) showing agents propose → human gate → audit → a buyer
   mind-change superseding — undeniable "it's agentic + governed".
3. **ONE real connector flips it from "demo" to "product."** The single highest-leverage move: a real
   **shipping-tracking** integration (AfterShip/EasyPost/AusPost) *or* a real **EDI 850/856**. Live tracking
   or a real PO landing in a supplier system is the moment skeptics stop saying "toy".

### The 5 defensible differentiators (vs the field)
1. **Governed autonomy ladder** — AI proposes → policy authorizes → human/agent executes under caps → audit
   records. (Shopify/Magento don't automate procurement; CrewAI/Agentforce automate *without* this governance.)
2. **Bitemporal audit-by-construction** — court-defensible, EU-AI-Act-aligned. (Coupa/Ariba log, but aren't
   AI-native or storefront-integrated.)
3. **Supplier-safety claim cage** — anti-prompt-injection for outbound supplier comms. Nobody else has this.
4. **Shift-left security in the commerce pipeline** — CV fraud, steg/QR, ASN/GeoIP, redraft-abuse inline.
5. **Channel-aware supplier routing** (email/phone-human/EDI/cXML/API) — real B2B depth, not "send an email".

The unoccupied quadrant: **AI-native + high security + high commerce depth + governed autonomy + audit**.
That is the moat.

---

## 4. Roadmap (prioritized, file:line)

**Tier 1 — demo-critical, no secrets (do next):**
1. **Procurement Playwright E2E** (`frontend/e2e/`) — bulk query → sourcing card → confirm → Decision-Trace
   Procurement tab shows channel + supplier-selection + a mind-change supersede. The recorded proof.
2. **Surface channel routing on the 3001 operator page** — `src/frontend/admin-react/src/components/ProcurementCases.tsx`
   render `supplier_channel_resolved` (channel · human-only · integration) next to each case's supplier.
3. **Return-policy / FAQ card at the cart/payment step** — new `frontend/src/components/ReturnPolicyNotice.tsx`
   rendered in `App.tsx` cart panel; reads a policy from `StoreProfile` (agnostic).
4. **Stakeholder-notification milestone matrix** — extend `services/fulfillment/notifications.py` to fan
   `case_opened / committed / quote_sent / shipped / delivered / rma_opened` to buyer/operator/supplier
   channels (templated, buyer copy stays supplier-blind).
5. **Returns/RMA state flow** — add `RMA_REQUESTED → RMA_APPROVED → RETURN_IN_TRANSIT → REFUNDED` edges to
   `domain.py`, gated + CV-inspection-linked; wire the existing CV return-fraud triage as the approve signal.

**Tier 2 — one connector flips perception (highest leverage):**
6. **Shipping-tracking connector** (`services/fulfillment/shipping_providers.py` — the interface already
   exists as an abstraction) → AfterShip/EasyPost/AusPost; emit `shipment_tracking_updated` to the journey.
7. **Payment-captured gate before GATE 2** — Stripe; a `payment_captured` precondition so the story becomes
   "paid → human approves → send" (needs the Stripe secret).

**Tier 3 — gated on secrets/partners:** real SMTP/IMAP (Gmail App Password), EDI/cXML connectors, catalog/
inventory (Shopify/Magento), SSO, ERP.

**UI/UX polish (parallel, cheap):**
- Decision-Trace Procurement tab: group by supplier + a small channel icon (📧/📞/🔌) per row.
- Cart: qty×unit line already done; add a "sourced — ships from partner" chip (blind, no supplier name).
- 3001: a "how we'll reach this supplier" chip on each case; a delivery-progress stepper once tracking lands.
- Buyer chat: the multi-intent confirmation card (done) — add a one-line "N in stock, X sourced (ships from a partner)".

**The single most valuable next step:** the Tier-1 Playwright procurement E2E *plus* one Tier-2 shipping
connector — together they turn "impressive demo" into "this is a real product with real supplier + carrier
integration and a court-grade audit trail."
