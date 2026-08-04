# ShopSquire — Comprehensive Breakdown (clickthrough/Playwright · market-intel · roadmap · excise/extract · agnostic-core · cacheRAG/context)

**Date:** 2026-06-30
**Purpose:** One document answering: the browser clickthrough + Playwright e2e, what market intelligence we need, what's left of the roadmap, what to excise/extract, how to keep core agnostic, and what to do with cacheRAG + conversation context.

---

## 1. Browser clickthrough + Playwright e2e

### 1a. Manual clickthrough (what to ascertain) — already written
`docs/SHOPSQUIRE_RECENT_CHANGES_CLICKTHROUGH_2026-06-30.md` — 13 permutations (P1–P13), each *Do → Confirm → Verifies(commit) → Blocked-by*. Critical first test = **P1 chat renders (no NotSameOrigin)**. New things to confirm = **P5 continuity** + **P7 margin-at-gate**.

### 1b. Playwright e2e — what exists vs what's needed
- **Exists:** a real harness — `tests/e2e/test_procurement_journey_playwright.py` (API-driven via `requests` + an optional browser render check), plus storefront/cv/returns e2e. Gated by `GATE_PROCUREMENT=1`; **skips cleanly** when Playwright/stack/env absent (safe in unit CI).
- **Gap:** it covers the **OLD eager flow** (query → case opens immediately). It does NOT exercise the **fluid** flow (sourcing preview → confirm-cart → grouped cases → amend → supersede → margin advice).
- **Done this pass:** added `test_fluid_sourcing_journey_api()` — drives confirm-cart → grouped cases → amend_required → supersede → operator margin-advice, asserting the recent changes end-to-end against a live stack (skips when the stack is down).
- **To run the live e2e:** `pip install playwright && playwright install chromium`; start the stack with `FULFILLMENT_DEFER_TO_CART=1 FULFILLMENT_CASES_ENABLED=1 COMMERCE_CATALOG_ENABLED=1`; then `GATE_PROCUREMENT=1 BACKEND_SMOKE_URL=http://127.0.0.1:8080 python -m pytest tests/e2e/test_procurement_journey_playwright.py`.
- **What the e2e ASCERTAINS:** the governed journey + the fluid journey produce the right states/cases/margin; the *browser render* (CORP, chat panel, sourcing card) is the part only a human (P1) or a full Playwright browser session confirms.

**Recommendation:** keep the deterministic backend suites (213 fulfillment tests) as the source of truth; use the e2e/Playwright as a **live acceptance gate** before a demo, not in unit CI (Playwright isn't a default dep — intentional).

---

## 2. Market intelligence — what we have, what we need

### What EXISTS (dormant)
- `market_signal.py` — a typed signal store: `signal_type ∈ {demand, conversion, support_objection, competitor, …}`, `source`, `trust_score`, opaque `payload_json`, dedup + bitemporal. Vertical-blind.
- `market_intelligence_agent.py:gather_market_context` — gathers hippograph insights + market findings.
- Wired into `recommend_intelligence_stage` but **flag-gated OFF** (`HIPPOGRAPH_FEEDBACK_ENABLED=False`). Produces nothing live today.

### What we NEED (for a procurement/commerce platform), in priority order
1. **Demand signals** → *when to source + urgency framing.* "Demand peaks Tuesday" → time the RFQ / hold the discount. (Partly present as hippograph insights.)
2. **Competitor price** → *discount-to-win.* Feeds the margin/discount engine: "competitor is cheaper → discount to the floor to win." **This is the highest-value new signal** — it turns the sell engine from reactive to competitive.
3. **Supplier risk/performance** → *which supplier, what lead time.* On-time rate, price trend, reliability. (Partly in `supplier_terms` + supplier history; needs a trend signal.)
4. **Stockout / inventory trend** → *predictive sourcing.* Source before the shortfall, not after.
5. **Conversion / objection signals** → *what blocks the sale.* "Buyers drop at price X" → adjust the offer.

### The leap (the real product value)
Wire market signals **into the margin/discount decision** (the sell engine), not a dashboard:
- demand high / stock tight → **hold** the discount;
- competitor cheaper / conversion dropping → **discount to win** (still clearing floor);
- supplier price trending up → source now / re-route.

### Governed rollout (per the autonomy ladder)
**shadow** (compute + log, don't act) → **inform** (signals adjust the rung-A discount *recommendation*) → **never auto-apply** a below-floor price (stays rung-C human). Enable `HIPPOGRAPH_FEEDBACK_ENABLED` in shadow first.

---

## 3. What's left of the roadmap

From `docs/SHOPSQUIRE_MASTER_EXECUTION_ROADMAP_2026-06-30.md`, with this session's progress:

- **Phase 0 (correctness)** ✅ done (N+1 batch, cache fingerprint; time.sleep verified non-issue).
- **Phase 1 (continuity)** ✅ done (last_sourcing_intent persisted + preamble) — *browser-confirm pending (P5).*
- **Live-test fixes** ✅ done (#2 requirements carry-forward, #4 demo economics, #3 verified). **#1 = config** (`RECOMMEND_NARRATION_MODE=async`).
- **Phase 2 (hygiene/excise)** ⏳ next — §4 below.
- **Phase 3 (verify)** ⏳ your browser (P1–P13) + the e2e gate.
- **Phase 4 (integrate)** ⏳ secrets: real prices, SMTP, KYV, Stripe.
- **Phase 5 (autonomy)** ⏳ dry-run then enable.
- **Phase 6 (architecture)** ⏳ `suggest()` stage-pipeline, split `recommendations.py`, promote/remove V2, market-intel ON (§2).

---

## 4. Excise / extract (Phase 2 — collapse duplication)

| Extract into | Collapses | Sites | Note |
|---|---|---|---|
| `services/redis_factory.create_redis_client()` | Redis construction | 6 (deps + 5 services + rq_queue) | timeouts already unified this session |
| `services/price_conversion.py` (`cents_to_dollars`/`dollars_to_cents`) | price↔cents | 50+ | ends the rounding bug class (the BAG bug) |
| `feature_flags.get_flags()` everywhere | flag loads | 12+ (`decisions.py` 12× alone) | + the 3 `_truthy` copies |
| (remove) | orphaned `CAG_CONTEXT_ENABLED` / `DYNAMIC_CONTEXT_PROVIDER_ENABLED` / `GRAPH_RAG_ENABLED` | config-only | dead config = misleading |
| **architecture:** `suggest()` → stage-pipeline | a ~11.7k-line monolith | 1 | intent-based stage skipping |
| **architecture:** split `recommendations.py` (104KB) | scoring/filtering | 1 | extract the hot functions |

**Order:** price_conversion + redis_factory first (bug-class + the 6 sites I just touched), then flag consolidation, then the architecture splits.

---

## 5. How to ensure things are agnostic-core

The discipline is **enforced by ratchets**, not vibes:

- **`tests/test_no_flavour_in_core.py`** — `_CORE_MODULES` must contain ZERO product/electronics vocabulary (a deliberately specific regex: rtx/macbook/240hz/…). Vocabulary lives in `config/store_profiles/*.json` (StoreProfile); core matches **opaque data** against profile rules. A **pending-excision** list records decision-path modules with known transitional flavour — the count may only go DOWN; at 0 a module graduates into `_CORE_MODULES`.
- **`tests/test_no_silent_except_in_core.py`** — core modules may not grow bare `except: pass/continue`; failures must route through a logger or `record_partial_failure` (visible in the decision trace). *(Caught me twice this session — correctly.)*
- **`tests/test_no_untimed_outbound_http.py`** — no outbound HTTP without a timeout.

**The recipe for any new feature:** put the vocabulary in the StoreProfile; make core operate on opaque `{item_ref, qty, domain, kind}`; graduate the new module into `_CORE_MODULES` once it's vocabulary-free; keep all three ratchets green. The fluid-procurement modules (`cart_commitment`, `supplier_events`, `notifications`, `margin_advisor`, `order_split`) all did this.

---

## 6. CacheRAG + keeping conversation relevant in context

### CacheRAG — current truth (verified, not the agent's overstatement)
- The semantic cache holds **only the LLM narration TEXT** (keyed embedding of `query|budget_max|use_case|top_3_skus|order_quantity`), TTL 4h, two-tier Redis+local. A hit returns prose from the summarization helper — it does **NOT** short-circuit `suggest()`, so procurement fields (`sourcing_intent`/`order_group`/`fulfillment_case`) recompute **fresh** every request (NOT lost on a cache hit).
- **Done this session (`40b2082`):** added `order_quantity` to the fingerprint → a bulk query can't reuse a single-unit query's prose (the prose↔card mismatch). This closes the real risk.
- **Remaining cache hygiene:** remove (or wire) the orphaned `CAG_CONTEXT_ENABLED`/`DYNAMIC_CONTEXT_PROVIDER_ENABLED`/`GRAPH_RAG_ENABLED` flags — they imply a RAG-context cache that doesn't exist.
- **Optional precision:** also add `sourcing_intent.mode` to the fingerprint (if the procurement stage runs before the narration cache check) — `order_quantity` already covers the bulk case, so this is belt-and-suspenders.

### Keeping the conversation relevant in context
The session memory (4-layer Redis) already grounds narration in: last ~8 messages, NQE asked/answered state (BUG-1 fixed), confirmed slots, and — new this session — **`last_sourcing_intent`** injected into the LLM preamble ("for your N-unit sourcing request…"). To make it *reliably* relevant:
1. **Verify follow-up resolution in the browser (P5):** "cheaper?" / "change it to 10" / "different supplier" should resolve against `last_sourcing_intent`. If it doesn't, the fix is prompt-side (strengthen the preamble instruction) — needs a browser repro.
2. **Decay/expiry:** `last_sourcing_intent` overwrites each turn + TTL-expires; if a buyer moves to a totally different product, it should clear (today it's overwritten by the next sourcing turn but persists across non-sourcing turns — consider clearing it when the use_case changes).
3. **Don't over-stuff the preamble:** the memo is one line; keep it bounded so it doesn't crowd the LLM context.

---

## What I executed alongside this breakdown
- Added the **fluid-flow e2e acceptance test** (`test_fluid_sourcing_journey_api`) — §1b.
- Confirmed the **cache `order_quantity` fix is already in** (`40b2082`) — §6.

## Recommended next executions (in order)
1. **price_conversion + redis_factory extracts** (Phase 2 §4) — I can do these now, low-risk, bug-class prevention.
2. **Market-intel shadow wiring** (§2) — enable `HIPPOGRAPH_FEEDBACK_ENABLED` in shadow, then feed competitor-price into the discount recommendation.
3. **Your browser pass** (P1–P13 + the e2e gate) with `RECOMMEND_NARRATION_MODE=async`.
