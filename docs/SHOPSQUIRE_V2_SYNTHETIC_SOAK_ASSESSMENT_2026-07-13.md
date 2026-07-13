# ShopSquire V2 Synthetic Soak Assessment - 2026-07-13

## Scope and evidence

This is a compressed, model-backed V2-core functional soak, not human traffic and not human
relevance ground truth. It is side-effect-free: cart plans are applied only to an in-memory cart,
and no supplier, return, payment, or order action is executed.

- Runner: `tests/characterization/synthetic_conversation_soak.py`
- Runner tests: `tests/characterization/test_synthetic_conversation_soak.py`
- Raw report: `tmp/synthetic_soak/review10_baseline_200.json`
- Support honesty probe: `tmp/synthetic_soak/support_honesty_probe.json`
- Seed: `20260713`
- 200 turns, 50 four-turn journeys, 10 families, 25 minutes
- Model: router default `qwen3:14b`, temperature 0, 20-second request timeout

Families: high-school homework/light gaming, university engineering, local AI/image generation,
retiree social/video/casual gaming, graphics tablets, office per-unit procurement, office total-budget
procurement, AAA/esports gaming, returns/warranty/repair, and multi-item cart changes.

## Result

Raw invariant result: 155/200 passed (77.5%). Latency was p50 7.77s, p95 8.66s, maximum
13.61s. Cart-resolution turns were faster, but ordinary recommendation turns remained roughly
7-9 seconds. This is core latency only; it excludes browser and HTTP composition overhead.

| Family | Pass | Finding |
|---|---:|---|
| AI creator | 20/20 | Routing stable, but first recommendation remains relevance-unproven |
| Cart changes | 20/20 | In-memory typed plans correct; not a CAS/persistence test |
| Gaming | 20/20 | Cyberpunk -> Valorant -> cheaper -> explain stayed on gaming laptops |
| Graphics tablet | 5/20 | Self-complement plus procurement follow-up category drift |
| High school | 5/20 | Minecraft follow-up drifted to toy food and poisoned later turns |
| Office per unit | 15/20 | Per-unit budget was incorrectly treated as total-order budget |
| Office total | 10/20 | Total budget dropped; quantity amendment became CART_MUTATE |
| Retiree | 20/20 | Routing stable; relevance still needs human judgment |
| Support | 20/20 raw | Audited result is 10/20: two turns per journey falsely claim persistence |
| University | 20/20 | Routing stable; closest slate admits GPU requirement failures |

The post-run support invariant found 2/2 support-action turns say "I've logged this" and set
`claim_status=received` although no claim is persisted. Applied to the baseline, at least 10 more
turns fail. The audited upper bound is therefore 145/200 (72.5%), before testing brand persistence.

## Confirmed defects

### P0 - Budget semantics are unsafe for procurement

`turn_router.py` tells the model to extract quantity and total budget, but its output JSON schema
does not include either field. There is no `budget_scope` field at all. `core.py` then uses
`decision.total_budget_cents or envelope.budget_max_cents` as the order total. A request for
15 laptops at $1,400 each was narrated as "$9,435 is over your $1,400".

Ownership:

- `src/app/services/recommendation_core/turn_router.py:322-334`: complete the bounded schema with
  `quantity`, `budget_amount`, and `budget_scope = per_unit|total|unknown`.
- `src/app/services/recommendation_core/turn_router.py:490-497`: clamp finite numeric values and
  scope; never infer order-total arithmetic when scope is unknown.
- `src/app/services/recommendation_core/core.py:753-761`: compute total only from explicit scope.
- `src/app/services/recommendation_core/bulk.py`: keep deterministic multiplication/division here.

Acceptance: 100% correct on per-unit, total-order, no-budget, range, changed-quantity, and changed-
budget permutations. Unknown scope asks one clarification and performs no affordability claim.

### P0 - Multi-turn subject continuity is under-specified

Candidates are generated from the current fragment before prior state is considered. Prior context
contains only a path, not a valid taxonomy handle. The model is told to keep the prior category but
is not given that handle to return. Minecraft and "the class needs 10" therefore selected unrelated
toy/school-bag nodes. An OFF_CATALOG mistake then became the next active subject.

Ownership:

- `src/app/services/recommendation_core/turn_router.py:345-363`: inject the prior node and relevant
  host/sibling nodes into the bounded candidate list; include the prior handle in context.
- `src/app/services/recommendation_core/turn_router.py:381-420`: add a model-proposed, clamped
  `subject_action = continue|switch|uncertain`; apply drift validation independent of lane.
- `src/app/services/recommendation_postflight.py:53-69`: persist a new subject only after grounded
  success or an explicit validated switch. Do not let a failed refusal poison the session.
- `src/app/services/recommendation_core/core.py:152-177`: allow procurement continuations to inherit
  accepted state when `subject_action=continue`, rather than keying inheritance only to lane names.

Acceptance: Minecraft, graphics-tablet class quantity, brand exclusion, budget-only, explain, and
explicit topic-switch permutations retain or switch subject correctly in 100/100 seeded runs.

### P0 - Cart and procurement amendments need a state discriminator

"Reduce the order to 15" was classified as CART_MUTATE with an empty cart. This is not a phrase-
grammar problem. The platform has enough state to reject an impossible cart operation.

Ownership:

- `src/app/services/recommendation_core/envelope.py`: expose active cart and active procurement
  state as bounded booleans/version IDs.
- `src/app/services/recommendation_core/turn_router.py`: let the model propose the lane.
- `src/app/services/recommendation_facade.py:393-418`: deterministic validation: CART_MUTATE requires
  a non-empty current cart; otherwise continue the active procurement intent or clarify.
- `src/app/services/recommendation_core/cart_resolver.py`: remain the SKU-bound cart planner only.

Acceptance: the same language targets procurement with no cart and targets cart mutation with a
cart; neither path guesses when both are active and the target is ambiguous.

### P0 - False support persistence claim

`src/app/services/recommendation_core/core.py:959-964` says a support claim was logged without any
write. Support is currently excluded from canary lanes, so this is not live V2 behavior yet.

Fix: use proposal language until an idempotent support handoff returns a committed claim ID. Add
that ID and audit event to the response before allowing SUPPORT_CLAIM into `CANARY_LANES`.

### P1 - Graphics-tablet self-complement and seed reproducibility

A direct Wacom tablet query recommends the Graphics Tablets node as its own complement. Only one
under-$500 Wacom appears. The additional Wacom data lives in an untracked source file and was
previously inserted directly into the demo DB.

Ownership:

- `src/app/services/recommendation_core/core.py:629-684`: suppress same/ancestor/descendant
  complement nodes before retrieval.
- `data/use_cases/electronics.json:32-51`: keep the declared complement as data.
- Catalog onboarding/seed pipeline: ingest graphics tablets through the canonical source and
  classify them; do not seed the DB manually.

### P1 - Test data contaminates recommendation slates

`scripts/e2e_sweep.py:128-141` inserts `E2E-RET-1` into the shared product catalog and never cleans
it up. It appeared in the AI recommendation slate. Run E2E setup in an isolated tenant/database,
or delete all created rows in a reliable `finally` block. Product retrieval should also exclude
explicit test fixtures from non-test tenants.

### P1 - Stage composition is becoming a new monolith

The Review-10 arc adds 541 lines to `recommendation_core/core.py`. Stages mutate one response and
overwrite `message` in sequence, while broad exception handlers only log and continue.

Refactor before adding more stages:

1. Each stage returns a typed `StageResult` with facts, cards, advisories, proposed message, priority,
   status, latency, and error code.
2. One composer selects buyer prose by declared priority; stages do not overwrite `resp.message`.
3. Record stage attempted/succeeded/degraded plus retrieval/model-call counts in trace telemetry.
4. Move capability, shelf, complement, and conflict presentation out of `core.py`; keep core as an
   orchestrator. Attribute labels currently hardcoded around `core.py:909` belong in registry data.
5. Replace repeated host-node retrievals in `core.py:343-354` with one tenant-scoped union query.

## Reordered roadmap

### Gate 0 - Lock the diagnosis

- Keep the 200-turn report as the pre-fix baseline.
- Add the four repeated failure families to the stateful golden corpus, keyed `case_id:turn`.
- Add prompt-contract tests that fail when documented fields are omitted from the output schema.

### Gate 1 - Correctness before UI

- Implement budget scope, subject action/prior-node candidates, empty-cart lane validation, support
  honesty, self-complement suppression, production-equivalent brand persistence, and E2E isolation.
- Re-run 200 turns. Required: 100% budget arithmetic, 0 subject poisoning, 0 false persistence,
  0 self-complements, 0 unsafe actions. Do not lower thresholds to pass.

### Gate 2 - Observability and latency

- Add stage status/latency and DB/model-call counters.
- Batch host-union evidence reads and cache immutable taxonomy/attribute data.
- Establish separate cold and warm SLOs. The current warm p95 of 8.66s is not canary-ready for a
  synchronous routing call; measure first-token and complete-response latency through HTTP/SSE.

### Gate 3 - Human labels, not synthetic labels

`tests/golden/relevance_labels.json` is still empty. Build a blind label pack containing query,
prior context, budget, requirements, candidate pool, and anonymized V1/V2 slates. Label candidate
pools, not only shown products.

- Select 30-50 unique product-expected turns, stratified across the six product personas.
- Two human reviewers grade 2/1/0 independently; adjudicate disagreements.
- Keep dev/test splits sealed. Do not label cart, policy, or support turns for NDCG; those receive
  lane/safety labels instead.
- Apply existing gates in `recommendation_core/quality.py:32-43`: at least 30% labeled coverage,
  precision@10 >= 0.60, NDCG@10 >= 0.60, constraint satisfaction >= 0.70, unauthorized rate 0.

### Gate 4 - Synthetic production soak

The current run calls V2 directly. The operational soak must use `/suggest` through
`recommendation_facade.py` in `shadow` mode and the Redis Streams worker.

- 500 turns in durable batches over 24 hours (roughly 20 turns/hour), unique tenant/user IDs.
- Restart backend and shadow worker at controlled checkpoints; inject one Redis interruption.
- Verify stream pending recovery, idempotent replay, 0 queue loss, 0 cross-tenant/session bleed,
  session TTL behavior, and no supplier/payment sends.
- Repeat for 72 hours only after the 24-hour gate is clean.

### Gate 5 - Bounded domain evidence

- Wire the existing `connectors/steam_requirements.py` fixture-first connector into a typed workload
  evidence stage, not directly into the router. Translate desktop GPU requirements through
  `gpu_translation.py`, preserve minimum vs recommended verdicts, citations, cache age, and source.
- Add equivalent governed evidence only where it changes a fit decision. Avoid a broad homework web
  search or age-based recommender; use stated tasks and curriculum/software requirements instead.

### Gate 6 - UI, canary, retirement

- Bind UI cards only after extras shapes and message ownership are stable.
- Shadow -> canary 1% -> measured ramp -> primary. Procurement/support remain legacy until their
  idempotent handoffs and audit contracts are complete.
- Archive legacy `suggest()` and remove `App.tsx`/`chat.py` duplicate intent routing only after at
  least four weeks of clean canary evidence and a one-switch rollback remains tested.

## What is already done

- Redis Streams shadow worker with consumer group, reclaim, durable DLQ, and tests exists.
- Shared guard, lane gate, fallback ladder, tenant envelope, catalog taxonomy/classification, typed
  cart plans/CAS tests, fulfillment workflow, returns persistence tests, and V2 intrinsic quality
  gates exist.
- Selected cart, fulfillment, return, shadow-worker, complement, bulk, and multi-turn suites passed
  after the soak; five environment-gated tests skipped.
- The human relevance label set is not done. Procurement/support are not V2 canary lanes. The
  current 200-turn run is not an old-vs-new production A/B and must not be presented as one.
