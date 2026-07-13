# GPT-5.6 Review Packet — Review-10: the Smart-Core arc (1a–1f + harness refactor)

**Scope: `git diff 8580807..HEAD` — 13 commits, 21 files, +1,749/−21.** This is the delta since
the KB-smart baseline: the entire V2 recommendation-core "smart core" (capability floor → shelf →
clarifier → complement → bulk economics), the **model-judged harness refactor**, multi-turn
context threading, decomposition fixes, and the 1f polish. Everything is behind
`RECOMMEND_CORE_MODE` (default off) — **zero production behavior change**; the ask is a deep
adversarial review before we build the UI (1e) on this contract.

**Full regression green** (exit 0) across ratchets (no-flavour, no-silent-except, no-fail-open) +
all core suites. ~47 new test functions across 9 new test files.

---

## The commits (newest → oldest)

| # | commit | what |
|---|---|---|
| 13 | `5e22e96` | 1f polish: node-scoping floor via the **declared device host union** (video $4894→$1199; drawing unchanged) |
| 12 | `d589e36` | 1f polish: **capability-conflict narration** (data-derived "relax the discrete GPU (3 match)") |
| 11 | `5cc6c12` | decomposition: **exclude_brand** slot ("not Apple") — the one negation gap |
| 10 | `1fb2dde` | **HARNESS REFACTOR** — model-judged quantity+budget (kill the $-regex + count-as-fit-predicate) + **multi-turn context** |
| 9 | `4bd77bf` | **1f bulk-procurement economics** — ÷units viability + tradeoff menu |
| 8 | `9c480e3` | 1d.4b: bundle real price + **standalone complement-as-primary** |
| 7 | `f74e696` | 1d.4: **unstocked-complement trust play** (bundle ↔ source-it by stock truth) |
| 6 | `9f3e83e` | **KB wiring** — registry capability predicates reach the LIVE decision path + enum-crash fix |
| 5 | `2aa3300` | review fixes — brand-blind floor leak + double retrieval + frontend adapter seam |
| 4 | `4aafae9` | 1d: soft **preferred_brand** + intent-aware **cart-swap brain** (assess_intent_fit) |
| 3 | `3bd59e2` | 1c: **variant clarifier** (ask only when it moves the floor) |
| 2 | `56b97d5` | 1b: **3-band shelf contract** (extras[shelf]) |
| 1 | `2920672` | 1a: **budget×capability floor** (catalog-DERIVED, never stored) + honest tradeoff |

**Files (production):** `core.py` (+541), `turn_router.py` (+97), `fit.py` (+92),
`intent_resolver.py` (+53), `bulk.py` (+50, new), `use_case_registry.py` (+24),
`legacy_adapter.py` (+9), `suggest_contract.py` (+9), `recommendation_postflight.py` (+5),
`data/use_cases/electronics.json` (+10).

---

## What changed & why (self-assessment — challenge every claim)

### A. The smart core (1a–1f) — deterministic stages after the ONE model call
`core._recommend_turn` runs, AFTER the single `route_turn` LLM call, a sequence of **guarded,
data-driven stages** (each `try/except`-wrapped + logged, lane-gated):
- **capability floor** (`fit.build_cards` → `capability_floor_cents`; `_apply_capability_budget`):
  the cheapest catalog product that MEETS the resolved requirements — DERIVED, never stored.
  Branches on budget (floor_stated / within_budget / below_budget tradeoff). `_budget_free_cards`
  probes the floor ignoring the ceiling (else the "real floor is $1199" is invisible).
- **3-band shelf** (`_build_shelf` → `extras[shelf]`): partitions ranked cards into best_fit /
  stretch-or-more_capable (headroom, NOT just pricier) / preference. Adaptive, deduped.
- **variant clarifier** (`_maybe_variant_clarify`): asks ONE question only when a use-case's
  variants spread the floor materially AND the shopper hasn't anchored it; else states an
  assumption. Content-advisory surfaces, never blocks.
- **complement trust-play** (`_maybe_complement_offer` → `extras[complement_offers]`): a declared
  complement (drawing → graphics tablet, node el-7-9-12-7) becomes a **bundle-upsell if stocked,
  a source-it supplier-RFQ + willing-to-wait offer if not** — one KB declaration, `sells_within`
  picks the branch. Stocked → also offers the **standalone** path ("already have a computer? just
  the tablet"). Never auto-sends.
- **bulk economics** (`bulk.assess_bulk` + `_maybe_bulk_economics` → `extras[bulk]`): quantity ×
  floor vs total budget → viability + tradeoff menu (increase budget / reduce units / bundle-fit /
  payment plan). `_bundle_floor` = cheapest non-touch laptop + cheapest complement.
- **cart-swap brain** (`fit.assess_intent_fit`): does a product swapped INTO the cart still meet
  the remembered intent? Soft advisory + closer alternatives. **No caller yet** (wired at 1e).

### B. The harness refactor (`1fb2dde`) — the anti-brittle move
The prior bulk build had a **$-regex (`_parse_total_budget`)** and smuggled quantity through the
fit `count` requirement. Both removed. Now **the model extracts `quantity` + `total_budget`** as
structured fields; the router **clamps** them (qty int 1..100k; budget $1..$100M → cents). A model
that put the count in `requirements` is still honored (graceful bridge — reading the model's output
flexibly, NOT a query regex); `count` is excluded from fit requirements. **This is the
model-agnostic contract**: model proposes, platform clamps, a miss → null → inherit/clarify.

### C. Multi-turn context (`1fb2dde`) — the context-rot fix
`turn_router._prior_context_block` shows the PRIOR subject (node path + use-cases + budget) to the
classifier so a subject-dropping follow-up ("only 6 people, $19000") stays in-category (was
mis-routing "drawing class" → Art & Crafts → off-catalog). quantity + total_budget persist in the
session (`postflight.write_session`) and inherit on continuation (`core.py` R9.1 block). Over-anchor
guarded (a genuine "show me monitors" still switches).

### D. KB wiring (`9f3e83e`) — the honesty fix
The marquee scenario wasn't firing live: the router classified use-cases against the LEGACY KB
(no "drawing"), and touchscreen/form_factor (boolean/enum) can't ride the numeric constraint
machinery. Fixed: `known_use_cases()` = legacy ∪ registry; `_inject_registry_capabilities` injects
boolean/enum predicates AFTER `project()` (MERGE-not-override). **Live-proven**: drawing→touchscreen
floor $1124 on the real catalog; cyberpunk→GPU-#1 with real qwen3.

### E. Decomposition + polish (`5cc6c12`, `d589e36`, `5e22e96`)
- `exclude_brand`: negation slot, same model-judged pattern.
- `fit.relaxation_options`: catalog-derived capability-conflict ("relax the discrete GPU (3 match)").
- `_capability_scope_nodes`/`_gather_scope_variants`: the floor spans the **declared device host
  union** (profile `capability_host_nodes.run_on = [Laptops, Gaming Laptops]`) so a GPU intent
  routed to Laptops still sees Gaming Laptops.

---

## The NEW contract surfaces (what the 1e UI will bind to — review these shapes hard)
Adapter `_full_pipeline` now passes (all registered in `suggest_contract.KNOWN_FIELDS`):
`shelf {banner, bands[{id,label,basis,skus,cards}]}` · `capability {verdict, floor_cents,
budget_max_cents, meets_in_budget, probed_budget_free}` · `complement_offers[{key, mode
(bundle|source), stocked, supplier_rfq_offer, options, tags, from_cents}]` · `bulk {quantity,
total_cents, per_unit_cents, floor_cents, needed_cents, units_affordable, verdict, tradeoffs[],
bundle}` · `capability_conflict {requirements, relax_options[{key,count}]}` · `advisories[]` ·
`assumption` · plus `TurnDecision` gained `quantity, total_budget_cents, exclude_brand,
preferred_brand`.

---

## SPECIFICALLY what I want you to test / review

1. **Harness refactor (turn_router quantity/total_budget clamp + core).** Does the **count-bridge
   double-count** if the model fills BOTH `quantity` AND a `count` requirement? Is the
   dollars→cents `total_budget` conversion safe on floats/edges? Is `count` fully excluded from fit
   on EVERY lane (I saw a live case where it leaked before the fix)? Is the clamp bound-complete?
2. **Multi-turn context + inheritance.** The inheritance is gated to FILTER/COMPARE/EXPLAIN — is a
   **PROCUREMENT continuation** ("actually 6 people") correctly inheriting, or does it fall through?
   Can the prior-context **over-anchor** (a real new search inheriting the old node)? Does
   `exclude_brand`/`brand_filter` **persist across turns** (I did NOT add them to the session — a
   follow-up likely LOSES the brand filter — confirm)? Any stale-node inheritance risk?
3. **Bulk economics + `_bundle_floor`.** Math correctness (units_affordable, per_unit, bundle
   needed); edge cases (qty 1, floor None, total None → "unsized"); any div-by-zero; does
   `_bundle_floor` correctly drop touchscreen/form_factor and add the cheapest stocked complement?
4. **Host-union floor scoping — LATENCY.** `_gather_scope_variants` now does **N `gather_evidence`
   calls (2–3 nodes) per floor computation**, and a `below_budget` turn ALSO runs the budget-free
   probe + complement gather + bulk floor. **Count the total DB round-trips on a worst-case turn**
   (bulk + below_budget). Is this a hot-path latency regression? Can a non-host wrongly get the
   union? Does dedup work? Does it change the drawing floor (should not)?
5. **Stage composition (core._recommend_turn, ~8 stages).** **Message-clobber ORDER**: which
   stage's `resp.message` wins, and is it always the most-specific? Do the guards compose (lane /
   degraded / off_catalog)? Does any stage mutate `decision.requirements` in a way that corrupts a
   later stage? Is the `resp._bf_cards` memoization correct across `_apply_capability_budget` →
   `_build_shelf`?
6. **`fit.relaxation_options` (conflict).** O(reqs × variants) over up to 200 variants on a
   closest-match turn — is it bounded/acceptable? Correctness of "drop each req, count meets". Does
   it fire spuriously (e.g. when there's a single trivially-relaxable req)?
7. **Complement trust-play.** The `sells_within` branch (stocked→bundle vs None/False→source); the
   EXTRA `gather_evidence` in the stocked path; the willing-to-wait CTA; tenant scoping.
8. **Adapter/contract.** Every new key registered? Contract test truly green? Any shape the UI
   needs that's `None`/dropped? Is `capability_conflict` / `bulk` serialization stable?
9. **Registry injection interactions.** Does `_inject_registry_capabilities` interact badly with the
   accessory-req-drop, the multi-intent merge (intersection), or the workload reroute?
10. **Tenant safety across ALL new stages** — every `sells_within` / `gather_evidence` passes
    `tenant_id`?

## Blind spots — please UNEARTH what we missed
- **Latency budget** end-to-end: how many model calls (should be exactly 1) + DB round-trips per
  turn now, worst case? Any turn that does 5+ retrievals?
- **Silent degradation**: every stage is `try/except → logger.warning`. The ratchet catches silent
  *swallows*, but could a logged-warning degradation **mask a real bug** (a stage that always
  fails quietly)? Are any of these except-blocks too broad?
- **Session race**: concurrent turns for the same uid — does the postflight write/read race?
- **Other model-reliability boundaries** (beyond the two we know — indirect quantity "6 people",
  unreliable `total_budget`): does the model reliably fill `use_cases` for indirect intents,
  `workloads`, `exclude_brand`? Where else does a weak BYO model degrade, and is the degradation
  safe?
- **Floor honesty edge**: the host-union floor can quote a **Gaming Laptop** as "the cheapest that
  meets" for a query the shopper meant as a plain Laptop — is that misleading, or fine as a "cheapest
  capable" reference?
- **Wacom seed reproducibility**: the 3 Wacom SKUs were seeded DIRECTLY into `demo.sqlite` (not via
  the enrich pipeline, which reads `docs/laptop-products.txt`, NOT the file they were added to). CI /
  a re-seed would DROP them. Flag the reconciliation.
- **`assess_intent_fit` has no caller** — dead until 1e. Confirm it's correct so 1e can trust it.

## Known model boundaries (already documented — confirm, don't re-report as new)
- qwen3 missed **indirect quantity** ("6 people" → qty 6; inherited 20 instead). Degrades gracefully.
- qwen3 unreliably fills **total_budget** on its own — mitigated by the edge parsing budgets (same
  as single-item). Not a decomposition break.

---

## Roadmap changes (this arc)
- **Elevated multi-turn context to #1** after the bulk stress test exposed context-rot — now DONE.
- **Two-speed architecture decision recorded**: hot path = ONE clamped LLM call + deterministic
  stages + (future) parallel-I/O evidence; cold path = LLM agent swarms for async intelligence.
  We do NOT swarm the hot path. Scatter-gather over parallel SOURCES already exists
  (`recommend_pipeline.py`, `evidence_orchestrator.py`, both flag-off) — the "smartness epic"
  lights those up; agent swarms live on the cold path (market-intel, procurement, THIS review).
- **1f (bulk) added** as a named phase; **1e (UI)** now includes the bulk tradeoff-menu +
  complement + conflict cards + trace drill-down.

## What to do from here (proposed)
1. **You (GPT-5.6): this review.** Fix whatever survives verification.
2. **1e — the UI** on the reviewed, contract-stable `extras` shapes (shelf/complement/bulk/conflict
   cards + trace drill-down + wire `assess_intent_fit` into the cart + fix 2 legacy App.tsx bugs).
3. **Data breadth** (graphics tablets across brands/tiers — anti-overfit) + **seed reconcile**.
4. **Screenshot behavioral battery** (Phase 3.0 gate) → **Phase 2** labels/soak → **Phase 3**
   canary/retire `suggest()`.
5. **Phase 4 / smartness epic**: typed pricing, procurement FSM + volume pricing + supplier email,
   Move-1 evidence scatter-gather into the core, Move-2 cold-path swarms.

## Verification already performed
- Full regression green (ratchets + all core suites), ~47 new tests.
- Live-proven on the real 131-product catalog + real qwen3: drawing $900→$1124 tradeoff;
  cyberpunk→GPU-#1; complement source→bundle flip (Wacom seeded); bulk $16k/20→14-units/stretch/
  bundle/payment-plan; multi-turn context (stays on Laptops, $19k-update wins, topic-change
  switches); exclude_brand (no Apple); conflict narration; host-union floor ($4894→$1199).
