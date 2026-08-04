# ShopSquire Market Intelligence and V2 Retirement Deep Dive

Date: 2026-07-20

## Executive verdict

The direction remains correct: model judgment maps open language to bounded vocabularies;
deterministic services authorize catalog, taxonomy, money, fit, inventory and actions. The market
deck's visibility -> advisory -> bounded adaptation -> closed-loop sequence matches ShopSquire's
governance posture.

Do not archive `recommend.py` yet. Text V2 is strong enough for continued shadow evaluation, and
the real procurement journey is recordable, but IMAGE remains operationally unreliable on the
12 GB model profile, human relevance labels are not sealed, and mixed legacy/V2 lanes still need a
rollback period. Archiving now would remove the only proven image fallback and strand delegated
lanes behind the `chat.py` HTTP loopback.

## Delta verified in this pass

- Clean pgvector migration proof, canonical image authority, RFQ MOQ/date gates, capability-safe
  expanded slates, truthful replay diagnostics, and warm-model selection were already committed.
- A live Playwright procurement journey passed: clear -> 25 laptops -> split -> confirmation ->
  supplier RFQ/channel/terms -> quantity 15 -> redraft.
- A live context pass found and fixed three V2/legacy boundary defects:
  1. free-text budget ranges reached V2 before legacy parsing;
  2. a delegated legacy bulk turn and a V2 follow-up read different session namespaces;
  3. a budget-only revision could lose the prior product subject when the model said `switch`.
- The fixed browser suite now passes hard ceiling changes, quantity carry-forward, quantity
  amendments and delivery follow-ups through `/api/v1/chat/query`.
- The market/graph/attribution/experiment regression sweep passes 201 tests. Five initially
  failing experiment fixtures reused one fake order id and were updated to respect the production
  `(tenant_id, order_id)` conversion-idempotency contract.

Implementation: `recommendation_core/envelope.py:99`, `recommendation_facade.py:373`,
`recommendation_core/core.py:135`, `recommendation_postflight.py:39`, and
`recommendation_core/turn_router.py:783`. The default-tenant legacy-memory bridge is explicitly
transitional and must be deleted with the loopback.

### 75 x 3 stress result

The checkpointed model-backed run completed all 225 turns across 75 journeys:

- latency: p50 5.88 s, p95 7.03 s, max 22.85 s;
- no exceptions, unauthorized products, cross-tenant writes, cart-plan safety failures, or
  quantity/total-budget arithmetic failures;
- 77 flags were expected-lane label disagreements (`SEARCH` versus an expected `FILTER` or
  `PROCUREMENT`) and are routing-calibration diagnostics, not proof of an unsafe response;
- seven flags came from the trace grammar not recognizing `total order budget`; the arithmetic
  was correct and the grammar is fixed in `budget_grammar.py`;
- one journey lost its prior laptop node on two follow-ups. Reproduction found a BYO-model budget
  invention on “keep the total budget.” The core now requires buyer-supplied monetary evidence
  before accepting a changed amount, persists budget scope, and the exact journey passes:
  20 laptops/$19k total -> 15 units -> cheaper configuration while retaining $19k.

The old aggregate `62.67%` invariant pass rate therefore mixes semantic invariants with lane-label
expectations and must not be used as a promotion score. Split the harness into `semantic_safety`,
`continuity`, `routing_calibration`, and `relevance` dimensions before the next long-context soak.
The 75 x 3 suite proves breadth; it does not replace the planned 20 x 10 and 14 x 15 context-rot,
abandonment, returns and repeated-RFQ-amendment suites.

## Deck assessment

The PDF's seven modules are sensible but "one authoritative store" should mean one authoritative
fact contract, not one physical database:

1. Signal ingestion: largely built in `market_signal.py`, adapters and `market_pipeline.py:20`.
2. Intelligence store: partially built. Findings/history exist, but subject/location/campaign
   dimensionality is incomplete.
3. Analysis: broad detector coverage exists in `market_analysis.py:79-522`.
4. Bounded decisions: campaign readiness and rollback gates exist in
   `campaign_governance.py:34-106` and `experiments.py:149-277`.
5. Communications: supplier communication is mature; customer lifecycle messaging and consent
   policy require a canonical event model.
6. Experiment/attribution: assignment, uplift and trace/order attribution exist in
   `experiments.py:88-277` and `attribution.py:111-371`.
7. Policy/audit: directionally strong; evidence provenance, quarantine and correction outcomes
   need to become first-class facts.

## Current strengths

- Tenant scope is mandatory for graph projection at `hippograph_db.py:66-83`.
- Market evidence uses SKU/product/taxonomy/global precedence rather than brand-token overlap at
  `market_intelligence_agent.py:46-90`.
- Analysis covers demand shift, conversion anomalies, inventory mismatch, forecast/seasonality,
  competitor undercut, objections, funnel, segment, channel and bundle signals in
  `market_analysis.py:79-522`.
- Attribution is tenant-scoped and order-idempotent at `attribution.py:169-263`; reward feed has a
  settlement window, per-user cap and bounded reward at `attribution.py:281-375`.
- Experiments have deterministic assignment and explicit keep/scale/revert decisions at
  `experiments.py:88-177`.

## Material gaps

### 1. The warehouse projection is too coarse

`market_warehouse.py:30-44` rolls up only tenant/date/signal-type/source. That loses SKU, variant,
taxonomy, location, channel, campaign, consent and provenance dimensions. It cannot safely answer
"why did laptop demand rise in Sydney after campaign X while supplier Y's lead time worsened?"

### 2. Runtime DDL and best-effort writes hide data loss

`market_store.py:26-69` and `experiments.py:35-79` still create/alter tables at runtime.
`market_store.py:80-135` converts persistence errors into `False`; `market_warehouse.py:84-151`
converts failures to zero. Those outcomes need metrics/dead-letter records and Alembic migrations,
otherwise an empty dashboard is indistinguishable from no activity.

### 3. ERP ATP and marketing events are not canonical facts

Create separate typed families behind one envelope:

- ATP: material/SKU, variant, plant/location, requested quantity/date, on-hand, committed,
  incoming receipts, safety stock, lead-time distribution, confirmed quantity/date, supplier.
- Marketing: impression, view, search, shortlist, add-to-cart, checkout, purchase, refund/return,
  campaign, creative, channel, attribution window, consent state and deduplication id.

Marketing demand may advise procurement; it must never override ATP/inventory truth.

### 4. Hippograph is evidence-only but not yet experimentally proven

Keep the graph read-only. Materialize taxonomy, workload, freshness and provenance nodes, then run
the same sealed relevance corpus with Hippograph off and shadow-on. Require NDCG improvement with
no constraint, tenant, latency or return-rate regression before any ranking weight is enabled.

## Canonical fact contract

Use an immutable, versioned envelope:

```
tenant_id, event_id, deduplication_id, schema_version
subject_type, subject_id, sku, variant_id, taxonomy_node, location_id
event_type, metric, value, unit, currency, quantity
occurred_at, ingested_at, valid_from, valid_to, window_start, window_end
source_system, source_record_id, provenance_chain
confidence, trust_tier, freshness_policy, consent_state, status
trace_id, decision_id, experiment_id, campaign_id
```

PostgreSQL remains the transactional source of truth now. Do not introduce a new database for the
demo. When retained event volume or dashboard concurrency outgrows Postgres, stream CDC into a
columnar analytical store such as ClickHouse. pgvector and Hippograph remain derived indices, not
authoritative stores. This follows the useful pattern in mature platforms: transactional/profile,
event lake/OLAP and identity/graph are separate projections of governed facts.

## Metrics that affect action

### Buyer funnel

Impression -> product view -> search -> shortlist -> cart -> checkout -> purchase; no-result rate,
refinement rate, stage abandonment, time-to-next-step, assisted conversion and session recovery.

### Recommendation quality

NDCG/precision, constraint satisfaction, coverage/diversity, budget compliance, unknown-spec rate,
fallback/timeout, attach rate, incremental margin, return/complaint rate and correction rate.

### Inventory and procurement

ATP coverage days, stockout rate, fill rate, backorder age, lead-time mean/variance, supplier OTIF,
MOQ exposure, quote response/win rate, forecast bias/WAPE, dead stock and amendment/redraft rate.

### Marketing and retargeting

Incremental conversion/uplift rather than last-click alone; CAC/ROAS, frequency, consent eligibility,
unsubscribe/spam, abandonment age and reason. A retarget proposal must pass consent, frequency,
inventory, margin and experiment gates. Never infer age/demographics for performance ranking.

### Autonomy safety

Proposal -> authorized -> executed -> observed outcome; policy blocks, human overrides, rollback,
stale evidence, provenance failures, quarantine counts, drift and suspected poisoning.

## Poisoning and governance

1. Require tenant, source identity, schema version and deduplication identity at ingestion.
2. Allowlist sources; verify signatures where available; preserve raw immutable lineage.
3. Clamp types/ranges/units and quarantine schema violations instead of coercing them silently.
4. Require corroboration for high-impact demand or competitor claims; robustly aggregate outliers.
5. External facts can propose evidence, never directly rank, price, procure or message.
6. Pass evidence through freshness, taxonomy/SKU scope, capability and inventory clamps.
7. Gate learning on settled outcomes, bounded influence and correction/return signals.
8. Promote adaptations only through sealed shadow experiments with automatic rollback.

## Stress evaluation design

The `75 x 3` run is useful for breadth but not long-context rot. Keep three complementary suites:

- 75 journeys x 3 turns: broad persona/product/phrasing outliers.
- 20 journeys x 10 turns: budget, brand, quantity, cart and subject continuity.
- 14 journeys x 15 turns: abandonment, return/warranty/repair, repeated amendments, RFQ redraft,
  channel preference and stale-session recovery.

Every run must checkpoint per turn and report by family: lane, model mode, fallback, latency,
empty/unauthorized/over-budget products, quantity/budget drift, subject switches, cart mutations,
procurement proposals and unanswered compound questions. Synthetic traffic is not relevance truth;
the sealed human labels remain the quality oracle.

## Ordered roadmap

1. Finish and analyze the checkpointed 75 x 3 run; then execute family-partitioned 20 x 10 and
   14 x 15 runs instead of one uninterruptible process.
2. Human-review the eight current relevance slates; do not mark a model-generated draft as human.
3. Fix IMAGE runtime: selective OCR, one 12 GB deployment profile, bounded per-leg timeouts, and
   canonical slate-only rendering. Re-run the eight-image security/happy-path battery.
4. Add Alembic migrations for market facts, rollups, experiments and retries; remove runtime DDL.
5. Implement the canonical fact envelope and typed ATP/marketing projections in Postgres.
6. Add abandonment/retarget proposals with consent/frequency/inventory/margin gates and a true
   holdout experiment.
7. Run Hippograph off versus shadow-on NDCG and authorize no ranking influence without uplift.
8. Adjudicate the remaining 4 BLOCKER/13 MAJOR V1/V2 diagnostics.
9. Run synthetic shadow, then calendar canary 1 -> 5 -> 25 -> 100 percent for eligible text lanes.
10. Hoist facade dispatch, replace the chat HTTP loopback with a direct service call, relocate all
    delegated lanes, complete IMAGE rollback proof, archive `recommend.py`, and delete it only after
    the rollback window.

## Archive impact if done today

Immediate archive is unsafe. It would remove the functioning IMAGE fallback, risk procurement and
policy/support lane ownership, break callers still using the chat loopback, and eliminate the only
fast rollback before labels/canary are sealed. Continue V2 in shadow/primary-demo for eligible text
lanes while legacy remains a measured fallback. Archive becomes safe only when `recommend.py` has
zero unique behavior, all callers use the facade directly, IMAGE passes live, labels are approved,
and the canary/rollback period is complete.
