# Audit and continuity repair checkpoint

This is a partial implementation receipt, not a pilot release certificate. Base: `a0218c26`; changes are uncommitted.

## Implemented

- Added owner/developer authentication to the alternate admin as-of endpoint.
- Added tenant and independent knowledge-time predicates to its service query. With one timestamp, both axes use that instant; an explicit `known_at` selects a different knowledge cutoff. Invalid timestamp syntax returns 422.
- Added tenant filtering to the same service's current replay and causal-event reads. This is not a claim that every audit/export endpoint has been audited.
- Fixed the two reproduced budget-only scope regressions. The existing budget grammar now characterizes a bounded budget-only amendment; residual product/workload/quantity tokens prevent that path from restoring old scope. No application/category aliases were added.
- Strengthened the test oracle with independently supplied current-query, taxonomy and forbidden-question expectations. Mutation tests first proved those defects were undetected.
- Added a separate persisted `buyer_query` to the turn commit/read model. Retained case objective is no longer used as the local trace's current query.
- Labelled historical case objective and selected-turn query separately. Old records without a query say it was not recorded rather than inventing one.
- Strengthened the four-turn browser gate: current query in Summary, no electronics scope or gaming clarification for the chair, laptop scope for bulk turns, existing revision/budget checks and all 15 trace leaves.

## TDD and verification

| Check | Result |
|---|---|
| New audit tests before implementation | 6 failures: unauthenticated access, missing knowledge axis, tenant leakage and missing temporal validation |
| New oracle mutation tests before implementation | 3 failures: wrong category, stale query and inapplicable question went undetected |
| New budget-amendment characterization before implementation | Missing capability failures |
| Current-query commit test before implementation | Rejected undeclared query field |
| Full recommendation brain suite plus amendment cases | **183 passed**, zero failures/skips |
| Audit, bitemporal history and turn projection tests | **19 passed**, zero failures/skips |
| Full frontend suite | **384 passed in 82 files** |
| Frontend production build | Passed |
| Source-size guard | Exit 0; existing warnings remain, ceilings unchanged |
| Git diff whitespace check | Passed |
| Real Chromium four-turn trace journey | **1 passed**, 1.8 minutes, one worker, zero retries |
| Live unauthenticated alternate as-of request | **401**, previously 200 for the same test record |

Only the verified API process was restarted: prior PID 25884, replacement PID 47240, listener 127.0.0.1:8080. The existing recording profile/environment was retained. Frontend, database and Ollama processes were not killed.

Browser terminal results:

| Turn | Current catalog scope | Questions | Shelf count |
|---|---|---|---:|
| PRAGMATA laptop | `el-6-11-2` | None | 0 |
| Chair, explicitly not laptop | `fr-12-2` | None | 0 |
| 10 laptops, AUD 30,000 total | `el-6-6` | None | 0 |
| 12 laptops, same total | `el-6-6` | None | 0 |

The chair outcome was correct in this run. This does not establish that all model-dependent replacement/refinement paths are fixed: the earlier failing live chair output remains a required regression fixture. The new tests will now catch that output. Budget-only model-switch/outage failures are independently fixed by the deterministic tests.

The test checks every trace leaf's navigation, selected Summary query, research counts and history bindings; full semantic assertions for all other leaves remain unfinished. Empty shelves on the workload and bulk turns are not treated as positive delivery.

## Evidence locations

All runtime artifacts are outside Git under `C:/AI/ShopSquire-checkpoints/`:

- `audit-boundary-red.log`
- `oracle-subject-red.log`
- `budget-amend-red.log`
- `turn-query-red.log`
- `continuity-repair.xml` and `.log`
- `audit-turn-green.xml` and `.log`
- `audit-continuity-ui-green.log`
- `audit-continuity-build.log`
- `audit-continuity-browser.log` and `audit-continuity-browser/` trace/video/terminal attachments
- `audit-repair-size.log`

## Still unfinished

1. Audit the remaining decision/export/history entry points for tenant, role and temporal-policy parity; certify against actual PostgreSQL and hosted authentication.
2. Seal the intermittent wrong-subject response as a deterministic integration fixture and finish broad replacement/addition/refinement coverage.
3. Complete OS/architecture/storage and typed CPU/GPU alternatives, scoped fit normalization, reviewed derivations and live qualified-product delivery. No authority gate was lowered.
4. Finish every trace leaf's semantic oracle, loading-state reconciliation and legacy acceptance/retry paths.
5. Diagnose empty bulk delivery, then independently certify budget shortage, stock shortage and explicit draft-only sourcing with durable zero-dispatch proof.
6. Complete independent reviews, market shadow certification, stage ownership/extraction, hosted concurrency and recovery gates.

No source approvals, supplier sends, payments, market-mode changes, commits or pushes occurred. Existing assessment documents remain preserved. Implementation/test changes are intentionally uncommitted pending reviewable checkpoints; no Git reset or cleanup was performed.

## Follow-up: bulk catalog delivery, 11 September

The next live investigation found that the core's continuation guard replaced the
model's explicitly buyer-named Laptops node with the previous chair node. Terminal
scope was corrected later, hiding the retrieval mismatch. A failing integration
fixture now reproduces this exact boundary. The router retains a current named
registry category when the model's continuation signal is uncertain; no category
alias or application list was added.

Verification:

- Recommendation core plus budget-amendment suites: **184 passed**.
- Shared oracle: **14 passed**, including a new red/green regression covering flat
  terminal products and blocked authority. An explicitly empty grouped shelf must
  not fall back to historical flat products.
- Real Chromium, serial worker, zero retries: **1 passed in 2.1 minutes**. Four
  turns, all 15 trace leaves each turn, current query, budget, scope and selected
  history assertions. This is not full semantic certification of every leaf.
- PRAGMATA: four accepted claims, blocked authority, zero products.
- Chair: zero products, no inherited laptop slate.
- Ten laptops / AUD 30,000 total: **10 rendered catalog products**, unit cap AUD
  3,000, no budget shortfall.
- Twelve laptops / same total: **10 rendered catalog products**, unit cap AUD
  2,500, next revision of the same bulk case, no budget shortfall.
- API restarted onto these changes (PID 47240 replaced by 17168), preserving the
  isolated recording profile. No other service was restarted.
- Source-size guard exits zero with existing warnings; ceilings unchanged.

The first strengthened browser assertion was itself wrong: it inspected grouped
research shelves only, while ordinary catalog results use terminal.products. Its
red artifact is retained. Payload and screenshot showed actual delivery. The
corrected gate still unconditionally requires products, rendered content, matching
core/terminal scope and nonblocked authority; it does not skip failed delivery.

Artifacts outside Git: bulk-subject-red.log, bulk-routing-green.xml/log,
bulk-oracle-red.log, bulk-oracle-green.log, bulk-delivery-browser/ (initial test
defect), bulk-delivery-browser-v2/ and bulk-delivery-browser-v2.log (passing run).

Remaining boundaries are substantive:

1. Workload qualification is still blocked: Steam normalization loses additional
   notes, OS and architecture remain conflated, and CPU/GPU alternatives require
   typed comparison and reviewed equivalence rather than substring performance
   assumptions. The synthetic exact-field compiler fixture is not live delivery.
2. Bulk stock evidence is degraded with unknown freshness. The payload reports
   local/network quantities, but narration says availability is current. Catalog
   delivery does not certify those quantities or fulfillment. Fix this evidence/
   narration boundary before claiming stock-shortfall certification.
3. Distinct budget/stock shortages, explicit draft-only sourcing, durable absence
   of dispatch, complete trace semantics, actual PostgreSQL and hosted recovery
   certification remain open. Browser network observation is not durable outbox
   proof. No independent sources or equivalence rules were approved.

All existing dirty work was preserved; this follow-up remains uncommitted.

## Follow-up: stock narration and retained publisher notes

Stock narration now consumes the canonical inventory snapshot. A missing,
degraded, stale or unknown-freshness receipt cannot advertise stock available
"now" or a confirmed transfer. Financial affordability remains separate from
fulfillment availability. The network helper and final stage boundary enforce
the same rule, including paths without a network transfer plan.

Three failing unknown/stale/missing-freshness regressions were recorded before
implementation. Two old tests assumed fresh availability without supplying any
freshness evidence; their expectations were corrected. The fresh/recorded case
retains location-aware narration.

Steam Additional Notes now survive bounded normalization and project to the
existing literal-observation read model with exact publisher spans, observed
disposition and fit_authority=none. A failing source-to-observation test proved
the previous loss. This preserves SSD/architecture context for typed extraction;
it does not introduce a storage parser or accept compatibility predicates.

Verification:

- Fulfillment/economics: 30 passing tests.
- Steam connector/workload compiler: 42 passing tests.
- Full recommendation core/budget amendments: 184 passing tests.
- Real Chromium: one four-turn test passed, 2.1 minutes, serial worker, zero
  retries; all 15 leaves visited with existing query/revision/history assertions.
- Both bulk turns still returned/rendered 10 products and now explicitly said
  current stock and transfer availability are not verified.
- PRAGMATA remains partial, four accepted claims, zero qualified products.
- API restarted from PID 17168 to 44564 for the stock repair. The notes change
  was made afterward and is unit/integration-tested, not yet live-certified.
- Source-size guard and diff whitespace check pass; ceilings unchanged.

Artifacts: freshness-red.log, freshness-green.xml/log, freshness-core.xml/log,
freshness-browser.log and freshness-browser/, steam-notes-red.log and
steam-notes-green.xml/log, all under C:/AI/ShopSquire-checkpoints outside Git.

Still open: typed OS/architecture and CPU/GPU alternatives/equivalence, consumption
of retained notes by governed typed extraction, complete-evidence live product
qualification, full per-leaf trace semantics, distinct shortages and draft-only
sourcing with durable dispatch-absence proof, independent reviews, and hosted
PostgreSQL/recovery certification. No source approvals, dispatch, payments,
commits, pushes or deletion occurred.

## Follow-up: exact fit boundary and real PostgreSQL sourcing acceptance

Found and repaired an additional scope bypass in recommendation_core/fit.py:
`defs={}` was treated like omitted definitions, reopening the union of every
installed vertical. Explicitly empty definitions now stay empty in attribute
normalization, card construction, relaxation analysis and cart fit advisory.
The legacy omitted-definitions path is unchanged and still needs scoped caller
migration; this is not a claim that all fit paths are manifest-pinned.

TDD reproduced a false `meets` result from an empty manifest before the fix.
A separate complete-cited-requirements fixture exercises compiler -> normalized
VariantView -> ProductCard: six requirements, exact CPU/GPU alternatives, OS,
storage type and numeric capacity. Exact inventory meets; unreviewed mobile GPU
equivalence fails; missing inventory specifications remain unknown. This proves
that exact typed alternatives already execute, not that live publisher extraction
or the terminal qualified shelf is complete. No equivalence table was approved.

The full compiler/fit/core/amendment run passed 204 tests. Evidence:
typed-fit-red.log and typed-fit-green.xml/log under the external checkpoints
directory. Architecture ceilings remain unchanged.

The existing isolated PostgreSQL certificate was executed through
scripts/run_tests_postgres.ps1. Migration logs report PostgresqlImpl; the test
requires the actual PostgreSQL dialect and migration head. Result: one passed,
zero failures/errors/skips. Explicit sourcing acceptance created durable state,
was idempotent, and left outbound_message and outbound_delivery_job row counts
unchanged. Automatic drafting was disabled in this test: it does NOT certify an
inspectable supplier draft, distinct budget/stock shortage journeys, or hosted
operation. The unique disposable PostgreSQL container/database was removed by
the runner; application databases were untouched. Receipts are in
C:/AI/ShopSquire-checkpoints/typed-fit-postgres/.

The local API was restarted from PID 44564 to 36108 onto the fit and retained-note
changes using the existing isolated demo profile. Hosted certification still
requires an identified staging environment and deployment authority. Independent
source/compatibility review remains a human gate.

The initial browser rerun after restart failed before execution: direct chat
stream/query requests could not connect and the UI showed Backend unavailable.
The test started before API readiness, then spent 180 seconds waiting for a
terminal answer that could not arrive. That failed zero-retry artifact is retained
in typed-fit-browser/. The test now requires reachable /healthz before loading
the storefront, with a bounded 60-second preflight. This is transport readiness,
not evidence that models, search or production dependencies are ready, and it
does not retry buyer turns.

After the preflight correction, a fresh zero-retry Chromium journey passed in
2.2 minutes (typed-fit-browser-ready/ and .log). The four-turn test retained the
nonempty bulk product and unknown-stock narration assertions and visited all 15
trace leaves per turn. This remains limited to the semantic assertions actually
implemented in that test, not every trace claim. Focused research-summary/oracle
UI tests: 16 passed (typed-fit-ui.log). The expanded empty-manifest regression
also passes for direct normalization, relaxation and cart advisory entry points.
