# ShopSquire — The Sell Engine, Consumer-Behaviour Coverage & the Autonomy Ladder

**Date:** 2026-06-29
**Status:** Design + governance frame for the next sequence (margin-aware selling → market-intel → flake handling).
**Decided with the owner:** build it "sequentially, governable, safe-first."

---

## 0. The governing principle — the Autonomy Ladder

Trust is not a feeling; it is a function of three axes. An action may be automated to the degree it is
**reversible**, **low value-at-risk**, and **high confidence**. The ladder (and where today's line sits):

| Rung | Criteria | Examples | Status |
|---|---|---|---|
| **A — Auto (analysis/prepare)** | reversible, $0 at risk | preview/redraft, re-route, supplier ranking, **margin + discount-headroom computation**, substitute/ETA suggestions, market signals, abandoned-cart nudge | safe to automate now |
| **B — Auto-bounded (act, claim-safe)** | reversible-ish, bounded, kill-switch | buyer status replies, **autonomous RFQ send** (non-binding, no price/PO) | flag-gated — *today's edge* |
| **C — Human-only (commit)** | irreversible OR value-bearing | PO approval, quote validation, the supplier external send, the cancellation send, **applying a price/discount below floor** | human, always (for now) |

**The rule that makes the sell engine safe:** an agent may *compute and propose* a discount (rung A — pure
math, reversible, $0). A human *approves applying* it (rung C). You slide an item from C→B→A only as audit +
confidence accumulate; the kill-switch + bitemporal trace are what make sliding safe.

---

## 1. Consumer-behaviour permutation map (what a real buyer does)

The platform must keep the buyer moving toward a sale across every branch — and degrade gracefully (not
dead-end) when it can't.

| Buyer behaviour | Need | Coverage today |
|---|---|---|
| **Flakes / abandons** the preview | TTL + follow-up nudge / save-for-later | ❌ ephemeral preview, no nudge |
| **Negotiates price** ("can you do better?") | offer a discount within the margin floor | ⚠️ headroom computed, never offered → **sell engine** |
| Gives a **target price** that breaks the floor | counter-offer or graceful decline | ❌ → **sell engine** |
| Changes **product** / **quantity** | re-route + redraft / supersede | ✅ supersession (pre + post-send) |
| **Partial**: in-stock now, source the rest | split fulfilment | ⚠️ sources shortfall; no "ship now + source rest" |
| Wants it **faster** (lead-time vs price) | decision-framed tradeoff | ⚠️ alternatives exist, not framed |
| **Comparison shops** | substitutes | ✅ |
| Goes **cold then returns** | resume a prior request | ❌ no buyer "my sourcing requests" |
| Wants a **human** | escalation | ✅ |
| **Over-orders then regrets** | cancel pre/post-send | ✅ supersession |
| **Abusive churn** (recon/DoS) | rate-limit + fraud scoring | ✅ |

**The four highest-value gaps:** (1) negotiation/discount-to-close, (2) target-price counter-offer,
(3) flake follow-up, (4) buyer-facing "my requests".

---

## 2. The margin-aware sell engine (Phase 1 — build now, safe-first)

**What exists:** `fulfillment/economics.py` already computes supplier wholesale, retail, gross profit,
margin %, **floor margin**, **max buyer discount that still clears the floor**, profit-after-discount, and
`clears_floor`. It is pre-send capable (catalog-wholesale fallback when there is no live quote). Historical
supplier price (`last_invoice_cents`) is on the draft evidence.

**The gap:** that data is a button the operator clicks, not presented **at the send-approval moment**, and
**margin is not a gate** — nothing flags "this reorder isn't worth it" before a human sends.

**Build (rung A compute + rung C commit):**
1. `economics.from_case` — make the quantity pre-send-capable (read the draft scope / availability shortfall,
   not only the PO/selection) so margin is real at AWAITING_APPROVAL.
2. NEW `fulfillment/margin_advisor.py` (agnostic CORE): `assess(case)` → `{economics, verdict
   (healthy|thin|below_floor), recommended_buyer_discount_cents (leaves a buffer above floor),
   max_buyer_discount_cents, rationale}`. Pure analysis — rung A.
3. Surface at the gate: include the margin verdict in the operator case view at send-decision states, and
   `GET /cases/{id}/margin-advice`. The admin sees margin + historical price + discount headroom **before**
   approving the supplier send.
4. Governable warning (not a hard block by default): `FULFILLMENT_MARGIN_GATE` — `warn` (default) surfaces a
   below-floor warning the human can override; `block` (opt-in) requires an explicit override to send.
5. Discount-to-buyer: the recommended discount is *computed + proposed*; **applying** it to a buyer offer is a
   separate human-approved action (or a bounded rule: auto-approve discounts that still clear floor + buffer).

**Why safe:** no external action, no auto-commit. The supplier send stays GATE 2 (human). The agent only makes
the human's decision *informed*.

---

## 3. Market intelligence (Phase 2 — wire the dormant brain)

**Status:** richly built but **dormant** — `hippograph`, `market_signal`, `market_analysis`, `market_pipeline`,
`market_outcome`, `market_replay`, `market_intelligence_agent` all exist, but gated OFF
(`HIPPOGRAPH_FEEDBACK_ENABLED=False`). It produces nothing live today.

**The leap:** feed market signals into the **margin/discount decision**, not just a dashboard:
- demand high / stock tight → hold the discount (less needed to close);
- competitor cheaper / conversion dropping → discount to win (still clearing floor);
- demand peak timing → urgency framing in the offer.

**Governable rollout:** enable in *shadow* first (compute signals, log, don't act) → then let signals *inform*
the rung-A discount recommendation → never let them auto-*apply* a below-floor price (stays rung C).

---

## 4. Flake handling (Phase 3)

- Abandoned-preview TTL + a single follow-up nudge / **save-for-later** (the preview is ephemeral today).
- Buyer-facing **"my sourcing requests"** so a buyer who went cold can resume the exact prior preview/case.
- Both are rung A/B (reversible, low risk); the nudge send is claim-safe (no price/PO), like the status reply.

---

## 5. The governable sequence

1. **Sell engine** (this doc §2) — rung-A margin compute + rung-C human approve. Highest value, safest, rides
   existing economics. ← build first.
2. **Market-intel wiring** (§3) — shadow → inform → (never auto-apply below floor).
3. **Flake handling** (§4) — TTL/nudge/save-for-later + buyer "my requests".
4. Then revisit the ladder: which rung-C items have earned enough audit to move to rung B (e.g. auto-approve a
   discount that clears floor + buffer; auto-send the post-send cancellation notice).

Each phase ships independently, is bitemporally traced, and keeps the two gates (cart-confirm = GATE 1,
human send = GATE 2) intact.
