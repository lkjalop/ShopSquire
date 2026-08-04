# ShopSquire — Positioning, Running Cost, Security & Market-Intelligence (2026-06-28)

Strategic read of where ShopSquire stands **after this session's work** (choice-lanes, work-fleet ranking
truth, evidence-grounded narration, real-catalog seed, RFQ fan-out). Companion to the measured
model-eval/cost doc (`SHOPSQUIRE_MODEL_EVAL_COST_AND_COMPETITIVE_2026-06-28.md`). Grounded in the actual
codebase: ~127 security modules, 11 market-intel detectors, deterministic core + local-LLM narration.

---

## 1. What ShopSquire IS (one line)
An **intelligence + shift-left-security + bounded-autonomy LAYER** that sits ON TOP of existing commerce
infrastructure (Shopify/Magento catalog, Stripe payments, NetSuite/ERP inventory) — deterministic
decisioning with a thin, caged local LLM for narration. It is **not** a storefront/payments/CRM
replacement, and shouldn't try to be.

## 2. Comparison vs other platforms

| Capability | ShopSquire | Shopify (Magic/Sidekick) | Salesforce Agentforce | Sierra / Rep AI (commerce agents) | CrewAI / LangChain | Gorgias / Zendesk AI |
|---|---|---|---|---|---|---|
| Recommendation decisioning | **Deterministic ranker + profile choice-lanes + evidence** | Search/keyword + hosted LLM | LLM-agentic | LLM chat-led | DIY LLM loops | n/a |
| LLM role | **Narration only, caged + grounded** | Generative features | Agent reasoning (decisions) | Agent reasoning | Agent reasoning | Reply drafting |
| Cost model | **~Flat (self-host, $0/token)** | Bundled/usage | **Per-conversation** | Per-resolution/seat | **Many paid API calls** | Per-seat/resolution |
| Auditability | **Bitemporal decision trace (replayable)** | Opaque | Limited | Limited | Hard | Limited |
| Procurement | **Bounded-autonomy buyer→supplier (gates, RFQ fan-out, OKF audit)** | — | Flow/agent | — | — | — |
| Shift-left security | **In-pipeline (fraud, CV triage, prompt-injection cage, BEC/KYV, steg)** | Platform-level | Trust layer | Basic | DIY | Basic |
| Market intelligence | **11 detectors + governed shadow actions + experiment/attribution loop** | Dashboards | CRM analytics | Conversation analytics | — | Ticket analytics |
| Portability | **Vertical-agnostic profiles (electronics→pharmacy by config)** | Shopify-locked | Salesforce-locked | Hosted | DIY | Hosted |

**The unoccupied quadrant ShopSquire owns:** *high commerce-domain depth × high security depth × auditable
deterministic decisioning × near-zero marginal LLM cost.* No single competitor sits there — commerce AI
agents are LLM-led (costly, non-deterministic); security vendors don't do merchandising; BI tools stop at
dashboards.

## 3. Running costs

**Marginal (per-query):** ~**$0 in LLM tokens** — all inference is local Ollama; a typical recommend is
**one narration call (~5s warm)**; everything that *decides* is deterministic. This is the structural edge
vs per-conversation/per-call agentic billing (e.g., $X/conversation × volume grows linearly; ShopSquire
stays ~flat).

**Fixed (hosting):** two tiers —
- **Minimal runtime** (what a recommend actually needs): `api` + `postgres(pgvector)` + `redis` + **one
  GPU box for Ollama**. GPU VRAM driver: `qwen2.5:14b` (9GB) + `qwen2.5vl:7b` vision (6GB) + `nomic-embed`
  (0.3GB) → comfortably one **16–24GB GPU** (e.g., a single A10/L4/4090-class). Cloud ≈ a few $/hr; on-prem
  ≈ one-time. CPU-only works but narration drops from ~5s to ~30s.
- **Full platform** (`docker-compose.yml`): also `neo4j` (fraud-ring graph), `prometheus`+`alertmanager`+
  `grafana` (observability), `celery worker`+`beat`, `sync-worker`, `crowdstrike-poll`, `syslog-listener`,
  `graph-refresh`, `db-backup`. These are **optional/feature-gated** — run them only for the security/graph/
  observability features. Each adds memory + ops surface.

**Cost takeaway:** lead with **flat marginal cost + self-hostable** (data-sovereign, no per-token vendor
lock-in). The trade is you must host a GPU and (for the full feature set) operate a multi-service stack —
so the cost story is *"predictable infra, not metered AI."*

## 4. Security — posture & concerns

**Strengths (real today):** ~127 security modules; shift-left controls *inside* the commerce pipeline —
prompt-injection cage + `jailbreak_embedding_guard` + `prompt_injection_eval`, supplier-email `bec_kill_chain`
+ `semantic_bec_scorer` + `kyv_registry`, `commerce_request_guard`, fraud scorer (26+ signals), CV triage
(steg/adversarial-image/QR), `refund_window_guard`, the supplier **send-cage** (claim-safety, proven to
reject unsafe LLM rewrites), and a **bitemporal audit trace**. The LLM is caged ("AI proposes, policy
authorizes, automation executes, audit records").

**Concerns / things to harden before production:**
1. **Admin MFA is flag-OFF by default** (`ADMIN_MFA_ENABLED=0`). The middleware exists — **enable + enforce**
   for any real send/PO-execution/admin path (this is the PCI #5 item).
2. **Secrets management for real connectors** — live Shopify/Magento/SMTP/ERP/competitor feeds need API keys;
   today's sandboxes avoid it. Add a vault/secret-store boundary before wiring real transports.
3. **Local-LLM supply chain** — pin model digests + source; a swapped Ollama model is an integrity risk.
4. **Self-host attack surface** — the full stack (neo4j, grafana, pollers) widens it; keep feature-gated
   services off unless used, and network-segment them.
5. **Prompt-injection via product/supplier content** — largely caged (image-as-data boundary, send-cage),
   but every new free-text ingestion path must route through the existing guards (don't bypass).
6. **Multi-tenant isolation** — verify per-tenant data/engine isolation as you scale beyond single-tenant.

Net: security is a **differentiator**, not a liability — but flip on MFA, add secrets handling, and pin
models before a production/customer deployment.

## 5. Gaps — build vs integrate vs defer (so ShopSquire stays good at what it's good at)

**BUILD / own (the moat — keep making these best-in-class):**
- Deterministic ranking + **profile choice-lanes** + **evidence-grounded narration** (this session).
- **Bitemporal decision audit** + the **LLM cage** + claim-safety.
- **Bounded-autonomy procurement** (gates, RFQ fan-out, quote-compare, OKF).
- **Shift-left commerce security** (fraud/CV/BEC/prompt-injection).
- **Market-intel detectors + governed action loop**.

**INTEGRATE / don't rebuild (connect to mature systems):**
- Payments → **Stripe/Adyen** (never build a PSP). Storefront/catalog → **Shopify/Magento adapters**
  (already present). Inventory/ERP → **NetSuite/SAP connectors** (scaffolded). Email transport →
  **SMTP/Microsoft Graph**. Exec dashboards/BI viz → **Grafana/Metabase/PowerBI** (Grafana already in-stack).
  CRM → **Salesforce/HubSpot**. Vector/search → **pgvector** (already). Auth/SSO → **an IdP (OIDC)** rather
  than home-grown.
- Principle: ShopSquire is the **decision/intelligence/security brain**; it should *orchestrate* commodity
  infra, not reimplement it.

**DEFER / mature later (gated on data, creds, or sign-off):**
- Trained ML classifiers + forecasting (today: deterministic detectors — good enough, upgrade with data).
- GNN fraud-ring detection (Neo4j is in-stack; wire when fraud volume justifies).
- Real external connectors (competitor prices, reviews, ad platforms) — the market-intel connector gap.
- Module-5 execution bridge (shadow → real action) — **needs autonomy sign-off**.

## 6. Market intelligence — where it stands & how to make it actionable

**What ShopSquire has (real, deterministic, governed):**
- **11 detectors** (`market_analysis.py`): demand_shift, conversion_anomaly, inventory_demand_mismatch,
  demand_forecast, seasonal_demand, competitor_undercut, objection_cluster, funnel_dropoff, segment_shift,
  channel_performance, bundle_opportunity.
- **Signal warehouse** (Module-2: rollup + retention, this session), **shadow actions** (governed log-only
  proposals), **experiment console** (promote/evaluate/**auto-rollback** with anti-Goodhart guardrails),
  **attribution** (decision→conversion), **campaign/contact governance** (consent + frequency caps).

**vs other BI/market tools:** Shopify Analytics, Triple Whale, Glew, Looker — these are **descriptive
dashboards** (what happened). ShopSquire is **detective + prescriptive + a governed closed loop**:
*sense (detectors) → propose (shadow action) → experiment (A/B with auto-rollback) → measure (attribution)
→ govern (consent/audit)*. That loop with **auditability** is the differentiator; most stop at the chart.

**The gaps that hold market-intel back from "mature, actionable" (in priority order):**
1. **External connectors** — the internal signals (orders/conversion/returns/search) are real, but
   competitor-price, reviews, ad-spend, and support-ticket signals are **fed externally with no canonical
   table to scan** (confirmed in `market_signal_adapters`). Real connectors = the #1 unlock for breadth.
2. **Exec-facing BI surface** — findings/attribution exist as data + an operator console, but there's no
   polished owner dashboard. **Integrate into the in-stack Grafana** (or Metabase) for charts + a
   contact-frequency-ledger view + shadow-actions-pending view.
3. **Shadow → execution bridge (Module-5)** — proposals are visible but not actioned; gated on sign-off.
4. **Causal depth + trained forecasting** — upgrade detectors with trained models once enough signal
   history accrues (the warehouse now retains it).

**Recommended integration path for "better business intelligence + actionable intel":**
- Pipe `decision_outcome` + `attribution_event` + active findings into **Grafana dashboards** (already
  running) → exec gets live "what's happening + what we did + did it work."
- Add **connectors** for competitor/review/ad/support signals → the detectors light up with external context.
- Promote validated **shadow actions** to governed execution (behind approval + experiment + kill-switch).
- Keep the **closed-loop + audit** as the headline — that's what makes the intel *trustworthy and
  actionable*, not just another dashboard.

---

## TL;DR
- **Compare:** ShopSquire owns the unoccupied "deterministic + auditable + secure + cheap" commerce-AI
  quadrant; competitors are either LLM-led-and-metered, security-only, or dashboard-only.
- **Cost:** ~$0/token marginal (local LLM, deterministic core); fixed cost is a GPU box + (optionally) a
  multi-service stack. Predictable infra, not metered AI.
- **Security:** strong shift-left differentiator; **enable MFA, add secrets handling, pin models** before prod.
- **Gaps:** keep building the decision/security/procurement/market-intel moat; **integrate** payments/
  catalog/ERP/BI-viz/CRM rather than rebuild; defer trained ML + Module-5 execution until data/sign-off.
- **Market-intel:** strongest as a **governed closed loop** (sense→propose→experiment→measure→govern);
  unlock it with **external connectors + a Grafana exec surface + the gated execution bridge.**
