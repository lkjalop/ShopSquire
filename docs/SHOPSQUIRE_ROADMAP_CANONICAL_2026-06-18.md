# ShopSquire — Canonical Roadmap & Agent-Behaviour Contract (2026-06-18)

**This document supersedes the ordering in the three loose roadmap files**
(`..._CORE_ADAPTER_DATA_PLATFORM_ROADMAP_...`, `..._OPUS48_AGNOSTIC_COMMERCE_AI_ROADMAP_...`,
`..._CLAUDE_HANDOFF_DAVID_OPUS48_...`) and the A→E plan in
`SHOPSQUIRE_AGNOSTIC_CORE_DEEPDIVE_2026-06-18.md`. Those remain valid as detail; **this is the
authoritative phase order.** Verified against the tree in
`SHOPSQUIRE_REVIEW_ADJUDICATION_2026-06-18.md` (GPT-5.5 review: 10/10 claims confirmed).

## Reorder principle

**Breadth of data sources comes AFTER the core is agnostic, the taxonomy is unified, and the
consent envelope exists.** Adding a loyalty/warehouse feed (Flybuys, Everyday Rewards, Snowflake)
into today's split-brain taxonomy (F1/F2) just spreads the mess into more surfaces.

## Phase order (authoritative)

| Phase | Work | Exit bar |
|---|---|---|
| **0** | First PR: `store_profile` fail-closed (P0) + `checkout_upsell` cents fix (P2) + taxonomy characterization fixtures | P0 closed; bug fixed; the two taxonomies have a pinned parity baseline |
| **1** | **One `StoreTaxonomy`** — resolve F1 (split-brain upsell) + F2 (two taxonomies in one request path); collapse quad-source config (`store_vocab.json` + 3 use-case files + profile slot) into the profile | one product-type source; one upsell engine; one config source |
| **2** | Flavour excision P1-P4: `llm_provider` complexity keywords, `query_decomposer` spec extractors, `upsell_companions`, `cv_returns_pack` → profile slots | pharmacy profile drives complexity/specs/upsell/CV with zero electronics literal; modules added to no-flavour lint |
| **3** | **CustomerContext + consent envelope** (NEW foundational); then generalize `erp/provider_registry` → `src/app/ports/` with families: Catalog, Inventory, **CustomerContext, Loyalty, Warehouse**; loyalty/CDP/warehouse are adapters | external data enters normalized, consented, freshness-stamped; ERP connectors move under ports unchanged |
| **4** | `QueryUnderstanding` contract + evidence/why **provenance tiers** + **assumption guardrails** (see below) | every claim cites evidence+tier; under-specified queries ask or state overridable assumptions |
| **5** | `recommend.py` stage extraction (continue from checkout-handoff), vision 3-state (on/adjacent/off), CPU/GPU pool split | suggest() < 6.5k; adjacent-image handled; nano→CPU composer |

GPT-5.5's 0→7 and the A→E plan both survive inside this; the only structural change is inserting
**CustomerContext + ports at Phase 3** and forcing **taxonomy consolidation (Phase 1) ahead of
any data-source breadth.**

## Foundation: redo vs add

- **No redo of the decision spine** — `policy/execution_gate.decide()`, the fail-closed authority
  matrix, the finalizer, retrieval/RRF are sound. Do not rewrite.
- **One fix:** `store_profile` fail-closed (Phase 0).
- **Two additions (not redos):** `CustomerContext` + consent gate (missing today); generalize the
  existing `provider_registry` factory pattern into a `ports/` layer (Phase 3).

## Agent-behaviour contract (the "smarter" core — Phase 4)

### a. Evidence provenance tiers (extend CaMeL control/data → a trust ladder)

Today "retrieved/OCR/QR text = data, never instruction" is enforced for images. Generalize: every
piece of evidence an agent gathers carries a **provenance tier**. Every claim in the "why" cites
its evidence **and** its tier.

| Tier | Source | May gate a consequential action? | May be a cited "why" reason? |
|---|---|---|---|
| `user_stated` | the query itself | intent only (never bypasses safety) | yes |
| `catalog_fact` | product specs/price/stock (authoritative) | yes | yes |
| `external_operational` | ERP/inventory (real-time, freshness-stamped) | yes | yes |
| `agent_inferred` | model inference (use-case, persona) | **no** (routes to review above threshold) | yes, **labelled as inferred** |
| `external_analytical` | warehouse segment, loyalty tier, propensity (batch, stale) | **never** | ranking only, **never** the reason for a refund/price |
| `untrusted_content` | OCR/QR/email body/3rd-party text | **never** | **never** a claim source |

### b. Assumption ledger + clarification guardrail (biggest UX/safety win)

When the query is under-specified, the agent **must not silently assume.** It either **asks**
(NQE) or **states the assumption explicitly and overridably**:

> "Assuming *new*, *in-stock*, budget *~$1500* — change any of these."

First-class: `QueryUnderstanding.assumptions[] = {field, value, basis, overridable}`, surfaced in
the response **and** the decision trace. Kills the silent-assumption failure (e.g. inferring
"gaming → needs dGPU" when the user meant casual play): the assumption is visible and correctable
instead of buried in ranking.

### c. Bounded autonomy keyed to evidence tier

Extend `decide()` so permitted autonomy depends on **both** the authority matrix **and** the
triggering evidence tier. An action triggered by `agent_inferred` or `external_analytical`
evidence above a value threshold cannot auto-execute — it routes to human review. "Restock email"
auto-sends on `external_operational` stock data; a discount triggered by a stale
`external_analytical` propensity score is gated.

### Unifying invariant

**Provenance flows with evidence → trust tier bounds what an action may rest on → assumptions are
explicit and overridable → the deterministic gate is the only thing that acts.**

## External data: the latency/trust rule (Phase 3 design)

Every source (SAP, Snowflake, Databricks, Cassandra, Flybuys, Everyday Rewards, Segment,
mParticle, 3rd-party supplier) is classified once, on entry, by latency + trust:

- **Operational** (real-time, decision-grade): inventory, price, orders → `external_operational`,
  may gate. SAP/NetSuite via existing ERP connectors; Cassandra if it's the operational store.
- **Analytical/enrichment** (batch, advisory-only): warehouse segments, loyalty tier, propensity →
  `external_analytical`, informs ranking, **never** gates a money/stock/refund decision.
- **Untrusted** (3rd-party/free text): → `untrusted_content`, data only.

Do not build connectors speculatively. Build the **port + one reference adapter**, prove agnostic
with a **second** (the electronics+pharmacy discipline). Core sees normalized
`LoyaltyTier=gold, freshness=18h, consent=[personalization]` — never the vendor schema.
