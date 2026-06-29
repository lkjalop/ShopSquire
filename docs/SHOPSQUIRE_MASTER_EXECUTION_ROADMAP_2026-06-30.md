# ShopSquire — Master Execution Roadmap (ordered)

**Date:** 2026-06-30
**Purpose:** The single ordered sequence across the three detail docs — go-live readiness, browser test plan, architecture assessment. This is *what to do and in what order*, with the rationale for the order.

**Ordering principle:** correctness first (cheap, removes risk) → continuity (the product gap) → hygiene (duplication) → verify → integrate (secrets) → autonomy (staged) → architecture (long-term). Do NOT jump to go-live integrations before the correctness + verify phases — a clean base is what makes the integrations trustworthy.

Owner: **[C]** Claude (code) · **[U]** You (secrets/infra/decision/browser).

---

## PHASE 0 — Correctness quick wins (do FIRST; hours; low-risk) [C]
*Why first: cheap, unambiguously correct, and they remove real risk (event-loop blocking, an N+1 I introduced, cache/card mismatch). Clears the deck before anything bigger.*

1. **`time.sleep` → `await asyncio.sleep`** in the two async endpoints (`recommend.py:~4857`, `pricing.py:~50`). Event-loop correctness. (~15 min)
2. **Batch the N+1** in `order_split._find_sku_for_phrase` — resolve all phrases against one product fetch instead of a full `SELECT` per phrase. *(my code; my fix)* (~1 hr)
3. **Cache fingerprint** += `order_quantity` + `sourcing_intent.mode` so a bulk query never reuses a non-bulk query's narration prose (the prose↔card mismatch). (~30 min)
4. **Re-run the full suite** (now fast after the Redis-hang fix `1b7ffe1`) → confirm a clean green; the only chunk failure was a test-ordering flake (`test_admin_bi_executive_pulse_shape`, passes isolated). (~20 min wall, mostly waiting)

**Exit:** suite green + 3 correctness fixes in.

---

## PHASE 1 — Procurement continuity (the missing half of fluid procurement) [C]
*Why second: it's the highest PRODUCT-value finding and it's low-risk. Procurement interaction (sourcing_intent/order_group) is NOT in conversational memory, so the LLM can't reference "your 15-laptop request" next turn — the "my requests / flake" gap.*

5. **Persist the lightweight `sourcing_intent` into `kv_state`** (lines + planned split + requirements; NO supplier identity) in `recommend_memory_writeback`, and read it into the narration preamble + NQE context. No durable case created — just memory. Now the assistant can say *"for your 15-laptop sourcing request, here's a cheaper split."* (~1–2 hr)

**Exit:** a buyer who previews sourcing then asks a follow-up gets continuity, not a cold search.

---

## PHASE 2 — Hygiene refactors (collapse duplication; medium; schedule) [C]
*Why third: real maintainability + bug-class prevention, but not urgent. Do after correctness/continuity so the refactors land on stable behaviour. Each is independently shippable + testable.*

6. **`redis_factory.create_redis_client()`** — collapse the 6 Redis construction sites (timeouts already unified) into one. (~2 hr)
7. **`price_conversion` helper** (`cents_to_dollars`/`dollars_to_cents`) — collapse 50+ inconsistent conversions; ends the rounding bug class the BAG failure exposed. (~2 hr)
8. **Feature-flag consolidation** — replace `load_feature_flags(...)` (12× in `decisions.py` alone) + the 3 `_truthy` copies with `feature_flags.get_flags()`. (~2 hr)
9. **Orphaned flags** — remove or wire `CAG_CONTEXT_ENABLED` / `DYNAMIC_CONTEXT_PROVIDER_ENABLED` / `GRAPH_RAG_ENABLED` (defined, never read = misleading). (~1 hr)

**Exit:** the four worst duplications gone; dead config cleaned.

---

## PHASE 3 — Go-live verification (needs you + browser) [U + C]
*Why here: with a clean, continuous, de-duplicated base, NOW verify the real thing. This is the gate between "demo-ready" and "trustworthy for a buyer."*

10. **[U] Browser re-verify** — restart backend (CORP fix `82fccbc` needs it), hard-refresh frontend, run the 10-scenario clickthrough in `docs/SHOPSQUIRE_BROWSER_TEST_PLAN_2026-06-30.md`. **Test #1 (chat renders, no NotSameOrigin) is the critical one.** (~30 min)
11. **[C] One clean full-suite pass** captured + triaged (re-run is fast now).

**Exit:** the buyer journey works in a real browser; suite green.

---

## PHASE 4 — Go-live integrations (needs your secrets; code already exists) [U + C]
*Why here: only after the base is verified. The code exists; this is secrets + a controlled live test. See `docs/SHOPSQUIRE_GO_LIVE_READINESS_2026-06-30.md` Track B/C.*

12. **[U] Real catalog prices** for active SKUs (so margin reads *healthy*, not just computes).
13. **[U] SMTP** creds + `FULFILLMENT_SUPPLIER_TRANSPORT=smtp` → a human-approved RFQ lands in a controlled test inbox.
14. **[U] KYV** real supplier onboarding (replace demo `.example` allowlist).
15. **[U] Stripe** live key (checkout out of demo mode) + secrets/config audit (`AUDIT_CHAIN_SECRET`, Postgres, Redis).

**Exit:** real supplier email (human-approved), real prices, real allowlist — a human-in-the-loop **pilot go-live** is possible.

---

## PHASE 5 — Autonomy rollout (staged, governed) [U decides + C]
*Why after integrations: never flip autonomy before a real supplier dry-run. See the autonomy ladder doc.*

16. **Autonomous-send dry-run** to a test inbox: confirm it escalates on every failing guard (incomplete deadline, MOQ, untrusted recipient, over-cap, rate limit) and only sends when all pass; verify the kill-switch.
17. **Decide** the margin-gate mode (`warn` default vs `block`) and only then consider `FULFILLMENT_AUTONOMOUS_RFQ=1`.

**Exit:** autonomy on with proven guards + kill-switch = **full autonomous go-live**.

---

## PHASE 6 — Architecture (long-term; product-roadmap aligned) [C]
*Why last: high effort, not blocking. Tackle once the platform is live + earning.*

18. `suggest()` (~11.7k lines) → stage-pipeline with intent-based skipping (skip vision/game-detection for simple shopping).
19. Split `recommendations.py` (104KB) into scoring/filtering modules.
20. Decide the shadow `recommend_pipeline` V2 — promote to live or remove.
21. Turn on `HUMAN_FEEDBACK_CAPTURE_ENABLED` (with monitoring) to feed learning.

---

## The one-line answer
**Order:** Phase 0 (correctness) → 1 (continuity) → 2 (hygiene) → 3 (verify) → 4 (integrate) → 5 (autonomy) → 6 (architecture). Phases 0–2 are pure code I can do now; Phase 3 needs your browser; Phase 4 needs your secrets; Phase 5 is your go/no-go.

**Fastest path to a pilot:** Phase 0 → Phase 3 (#10 browser) → Phase 4 (#12 prices, #13 SMTP, #14 KYV). Everything else can follow.
