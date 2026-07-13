# ShopSquire — V2 Ship + Pricing-Intelligence Roadmap
_Living checklist. Last updated 2026-07-13._

## The one rule (anti-circling)
> **You may not re-open a phase without a failing measurement that points at a specific line.**
> "It could be better" is not a reason to loop; a red gate is. Building feels like progress and
> validating feels like waiting — that inversion is the circle. Ship the demo, validate on labels,
> canary, retire `suggest()`. New building resumes only at Phase 4 (genuinely new scope).

Circling smells (call them out): another review cycle with no red gate; a refactor with no failing
test; a KB tweak with no holdout miss behind it; a second copy of a parser; a hardcoded number.

---

## The agnostic core (what we're shipping)
**Mechanism in code, knowledge in data. The core is vertical-blind; add a vertical with JSON, never code.**

Product side and query side meet at one currency — a **taxonomy node + `{attr: (op, value)}` predicates**:

| | Product side (classify) | Query side (understand) |
|---|---|---|
| Model does | embed → top-K nodes → pick node ID (closed vocab) | language → use-case (closed vocab) |
| Code grounds | `sells_within()`, attribute normalization | `resolve()` → capability requirements |
| Result | classified node + attributes | requirements + `derive_price_floor` from real catalog |

`fit.py` does the tri-state match (meets / unknown / fails; **unknown ≠ fail**). No regex in the decision path.

**Validation instruments (all exist):** labeled holdout (82.5% exact / 95.6% lenient) · KB-drift tests ·
shadow soak (constraint_sat, empty_rate, unauthorized_rate, classified_shown_rate) · **labeled gate
(`relevance_labels.json`, case_id:turn — USER-owned, the only blocker)** · fail-open/silent-swallow ratchets.

---

## PHASE 1 — DEMO-READY (days). Make the core visibly smart.
**The recommendation logic = capability-first → price-second → alternative → (maybe) clarify.**
The ranking spine already exists (`fit.py`: meets < unknown < fails → fewest-fails → price — capability
truth never overridden by a cheaper worse product). What's missing is the CONVERSATION intelligence:

- [x] **`derive_price_floor` in the live path** — cheapest in-catalog product that ACTUALLY meets the
      capability (drawing→$1199, Apple→$2879, no-touch→"none"). DONE (2920672, `fit.capability_floor_cents`).
- [x] **Budget × capability branch (the key smart moment)** — DONE (2920672, `core._apply_capability_budget`
      → `extras["capability"]`; budget-free probe when budget<floor; 24 tests):
  - no budget → good/better/best spread + STATE the floor ("these all do X; they start at $1199").
  - budget ≥ floor → rank meets within budget; optional "save $X and still meets" / "$Y more gets <upgrade>".
  - budget < floor → NEVER empty/junk: name the gap + offer a path (stretch / relax / closest).
- [ ] **The 3-band SHELF (`extras["shelf"]`, Phase 1b) — the right-side panel's brain, core-agnostic:**
  - **Band 1 best_fit** — top-3 answer to intent+budget (meets-in-budget, else closest-in-budget labeled honestly).
  - **Band 2 stretch/more-capable** — meets NOT in band 1. below_budget → "meets, stretch to $floor" (price asc);
    within/no-budget → "More capable" = **capability HEADROOM (exceeds requirements), NOT just pricier** (a
    pricier-same-spec brand premium does NOT belong here — that's the sharpening).
  - **Band 3 preference** — brand/variant/spec preference (Apple/Surface); OMITTED when no preference signal.
  - Rules: adaptive (empty bands omitted, never fabricated), deduped (a product in exactly one band, priority
    1>2>3), every card carries its honest fit verdict chip, banner is grounded (LLM rephrases, never invents).
  - Sourcing: within/no-budget from `resp.products` (zero extra retrieval); below_budget reuses the budget-free
    probe for the above-budget meets. Frontend renders `shelf.bands[].cards` blind (no per-vertical logic).
- [ ] **ONE clarifying question — only when it changes the answer:** ask iff variant is ambiguous AND
      variants differ materially in floor/capability; else recommend with a STATED assumption. Content-
      advisory (minor + mature game) is this pattern — surface, never block.
- [ ] **Wire FILTER / COMPARE / EXPLAIN executors** for turn 2+ (today plan = retrieve + fit_check only).
- [ ] `RECOMMEND_CORE_MODE=primary` in a demo profile + smoke the golden matrix.
- **EXIT GATE:** live demo shows (1) capability-first ranking, (2) a budget<floor tradeoff instead of an
      empty/mismatch, (3) one smart clarification, (4) a 3-turn refine. Nothing more.

## PHASE 2 — VALIDATE (gated on USER). Prove it, don't polish it.
- [ ] **USER fills `relevance_labels.json`** (case_id:turn) — the only true blocker.
- [ ] Shadow soak → baseline → label-free gates stay green + labeled gate goes green.
- **EXIT GATE:** all gates pass on labeled data. A red gate is the ONLY license to touch code, and only
      the code it points at.

## PHASE 3 — SHIP (canary ladder). Retire the old engine.
- [ ] Canary ladder (small % → ramp).
- [ ] Delete `recommend.py` / `suggest()` / chat-hop at R11 ("never fixed, only replaced").
- **EXIT GATE:** `suggest()` is gone from the tree.

---

## PHASE 4 — PRICING INTELLIGENCE EPIC (post-demo, genuinely new scope)
_This is where the retail-pricing research + supplier-pricing insight land. NOT before Phase 3._

### 4A — Sell-side typed pricing (customer-facing)
Research-validated: every serious platform (Shopify/Oracle/SAP/Salesforce) models price as typed +
effective-dated, with **promotion (temporary, reverts) ≠ clearance (permanent, SKU exiting)**.
- [ ] Type `price_book`: list/RRP · regular · promo-temporary · clearance-permanent · landed-cost · MAP ·
      competitor — each with valid-from/valid-to. Extend the bitemporal audit to price.
- [ ] Item lifecycle flag (`is_clearance` / `discontinued` + exit-date) — the single bit that lets
      recommender + BI + procurement reason correctly off shared data.
- [ ] Capture transacted price on the order line at time of sale; derive BI via point-in-time/as-of joins
      to the price event log — never re-read current `sale_cents` (that's an SCD-Type-1 overwrite = BI poison).
- [ ] Demand decomposition: baseline + promo/price uplift BEFORE procurement (guards the ~3× clearance
      over-order). Feed only cleaned baseline into reorder logic.
- [ ] (EU/ANZ) rolling ≥30-day per-SKU price history; "was" = lowest in window (Omnibus Directive).
- **Note:** `derive_price_floor` already reads the effective sale-aware price live — a clearance item
  *correctly and temporarily* lowers the floor. Hardcoded floors would have poisoned this. Already dodged.

### 4B — Buy-side supplier pricing (procurement) — the mirror of 4A
Grounded 2026-07-13. Skeleton exists; five precise gaps.
- **Exists:** quoted price captured (`parse_quote` external_comms.py:271); PO from quote
  (purchase_order.py:43); margin gate (margin_advisor.py:54); RFQ email volume-ask (draft.py:595, price-free
  cage — KEEP); admin QuotePacket + manual RfqFanout ranking.
- [ ] **Quote carries a TIER SCHEDULE, not a scalar** — `parse_quote` drops "$1,115@10 / $1,020@25" to one
      number today. Model quoted price as effective-dated, quantity-scoped (same discipline as 4A).
- [ ] **Reconcile** returned tiers against catalog `price_breaks` (supplier_catalog.py:45 — today static guesses,
      never reconciled).
- [ ] **"Redo the order"** — expected-price baseline + variance check → recompute qty / re-rank supplier /
      re-solicit. Today a high quote trips only a margin warning; no re-selection exists.
- [ ] **Post-quote email regenerates** on recompute (PO-confirmation/counter/acceptance carries agreed
      price+tier). Outbound RFQ STAYS price-free (anti-anchoring invariant).
- [ ] **Admin surfaces tiers** (SupplierDraftPacket hides `supplier_terms`/`price_breaks` it already has;
      add list-vs-quoted view + tier grid).
- [ ] **MI ingests buy-side cost** as its own signal (supplier competitiveness, bulk economics, landed-cost
      trend, quote-variance) — distinct from the sell-side `competitor` signal. Feed actual quoted/landed
      cost back to MI so procurement + market intelligence close the loop.

### 4C — Market intelligence wakes up (consumes 4A + 4B)
- [ ] Price index + margin/GMROI + promo-lift (baseline-net, cannibalization/halo/pull-forward aware).
- [ ] B2B vs B2C pricing keys kept separate (B2B: account × product × qty × contract-state, RFQ for unpriced;
      B2C: SKU × time × segment).

---

## Standing invariants (do not violate in any phase)
FULFILLMENT_SUPPLIER_TRANSPORT=sandbox · FULFILLMENT_AUTONOMOUS_RFQ=0 · human-only supplier send ·
never leak budget/target price to a supplier (anti-anchoring cage) · RECOMMEND_CORE_MODE off in prod until
gates pass · no canary / no archiving `suggest()` / no threshold-lowering until gates genuinely pass ·
Track A security/fraud/payment = fail-CLOSED.
