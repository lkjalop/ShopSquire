# ShopSquire — Adjudication of the GPT-5.5 Independent Review (2026-06-18)

Purpose: I (Opus 4.8) independently **verified** each falsifiable claim in
`SHOPSQUIRE_AGNOSTIC_CORE_INDEPENDENT_REVIEW_2026-06-18.md` against the actual tree, paranoid
style — no claim accepted without reading the code. Verdict per claim, then findings **both**
reviews missed, then the recommended first PR.

Headline: **the GPT-5.5 review is high-accuracy and should be trusted.** Every file it named
exists; its two flagged bugs are real; one severity is overstated and one model-routing claim is
stale-but-directionally-right. It surfaced four blocker files I had missed. My paranoid pass
found three *additional* structural problems neither of us had named.

---

## Part 1 — Claim-by-claim verification

| # | GPT-5.5 claim | Verified? | Evidence | My verdict |
|---|---|---|---|---|
| 1 | `product_taxonomy.py`, `checkout_upsell.py`, `bundle_pricing.py`, `use_case_advisor.py` are blockers I missed | ✅ TRUE | files exist: 180 / **1076** / 126 / 621 lines | **Agree.** checkout_upsell is a whole 2nd upsell system; I only audited upsell_engine (317). Correct catch. |
| 2 | `store_profile.py:40` falls back to electronics on missing profile (P0 fail-open) | ✅ TRUE + worse | [store_profile.py:50-51](src/app/platform/store_profile.py#L50) falls back; `strict` (line 47) guards only **malformed JSON** (line 59), NOT missing-profile | **Agree, raise confidence.** Strict mode doesn't even cover the missing case. Genuine fail-open for multi-tenant. |
| 3 | `checkout_upsell.py:~668` compares cents to dollar-ish `1200` | ✅ TRUE | [:658](src/app/services/checkout_upsell.py#L658) `cart_price = sum(price_cents)` (cents); [:669](src/app/services/checkout_upsell.py#L669) `cart_price > 1200` = ">$12"; [:671](src/app/services/checkout_upsell.py#L671) `<= 1200` branch is dead for real carts | **Agree on bug, downgrade severity P0→P2.** The strict 70%-of-cart guard is itself sane; only the *adaptive relaxation* never fires. Revenue impact is low-value carts get over-filtered, not laptop carts. |
| 4 | Config drift: StoreProfile vs `store_vocab.json` vs use-case KB files | ✅ TRUE + worse | product_classifier reads `store_vocab.json` ([:31](src/app/services/product_classifier.py#L31)); use_case_advisor reads `use_case_knowledge_base.json` **and** `use_case_knowledge.json`; `use_case_kb.json` also exists; electronics.json has a `use_cases` slot | **Agree, it's quad-source not dual.** Use-case knowledge lives in 4 places, all live (loaded by nqe/recommend/recommendations/use_case_advisor). |
| 5 | `llm_provider.py:13` medium default mismatches ladder (`27b` vs `14b`) | ⚠️ STALE but right-in-spirit | source const `MEDIUM_DEFAULT="qwen3.6:27b"` ([:19](src/app/services/llm_provider.py#L19)); ladder medium=`qwen3:14b`. **Primary path** `_tier_for_score(5)` → `qwen3:14b` (correct); **fallback/wrapper** ([:64](src/app/services/llm_provider.py#L64), [:256](src/app/services/llm_provider.py#L256)) → `27b` const | **Partial agree, P2.** Runtime routing is currently correct; the constant is a latent drift that 2×-costs if the ladder fails to load or a caller uses `select_ollama_model`. Align the constant to the ladder. |
| 6 | Scatter legs still collapse errors to empty (silent fail) | ✅ TRUE | timeouts wrapped, but leg failure → empty struct, indistinguishable from no-hit | **Agree.** Matches my §7. Typed source-status is the fix. |
| 7 | `recommend.py` ≈ 14,078 lines, suggest() ≈ 7.7k | ⚠️ stale number | current = **14,661** (review measured an earlier/other checkout) | **Agree on substance, number drifted.** suggest()≈7.7k still holds. |
| 8 | Vision binary relevance needs on/adjacent/off model | ✅ TRUE | [cv_triage_basic.py:133-146](src/app/services/cv_triage_basic.py#L133) binary, electronics-keyed | **Agree** — identical to my own §4. Independent convergence raises confidence. |
| 9 | NQE templates hard-coded (school/uni/gaming/corp) | ✅ TRUE | nqe.py question gen + `_template_field_map` | **Agree.** |
| 10 | Don't rewrite; strangler-extract; deterministic decides, LLM interprets | ✅ | — | **Strong agree** — same conclusion both reviews reached independently. |

**Scorecard: 10/10 claims substantively correct.** 2 severity adjustments (P0→P2 on the price
bug; P1→P2 on model routing), 2 "true and actually worse" (store_profile strict gap; quad config
drift), 1 stale line count. No hallucinated files. This is a review worth acting on.

---

## Part 2 — Findings BOTH reviews missed (my paranoid pass)

### F1 — Split-brain upsell (two engines on two surfaces, two taxonomies)
- `upsell_engine.get_upsell_candidates` is wired **only** to the cart route ([cart.py](src/app/routers/cart.py)).
- `checkout_upsell` is wired to the **recommend** route + admin + synthetic lab.
- They classify with **different taxonomies**: upsell_engine → `product_classifier` (store_vocab.json); checkout_upsell → `product_taxonomy` (hard-coded families).
- Result: the *same product* yields different companion logic in cart vs recommend. The review said "rationalize the two"; the sharper problem is they're **live on different surfaces with divergent taxonomy sources** — a consistency bug, not just duplication.
- **Fix:** pick checkout_upsell as the engine (it's the richer one), make cart call it too, and back **both** with one profile-driven taxonomy (see F2). Retire upsell_engine to a thin shim.

### F2 — Two product taxonomies in one request path
- `product_taxonomy.py` (hard-coded) ← recommend.py body, bundle_pricing, catalog_profile, checkout_upsell.
- `product_classifier.py` (store_vocab.json) ← **recommend_response_finalizer (CORE)**, upsell_engine.
- So the **core finalizer** and the **route body** disagree on what "product type" means and read from different sources. Off-type demotion (finalizer) and family-based bundling (route) can contradict.
- **Fix:** one taxonomy, profile-driven. `product_classifier` (already config-backed) should be the survivor; `product_taxonomy`'s families become a profile slot. This collapses F1+F2 into a single `StoreTaxonomy` source — the highest-leverage consolidation on the board.

### F3 — V2 shadow is discarded compute
- [recommend.py:6415](src/app/routers/recommend.py#L6415) spawns a daemon thread that runs the full scatter-gather pipeline and records only `ms/count/error` ([:6398](src/app/routers/recommend.py#L6398)); the **result is thrown away**.
- Defaults **off** (`RECOMMEND_PIPELINE_V2="0"`), so not prod overhead today — but if anyone flips it on for "parity data," they pay a full extra pipeline per request for ms/count only.
- **Fix:** before turning it on, add the real parity payload (top-k overlap, budget/stock adherence, typed source status) the review lists — otherwise it's cost with no signal.

### F4 (checked, NOT a bug) — `_estimate_margin_guardrail` units
- Paranoia demanded I check the *other* numeric guard. [:496](src/app/services/checkout_upsell.py#L496) takes `price_cents`; thresholds 1500/5000/20000 = $15/$50/$200 tiers; called with cents at [:694](src/app/services/checkout_upsell.py#L694). **Consistent (cents in, cents thresholds).** Not a bug — recorded so the negative result is on the record.

---

## Part 3 — Where I agree the order should change

The GPT-5.5 review's Phase 0→7 order is sound and **more cautious than mine** (it front-loads
characterization fixtures + StoreProfile strictness before any extraction). I agree with its
sequencing over my A→E in one respect: **fix `store_profile` fail-open (P0) and pin
characterization fixtures FIRST**, because everything downstream trusts the profile and the
baseline. My only amendment: fold F1+F2 (taxonomy/upsell consolidation) into its Phase 2 as the
*single* `StoreTaxonomy` source — don't migrate `product_taxonomy` and `product_classifier`
separately or they'll drift again.

Merged first-PR (smallest safe, highest blocker-clearance):

1. **store_profile strict missing-profile** → in strict mode a missing requested profile RAISES (don't fall back). Fail-closed. (P0, ~15 lines + test)
2. **checkout_upsell cents fix** → name the threshold `_MIN_ADAPTIVE_CART_CENTS` and set it to a real value; add a cart-units test. (P2 bug, contained)
3. **Characterization fixtures** for 10-15 representative queries (electronics) so later extraction has a baseline. (enables everything)
4. **One taxonomy decision** (F2): declare `product_classifier`+profile the survivor; add `product_taxonomy` families to electronics.json; leave the code migration for Phase 2 but stop new call-sites.

That PR clears the one true P0, the confirmed bug, and lays the baseline — without touching NQE,
narration, vision, or the main route (no scope creep).

---

## Part 4 — Net answer to "are we doing the right thing?"

Both independent reviews (GPT-5.5 and Opus 4.8) converged, separately, on the same verdict:
**right direction, no rewrite, strangler-extract, deterministic-decides/LLM-interprets,
profile-drive the flavour.** That convergence is itself the strongest signal. The deltas are
sequencing discipline and four blocker files + three structural split-brains (F1-F3) that need
consolidation. None of it changes the architecture; all of it is contained, testable, ordered
work. Proceed.
