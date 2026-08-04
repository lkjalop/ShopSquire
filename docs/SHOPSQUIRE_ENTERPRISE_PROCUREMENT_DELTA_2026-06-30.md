# ShopSquire — Enterprise / Production-Grade Procurement Delta

**Date:** 2026-06-30
**Question:** what's the gap between our governed-autonomy procurement assistant and enterprise/production-grade procurement — more gates, faster + more reliable communications — and what do real e-commerce/retail companies actually do?

---

## 1. What real companies do for procurement (the P2P landscape)

Mid-to-large e-commerce/retail run **Procure-to-Pay (P2P)** on suites like **Coupa, SAP Ariba, Oracle Procurement Cloud, Ivalua, Jaggaer, GEP**. The standard flow:

```
Demand/replenishment → Sourcing (RFQ/RFP/reverse auction) → Supplier selection →
PO (multi-level approval) → PO acknowledgement → Goods receipt (ASN) →
Invoice → 3-way match (PO=receipt=invoice) → Payment (terms / early-pay discount) → Spend analytics
```

The non-negotiable enterprise mechanics:
- **Structured supplier channels** — **EDI** (X12: 850 PO · 855 PO-ack · 856 ASN · 810 invoice · 997 ack) and/or **cXML punchout** to supplier catalogs — *not* email. Email is the SMB tier.
- **Multi-level, threshold-based approvals** + **segregation of duties** (creator ≠ approver ≠ receiver) + **budget checks**.
- **3-way match** before payment (the core AP control).
- **Supplier lifecycle** — onboarding, KYV/KYC, sanctions/credit screening, performance scorecards, risk monitoring, **dual control on bank-detail changes** (anti-BEC).
- **Contract/price-agreement compliance** — a PO must reference a valid contract; off-contract = "maverick spend" flagged.
- **ERP/AP integration** (NetSuite/SAP/Oracle/Dynamics), tax/duty, SOX audit.
- **Replenishment intelligence** — reorder points, safety stock, demand forecasting (MRP).

---

## 2. Where ShopSquire sits (and what's genuinely differentiated)

ShopSquire is **not** a P2P suite replacement — it's the **AI intelligence + governed-autonomy layer** that classic suites lack:
- conversational **buyer-intent → procurement** (no one types POs into Ariba from a chat),
- **inventory-shortfall → auto-sourcing** with a preview/confirm boundary,
- **bounded autonomy** with a full **decision trace** (why each step),
- **inline margin guardrails** at the send gate,
- **security-aware** intake (image/QR/steg threats).

That's the unoccupied quadrant: **high commerce-domain depth × high AI/governance depth.** The delta below is what makes it *trustworthy at enterprise scale*, not what makes it a different product.

---

## 3. The delta — what to add (organized by your three asks)

### A. More gates (the governance delta)
Today: GATE 1 (buyer commit/cart-confirm) · GATE 2 (human send) · margin gate (warn) · RFQ completeness gate · claim-safety cage · confirm-cart rate-limit. **Strong for one-supplier, low-value flows.** Enterprise needs:

| Gate | Today | Delta |
|---|---|---|
| **Multi-level approval** | single human approve→send | **threshold tiers** (e.g. <$1k auto-eligible · $1k–10k manager · >$10k director · >$100k VP+finance) on the case value |
| **Budget / spend** | none | check the requesting dept/category budget before the PO; block/escalate over-budget |
| **Segregation of duties** | actors typed (buyer/agent/operator) but one operator can do all | enforce creator ≠ approver ≠ receiver per case |
| **3-way match** | PO finalization exists | gate PAYMENT on PO = goods-receipt = invoice match |
| **Supplier risk** | KYV allowlist (binary) | sanctions/credit/risk-tier screening at onboarding + ongoing monitoring; block high-risk |
| **Contract compliance** | supplier terms per SKU | PO must reference a valid price-agreement/contract; flag off-contract (maverick) spend |
| **Dual control (bank change)** | partial (supplier_domain_guard) | two-person approval for any supplier bank/contact change (anti-BEC) |

**Highest-leverage first:** multi-level threshold approval + budget gate + 3-way match — those three are what an enterprise auditor looks for.

### B. Faster + more reliable communications (the comms delta)
Today: flag-gated **SMTP send** + **Gmail poll** inbound; sandbox by default. Email = SMB tier; works, but synchronous-ish and fragile at scale.

| Dimension | Today | Delta |
|---|---|---|
| **Channel** | email (SMTP/IMAP-poll) | add **EDI (850/855/856/810)** + **cXML punchout** + a **supplier portal**; keep email as the small-supplier fallback |
| **Delivery reliability** | best-effort send | outbound **message queue** (retry + backoff + **dead-letter**), **delivery receipts**, **idempotency keys** (partly there), **PO acknowledgement (855) tracking** |
| **Inbound** | Gmail polling | **webhooks/push** over polling; strict correlation (already content-hashed) + quarantine (already there) |
| **Speed** | poll latency | event-driven (webhook → queue → parse) instead of poll cycles; **SLA timers** on supplier response with auto-escalation |
| **Durability** | local Redis often down | **production Redis/Postgres-backed** queue + memory (today memory is session-only when Redis is absent) |

**Highest-leverage first:** the outbound **queue with retry/dead-letter + 855 acknowledgement tracking** (reliable send), then EDI/cXML for the suppliers that require it.

### C. Production reliability (the platform delta)
- **Durable memory/state:** Redis/Postgres-backed (today session memory degrades to in-process when Redis is down — confirmed in the live test). Procurement cases are already DB-durable; the *learning/session* layer needs durable backing.
- **Reconciliation:** a clean chain `order_group → cases → POs → receipts → invoices` with a reconciliation job (detect orphans/mismatches).
- **Idempotency everywhere:** confirm-cart + the idempotency middleware exist; extend to PO/payment.
- **Observability/SLA:** queue depth, send-failure, escalation-backlog, kill-switch state alerts (some metrics exist).
- **Real market feeds:** competitor-price/demand ingestion to make the shadow market-intel (A7) business-grade.

### D. Integration delta (what makes it "fit" an enterprise)
- **ERP/AP connectors** (NetSuite/SAP/Oracle/Dynamics) — PO/receipt/invoice sync.
- **EDI/cXML gateway** (a VAN or a service like SPS Commerce / TrueCommerce).
- **Tax/duty** engine for cross-border, **SOX/audit** export (the bitemporal trace + OKF export is a strong start).

---

## 4. Pragmatic delta roadmap (enterprise-credible without boiling the ocean)

**Tier 1 — governance credibility (mostly code, no new vendors):**
1. **Multi-level threshold approval** — extend the workflow with approval tiers keyed on case value (the state machine + adaptive-action gate already model authorization).
2. **Budget gate** — a per-category/dept budget check before the PO (a new gate; data is internal).
3. **3-way-match gate** on payment — PO = receipt = invoice (PO finalization exists; add receipt + match).
4. **Reliable outbound** — wrap supplier send in a queue with retry/dead-letter + **855 acknowledgement** state.

**Tier 2 — supplier + comms maturity (needs vendors/secrets):**
5. **EDI/cXML gateway** + **supplier portal** (the channel delta).
6. **KYV risk screening** (sanctions/credit) + **dual-control bank changes** + supplier scorecards.
7. **Durable Redis/Postgres** memory + reconciliation job.

**Tier 3 — intelligence + ERP (the moat):**
8. **Real market feeds** → market-intel from shadow → inform (the discount/sourcing brain).
9. **ERP/AP connectors** + tax + SOX export.
10. **Replenishment forecasting** (reorder points / safety stock / demand) → predictive sourcing.

---

## 5. The honest positioning
- **Today:** a *strong governed-autonomy procurement assistant* — demo-ready, well-tested, with the differentiated AI/governance layer (preview→confirm→RFQ→human-gate→supersession→margin→audit).
- **Enterprise-credible (Tier 1):** add the **approval tiers + budget + 3-way match + reliable queued comms** — these are the controls an enterprise auditor/procurement lead checks first, and they're mostly internal code on top of the existing state machine + gates.
- **Enterprise-grade (Tier 2/3):** EDI/cXML/portal, KYV risk, durable infra, ERP/AP, real market feeds — these need vendors, secrets, and integration work, not just code.

The platform's edge is NOT to out-feature Coupa/Ariba on POs and 3-way match — it's to be the **conversational, bounded-autonomy, fully-audited front half** that turns messy buyer intent into governed procurement work, then **hand the structured PO to the ERP**. Build Tier 1 to be trusted; integrate (Tier 2/3) to fit.
