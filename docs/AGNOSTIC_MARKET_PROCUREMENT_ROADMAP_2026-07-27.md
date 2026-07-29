# Agnostic Market Intelligence and Procurement Roadmap — 2026-07-27

## Execution delta — 2026-07-29

The reordered work is now materially implemented locally:

- The active V2 compatibility failures were migrated or restored at the
  compatibility boundary. The reference matrix is green (21 tests), including
  price/budget contracts, nested slots, use-case tags, refusal behavior and
  route timing. A fresh rationale-bearing search can no longer be promoted to
  `EXPLAIN` without a prior shortlist.
- Experiment runs, assignments, results and evaluation are tenant-scoped.
  Creation seals a versioned policy containing baseline, target metric,
  eligibility, minimum sample/window, rollback threshold, guardrails and
  terminal policy. Late and cross-tenant outcomes receive no credit. The
  production schema is owned by Alembic migration
  `20260825_tenant_experiment_policy`; experiment services now validate that
  migration-owned schema and no longer issue runtime table, index or column
  DDL. Experiment fixtures apply the migrations explicitly.
- Migration `20260826_communication_lifecycle` and
  `communication_lifecycle.py` provide an append-only, tenant-isolated,
  idempotent projection with legal transition ordering and approved
  fact/template grounding. Connector ingress, buyer reply, supplier outbox and
  Party/case/trace reads are connected. Quarantine records prevented commercial
  effect. Governed fulfillment supplier drafts now register their persisted
  evidence as approved, versioned material-claim references before queueing.
  The older standalone `supplier_communication.py` dispatch is now a frozen
  compatibility-only surface. An architecture test prevents application code
  from calling it; production supplier delivery uses the governed fulfillment
  outbox.
- Migration `20260827_party_identity_authority` records authority, provenance
  and verification time on Party identities. Authenticated buyer principals,
  approved supplier-registry recipients and verified connector senders bind
  automatically inside the authoritative tenant transaction. Legacy or
  request-selected identities cannot satisfy this boundary.
- Decision Trace now exposes five sections while retaining all 14 leaf IDs,
  existing `tracetab` links and leaf-keyed fetch effects. The missing
  `execution` deep link is restored. Audit reads have an eight-second deadline
  and a visible retry/error state. Twelve rendered frontend tests prove every
  leaf remains reachable, legacy deep links (including `execution`) resolve,
  keyboard/ARIA tab behavior works and section/leaf navigation adds no API
  requests. The production build is green. The production-shaped local battery
  is now green against isolated PostgreSQL and Redis: 9 React Playwright
  journeys and three live SPA/security regressions passed. The malicious
  trusted-supplier reply remained visible but could not change quote,
  economics, PO or payment state. Hosted-runner proof remains outstanding.
- Hippograph now returns evidence paths with edge/evidence identifiers,
  observed/effective time, freshness, authority and source health. Temporal
  evaluation excludes future evidence; old/degraded/untrusted and repeated
  actor contributions are bounded. Why and Evidence now render bounded paths,
  edge/evidence identifiers, observed/effective times and degraded-source
  reasons while explicitly labelling Hippograph evidence-only. Independently
  sealed relevance labels remain outstanding.
- A clean PostgreSQL 16 migration reached
  `20260827_party_identity_authority`; downgrade to
  `20260826_communication_lifecycle` removed the three authority columns and
  re-upgrade restored them. The rehearsal exposed and fixed two legacy pgvector
  fallback migrations whose caught SQL errors previously poisoned the outer
  PostgreSQL transaction when `vector` was unavailable.
- Ninety-eight focused experiment/Party/migration tests, 54 communication and
  procurement tests, 12 rendered Decision Trace tests, the 21-test reference
  matrix and the production frontend build pass locally. The isolated
  PostgreSQL/Redis/Celery/browser harness now proves migration, worker ping,
  9/9 React journeys and 3/3 live SPA/security regressions locally. A
  child-written exit-status contract removed a Windows PowerShell process-code
  blind spot. Hosted proof and real shadow-pilot outcome evidence are not
  complete and must not be represented as proven.
- Portable cloud C0 prerequisites are implemented locally. `/healthz` remains
  dependency-free liveness and `/readyz` checks serving readiness; compose uses
  readiness for health. Celery beat now runs behind a token-bound renewable
  Redis lease. Secret, object and model boundaries support optional
  workload-identity Azure adapters while cloud SDK imports are confined to
  provider modules. Every supported LLM result carries explicit model, model
  version, prompt version and policy version fields. Fifteen focused adapter,
  boundary and regression tests pass, Ruff passes, and `docker compose config`
  validates.

### Remaining order after this slice

1. Split and land the mixed worktree as reviewable, ownership-safe commits.
2. Run the same production-shaped workflow on GitHub-hosted runners and retain
   migration, worker and browser artifacts. Local publication is blocked until
   `gh auth login`; the current branch is also 1,155 commits ahead of its
   published counterpart, so its publication delta must be reviewed rather
   than force-pushed blindly.
3. Deploy one minimal Azure core using Container Apps, PostgreSQL Flexible
   Server, Azure Managed Redis, Blob WORM, Key Vault, ACR and OpenTelemetry.
   Microsoft Foundry is an optional certified model endpoint, not the agent
   substrate.
4. After the cloud core is proven, add signed tenant/site/node identity and a
   two-node partition harness. Claim at-least-once transport with deduplicated,
   idempotent effects—not exactly-once replication. The core signs authority;
   an edge may exercise only fresh delegated capabilities within their limits.
5. Obtain one tenant-authorized shadow dataset, seal the baseline and measure
   forecast value added and business outcomes before increasing autonomy.
6. Record the polished demonstration after the UI/browser and deployment gates
   pass. Package a customer-managed Marketplace offer only after its privacy,
   support and publisher-access boundaries are reviewed.

Do not add AKS, MongoDB, TiDB, Kafka, Flink or a read replica without a measured
trigger. Broad feature expansion remains paused until hosted or design-partner
evidence exposes a concrete gap.

## Communication, trace and learning wiring reassessment — 2026-07-29

This section supersedes the older remaining-work order where the two disagree.
The platform does not need another broad subsystem. It needs the existing
observation, communication, experiment, graph and trace boundaries connected
under one tenant-safe contract and proved through the active V2 route.

### Corrected implementation status

- Conversation-to-observation extraction is already live for buyer chat.
  `conversation_fact_observations.py` extracts bounded requirements, exclusions,
  budgets/currencies, pack/UoM preferences, delivery constraints, payment-term
  requests, recurring use cases and refusal reasons. It records provenance,
  confidence, observation time, expiry and `observation_only` authority.
  `chat.py` invokes it after message persistence, and the account timeline can
  display the observations. The missing work is email projection, explicit
  correction/revocation, PII/source-excerpt policy and stronger Party binding;
  this feature must not be rebuilt.
- `communication_observations.py` defines an idempotent tenant/channel/provider
  message observation, but no production ingress or egress path calls it.
  Supplier fulfillment, the durable outbox, connector inbox, buyer status
  messages and chat therefore remain separate communication islands.
- Supplier RFQ drafting is evidence-bound and caged behind fixed templates,
  supplier allowlists, claim checks, evidence identifiers, content hashes and
  approval/send gates. General buyer/customer drafting is not held to the same
  claim-to-evidence contract.
- Procurement already has an authoritative domain state machine and the outbox
  has delivery/retry states. A generic communication lifecycle should be an
  append-only projection of those events, not a second state machine capable of
  overruling fulfillment or delivery truth.
- The Party/account timeline and operator UI exist, but runtime communication
  and procurement paths do not populate `account_activity`. It is not yet the
  promised unified buyer/supplier/decision/outcome timeline.
- Experiment evaluation supports windows, minimum samples, guardrails,
  terminal decisions and automatic reversion. However, `experiment_run` is
  global and governance pulse reads outcomes from a default tenant. Experiment
  ownership, baseline, target, minimum detectable effect, minimum window,
  rollback threshold and terminal policy are not sealed together at creation.
- Hippograph remains evidence-only. Recall returns nodes and scores, not
  provenance paths. Edges lack the metadata needed for time ageing and drift
  analysis. The current distinct-UID poisoning test is not meaningful Sybil
  resistance, and provisional relevance labels still require independent human
  sealing.
- `DecisionTrace.tsx` is a 4,000-line component with 14 flat leaf tabs. It has a
  concrete deep-link defect: `execution` is accepted by the tab type and fetch
  effects but omitted from `_TABS`, so `?tracetab=execution` falls back to
  Events. Audit fetch failure is silently swallowed and is not bounded by the
  shared timeout behavior. Existing React tests do not prove that all 14 panels
  remain reachable or that request counts remain stable.
- The active recommendation compatibility battery currently has 31 passing and
  16 failing tests. Empty-product failures are primarily associated with test
  fixtures that still seed the retired retrieval boundary. Price buckets,
  nested slots, use-case tags, refusal notes, turn intent and route timing are
  also named in the frozen compatibility surface and need explicit adjudication;
  they must not disappear accidentally.

### Reordered delivery plan

#### P0 — Restore a truthful V2 contract baseline

1. Classify each of the 16 failures as one of:
   V2 fixture migration, required compatibility behavior, or frozen V1-only
   characterization. Seed active tests through V2 taxonomy/catalog APIs rather
   than mocking the retired retrieval service.
2. Keep required edge behavior in `recommendation_compatibility.py` and
   `recommendation_core/legacy_adapter.py`. Move intentionally retired behavior
   into immutable characterization evidence with a written reason.
3. Require the focused compatibility battery, archive-import architecture
   tests, parity/golden/security tests and trace persistence tests to pass before
   changing navigation or adaptive learning.
4. Tenant-scope experiment definitions, assignments, observations and terminal
   decisions. Replace runtime experiment DDL with migrations and remove the
   global/default-tenant coupling in governance pulse.

#### P1 — Connect the bounded communication and outcome spine

1. Add append-only communication thread, message and transition records keyed
   by tenant, Party, case, trace, purpose and provider identity. Store content
   hashes and evidence references here; keep raw encrypted evidence in its
   separate custody store.
2. Project production events into that model:
   connector ingress after identity/security/correlation; supplier draft and
   approval; outbox queue/delivery/failure; governed supplier reply; buyer
   status/draft delivery; and buyer chat observations.
3. Derive `proposed`, `approved`, `queued`, `delivered`, `responded`, `expired`,
   `failed` and `superseded` from authoritative domain events. Reject illegal
   orderings and cross-tenant correlation. The projection must never execute a
   purchase, mutate Party truth or release quarantined content.
4. Add a dedicated tenant-scoped read router for communication timelines by
   Party, case and trace. Do not enlarge the fulfillment router with generic
   communication APIs.
5. Introduce one grounded-message contract for buyer and supplier messages:
   every material claim carries an approved fact/template reference, version,
   authority and expiry. Supplier drafting adapts to this contract; it is not
   replaced.
6. Project delivered messages, replies, decisions and measured outcomes into
   the account timeline. Preserve the underlying source event identifiers so
   the UI can navigate back to evidence and Decision Trace.
7. Seal an experiment specification at creation: tenant, baseline, target
   metric, eligibility, attribution window, minimum sample/window, rollback
   threshold, guardrails and terminal decision. Late or cross-tenant outcomes
   must not receive credit.

#### P2 — Reduce Decision Trace to five sections without changing its contract

Use five top-level sections with the existing leaves:

- Decision: Summary, Events, Execution
- Reasoning: Why, Intent, Memory, Complexity
- Evidence & Risk: Evidence, Multimodal, Security
- Commercial Journey: Market Intelligence, Procurement
- Audit & Technical: Audit Trail, Raw

Implement an exported section-to-leaf mapping and derive the selected section
from the active leaf, avoiding a second source of navigation truth. Keep leaf
identifiers, `tracetab=<leaf>` deep links, existing fetch effects and test
selectors. Fix the missing `execution` registry entry, reset stale initial-tab
state when opening a new trace, and route audit loading through a bounded API
helper with a visible error state. Specialist leaves with no data may be hidden
through progressive disclosure, but must remain directly reachable by old deep
links.

The navigation change is green only when tests prove:

- all 14 leaves are reachable through the five sections;
- every old leaf deep link opens the same panel, including `execution`;
- keyboard/ARIA tab behavior works;
- API request names and counts are identical before and after for each leaf;
- empty specialist panels are disclosed predictably rather than silently lost;
- every populated panel answers what happened, why, evidence, uncertainty,
  authority, changed/prevented state and next permitted action.

#### P3 — Make Hippograph visibly evidential, not autonomous

1. Return bounded provenance paths with source edge/evidence identifiers,
   observed/effective times and tenant scope. Display these paths inside Why or
   Evidence rather than adding another top-level tab.
2. Add time-aware edge ageing, maximum graph growth, drift reporting and an
   explicit degraded-source result instead of silently treating graph-load
   failure as no evidence.
3. Seal independently reviewed relevance labels. Evaluate with temporal
   train/test separation, leakage checks, realistic cold-start/lifecycle
   cohorts and multiple seeds.
4. Replace distinct-UID counting with repeated-actor resistance grounded in
   authenticated tenant membership and account/device trust signals. Synthetic
   identities must not create independent evidence weight.
5. Evaluate diversity, margin, availability and safety guardrails. Hippograph
   may continue to retrieve or re-rank evidence in shadow mode; it cannot
   increase procurement authority until a real shadow pilot shows lift without
   guardrail regression.

#### P4 — External proof and publication

1. Run PostgreSQL migration rehearsal and the Redis/backend/worker/storefront/
   admin browser battery in isolated hosted CI with retained diagnostics.
2. Authenticate GitHub, inspect the 1,155-commit local/publication delta, publish
   a reviewable branch and retain CI evidence. Do not represent local-green as
   hosted-green.
3. Obtain one design-partner shadow dataset and seal the V2 baseline before
   evaluation. Measure business outcomes and forecast value added; synthetic
   replay remains contract evidence, not proof of commercial lift.
4. Record a polished 10–12 minute demonstration only after P0–P2 are green. The
   demo should follow one trace across fact provenance, bounded reasoning,
   communication approval/delivery/reply, prevented unsafe action and measured
   outcome.
5. Stop broad feature expansion until hosted evidence or a design-partner
   outcome identifies a concrete gap.

### Required red-to-green test layers

- Unit: extraction expiry/revocation; grounded-claim rejection; communication
  transition legality; experiment policy sealing; path ageing and leakage.
- Integration: tenant isolation and idempotency across inbox, outbox, Party,
  case, trace and outcomes; no observation may mutate authoritative facts.
- Contract: V2 response/compatibility parity and frozen archive evidence.
- React: five-section mapping, 14-leaf reachability, deep links, request-count
  parity, loading/error/empty states and accessibility.
- Browser: buyer decision to supplier draft, human approval, queued/delivered
  projection, governed reply, timeline, trace and outcome; malicious or
  poisoned evidence must leave quote, economics, PO and payment state unchanged.
- Evaluation: temporal leakage, independently sealed labels, cohort/seed
  stability, calibration and guardrail deltas against the sealed V2 baseline.

## Operational grounding and archive update — 2026-07-29

The current no-credential foundation is materially stronger than the older
status sections below:

- inventory projections are now persisted as rebuildable, tenant/source-scoped
  operational read models. They retain raw UoM custody balances, use
  effective-dated governed conversions, quarantine negative/conservation/ATP
  mismatches and expose rebuild status and exceptions in the admin UI;
- supply nodes, bitemporal dependency edges, source mappings, bounded path
  retrieval, contradiction scopes and immutable evidence bundles are
  operational. Grounded hypotheses can produce proposal-only procurement
  options and qualified-alternative RFQ drafts, but cannot enqueue delivery or
  execute procurement;
- multi-seed synthetic cohorts report conditional interval coverage and policy
  utility by archetype, lifecycle, intermittency, lead time and disruption
  regime. All such results remain `simulation_only`; waste is explicitly
  undefined until lot-ageing semantics exist;
- CPSC, World Bank and the pinned USGS MCS 2026 ScienceBase release now have
  credential-free governed fetch paths. Licensing, origin, revision, cache and
  source-health controls are tested. These signals remain advisory and cannot
  establish SKU/BOM/supplier exposure without a dependency path;
- Party merge redirects and direct split reversals are append-only,
  graph-version checked, separately authorized and visible through impact
  previews. Historical observations are never moved or rewritten;
- the active legacy response transaction and supporting catalog, narration,
  fraud, inventory, NQE and context seams have moved behind V2-owned services.
  Exactly one direct legacy import remains:
  `tests/test_recommend.py`, the large frozen characterization suite.
  Production routing remains V2-owned. `recommend.py` is still about 12,400
  physical lines because rollback bodies remain during parity observation;
- a V2 trace defect exposed during extraction is fixed: blocked or unavailable
  compatibility turns now persist the decision identifier that they return;
- 2,953 service tests were collected and executed across eight isolated local
  shards: 2,952 passed and one opt-in live protocol test was skipped. The admin
  component test and production build pass. An empty SQLite database now
  completes upgrade, one-step rollback and re-upgrade to
  `20260823_supply_hypothesis_workflow`.

Remaining work, in dependency order:

1. Decompose `tests/test_recommend.py` into V2 contract tests,
   compatibility-route contracts and frozen characterization evidence. Observe
   the rollback window, remove the legacy router from `main.py`, then delete
   `recommend.py`.
2. Run the existing workflows on GitHub-hosted runners and retain shard,
   migration and browser artifacts. This workstation still lacks an
   authenticated `gh` session, so hosted-green is not claimed.
3. Prove the migration chain and read models on production-shaped PostgreSQL;
   SQLite rehearsal is not PostgreSQL certification.
4. Add lot/expiry ageing so waste and perishable-policy utility become defined,
   then add spend-weighted dependency concentration and multi-UoM aggregation.
5. Automatically project governed supplier/buyer inbox observations into the
   hypothesis workflow while retaining signed tenant binding, quarantine and
   human authorization.
6. Add hierarchical forecast reconciliation, lost-demand/substitution
   estimation, conditional calibration diagnostics, forecast-value-added and
   supplier reliability scoring with proper scoring rules.
7. Run a design-partner shadow pilot using sealed forecasts and real
   order/ATP/receipt/invoice outcomes. Synthetic replay proves contracts and
   discrimination, not commercial lift.
8. Reduce Ruff incrementally by owned subsystem. The changed boundaries are
   checked; the legacy repository-wide baseline is not clean.

## Governed intelligence execution update — 2026-07-29

The previously ordered no-credential work is now implemented locally:

- canonical inventory events project to tenant, variant, location, UoM and
  custody balances. Receipts, quarantine/inspection, releases, transfers,
  returns, disposal, adjustments, corrections and reversals participate in
  conservation. Source ATP and component checkpoints remain immutable;
- forecast models now publish split-conformal interval evidence with explicit
  calibration/evaluation counts, nominal and empirical coverage, residual
  radius, mean width and undefined states. Shadow policy counterfactuals
  compare bounded fill-rate, stockout, waste, margin and working-capital
  utility without claiming causal or execution authority;
- governed, credential-free live adapters now fetch CPSC recall observations
  and World Bank Pink Sheet commodity benchmarks. Fetches are tenant-cached,
  revision-preserving, origin-pinned, licence-aware and grouped for
  contradiction review. CPSC and World Bank protocol paths were exercised
  against their live public endpoints; other registry entries remain
  discovery-only;
- Party/account search, exact-identity timelines and governed merge/split
  proposals are available through tenant-scoped APIs and the admin UI.
  Approval records a disposition only: it deliberately does not execute a
  destructive merge or split;
- the legacy recommendation constraint filters moved behind a V2-owned
  service. Exact direct imports of `src.app.routers.recommend` are down to 15
  test files, and `recommend.py` is approximately 12,435 lines. Production
  routing remains V2-owned, but deletion is still blocked by those
  characterizations;
- a pull-request Ruff ratchet checks changed Python files. The reproducible
  remaining baseline is 603 findings across services/ERP/service tests and
  1,677 repository-wide. A green changed-file gate does not mean the legacy
  repository is Ruff-clean.

Current proof and honest limits:

- 2,925 service tests pass across eight isolated local shards with strict
  non-daemon-thread leak detection. The run found and fixed an
  evidence-orchestrator timeout path whose abandoned executor worker could
  delay process shutdown;
- 61 focused backend tests, all 36 admin tests and the production admin build
  pass;
- the empty-database migration chain reaches `20260819_party_timeline`;
- the synthetic generator still reports, rather than hides, ATP mismatches or
  transient negative custody balances where its daily series omits injected
  events. The projection is currently a shadow/in-memory acceptance surface,
  not yet an operational read model and not a cross-UoM converter;
- public signals are advisory. They cannot prove SKU exposure without a valid
  supplier, BOM, component, location or contractual dependency path;
- Party merge/split execution and fuzzy identity binding are intentionally
  absent;
- hosted GitHub execution is blocked on this workstation because `gh` has no
  authenticated GitHub session. The workflow cannot be truthfully marked
  hosted-green until an operator runs `gh auth login`, after which the branch
  can be pushed and the workflow artifacts inspected.

Remaining work, in dependency order:

1. Authenticate GitHub, push this branch, open a draft PR and run the authored
   Redis/service/browser/Ruff workflows on GitHub-hosted runners. Preserve the
   shard and failure-diagnostic artifacts.
2. Reconcile injected synthetic events into the daily ATP series, persist the
   location/custody projection as a rebuildable read model and add governed
   UoM conversion at projection boundaries.
3. Extend model-specific calibration to conditional coverage and compare
   policies across scenario cohorts and repeated seeds, not a single replay.
4. Add one public-source family at a time only when its licence, revision,
   availability clock, caching and source-health semantics pass the same
   contract. USGS and USDA are the next useful candidates; their registry
   entries are not live-fetch certified today.
5. Add a separate, reviewed execution workflow for approved Party merge/split
   plans with reversible identity redirects and immutable audit evidence.
6. Move the remaining 15 legacy recommendation imports to V2 contracts,
   compatibility-route tests or frozen characterization evidence, observe the
   rollback window, then remove `recommend.py`.
7. Burn down Ruff by owned subsystem under the changed-file ratchet. Do not
   perform an indiscriminate repository-wide auto-fix.

## Canonical replay and supply-risk execution update — 2026-07-29

This no-credential slice is implemented and locally verified:

- deterministic synthetic histories now materialize as tenant-scoped,
  append-only canonical observations for orders, ATP, purchase orders,
  receipts, inspections/quarantine, transfers, returns, invoices and
  reconciliation, markdowns, disposal, adjustments, corrections and
  reversals;
- four configuration-driven archetypes were added: intermittent critical
  spares, perishables/cold chain, bulky freight-heavy goods and irregular B2B
  project items. Product behavior remains parameter-driven rather than
  category-coded;
- acceptance reports expose daily inventory conservation, event ordering,
  canonical referential integrity, latent-demand separation, statistical
  descriptors, causal shock response, lead-time forecast comparison,
  empirical interval coverage and business utility;
- replenishment, supplier scoring, GMROI, shelf velocity and stale-stock price
  proposals run against the replay only with `shadow_only` authority;
- a tenant-scoped supply-risk API and lazy-loaded admin workbench expose
  dependency paths, PESTEL scope, provenance/licence, contradictions,
  freshness/completeness, impact ranges, alternatives and bounded options;
- lifecycle permissions are enforced in product selling and reorder proposal/
  execution boundaries;
- both frontends are code-split. The admin entry fell from about 505 KB to
  49 KB; the storefront entry fell from about 569 KB to 426 KB, with React in
  a separate shared chunk;
- all 2,908 currently collected service tests pass across eight local,
  production-shaped shards with 120-second per-test deadlines and a
  non-daemon-thread leak gate. The run fixed a date-dependent warehouse test,
  a recovered-product slate regression and unbounded executor shutdown;
- the GitHub shard workflow now isolates databases and feature flags, starts a
  real Redis service, retains last-running-test diagnostics and applies Ruff
  to the stabilized boundary.

Red/green interpretation:

- red meant a violated invariant, stale time assumption, cross-shard resource
  collision, leaked executor, or an incorrect product-slate contract;
- green now means deterministic replay, governed non-execution authority,
  isolated shard state and clean worker shutdown under the tested contracts;
- green does **not** certify live market-source fetching, external-provider
  causality, real ERP data, or autonomous procurement performance.

Remaining work, in dependency order:

1. Run the authored workflow on GitHub and preserve the eight hosted artifacts.
   Local sharding is complete; hosted runner behavior is not yet certified.
2. Project every canonical inventory event into a location-level accounting
   replay so transfer, quarantine, return, disposal, correction and reversal
   quantities participate in conservation, not only the generated daily
   on-hand series.
3. Add scenario target ranges and model-specific interval calibration, then
   compare policy counterfactuals for fill rate, stockouts, waste, margin and
   working capital instead of reporting one shadow proposal.
4. Add governed fetch adapters for the public source registry, including
   licence-aware caching, observation timestamps, revision handling,
   contradiction grouping and source-health outcomes. Until then, the
   workbench is a deterministic/configured intelligence demonstration.
5. Add Party/account timelines and governed merge/split proposals, then connect
   supplier observations and buyer requirements to immutable case snapshots.
6. Continue extracting frozen helpers and characterizations from
   `recommend.py`. Production routing remains V2-owned, but the legacy file is
   still about 12,520 lines and 23 test files directly import its module/helper
   boundary, so deletion is still blocked.
7. Address the repository-wide Ruff baseline separately. The declared
   toolchain runs, but the pre-existing broad service/ERP/test scan reports
   618 findings; the CI gate intentionally covers the newly stabilized
   boundaries rather than pretending the legacy baseline is clean.

## Causal supply-intelligence execution update — 2026-07-29

The roadmap is now ordered around proving product exposure before interpreting
external market signals. A commodity price, capacity constraint, recall,
tariff, weather event or macroeconomic release is not SKU evidence by itself.
The system must traverse a time-valid, tenant-scoped dependency path and retain
the assumptions, alternatives, uncertainty and source policy.

Completed in this slice:

- added a governed registry of official external source families with
  publisher, trust tier, licence, permitted use, measurement scope, refresh
  expectation and PESTEL dimensions;
- added durable supply nodes, dependency edges, signal observations, causal
  hypotheses, procurement-option proposals and synthetic replay manifests;
- added bounded impact reasoning that refuses to claim exposure without a
  dependency path and never grants execution authority;
- added supplier-confirmation evidence as a way to strengthen a hypothesis
  without turning supplier text into authority;
- added three configuration-driven supply scenarios without product-category
  branches, plus deterministic 400-day commerce histories with latent demand,
  observed sales, lost sales, inventory conservation, POs, receipts, lead-time
  shocks and cost pass-through;
- changed forecast comparison to evaluate aggregate supplier-lead-time demand
  at every rolling origin and report empirical lead-time uncertainty;
- fixed a supplier-catalog transaction rollback caused by engine-level schema
  inspection on SQLite StaticPool;
- removed fabricated admin KPI comparisons, distinguished unavailable evidence
  from measured zero, reduced procurement polling churn, and made authority,
  provenance, freshness, simulation and shadow states visible in both UIs.

TDD evidence:

- red: the causal market module and commerce-history function did not exist,
  PESTEL scope was undeclared, and forecasting exposed no lead-time evaluation;
- green: 79 focused backend procurement/forecast/inventory/market tests, 33
  admin tests and 183 storefront tests pass; both production builds pass;
- migration: an empty SQLite database upgraded to head, downgraded one
  revision and re-upgraded to `20260817_supply_intelligence`;
- known red: admin and storefront production chunks remain approximately
  505 KB and 569 KB, above the 500 KB warning threshold.

Reordered next work that needs no external credentials:

1. Materialize the synthetic histories through the canonical observation and
   correction/reversal contracts; add transfer, inspection, quarantine,
   returns, markdown, disposal and invoice-reconciliation events.
2. Add scenario acceptance reports for structural invariants, statistical
   fidelity, causal interventions, model discrimination, interval coverage and
   decision utility. Keep every result `simulation_only`.
3. Add tenant-scoped APIs and an operator supply-risk workbench showing the
   dependency path, PESTEL scope, source licence, contradictions, freshness,
   uncertainty, alternatives and bounded procurement options.
4. Replay replenishment, supplier scoring, GMROI, shelf velocity and
   stale-stock pricing in shadow mode; compare counterfactual fill rate,
   stockouts, waste, working capital and margin.
5. Enforce lifecycle permissions at selling and reorder execution boundaries,
   then add Party/account timelines and governed merge/split proposals.
6. Code-split both frontends, run the hosted sharded/browser workflow, and
   continue the remaining legacy `recommend.py` characterization imports in
   parallel.

Live external fetching remains a later connector slice. The current claim is
source discovery, policy governance and deterministic replay—not certification
against live providers or proof that a public signal caused a specific SKU
impact.

## Production-shaped landing update — 2026-07-28

The foundation batch is now split into reviewable commits. Local proof covers
the migration chain, bounded service-suite collection/sharding, runtime
governance, canonical observations, provider-independent communications,
conversation observations, forecast evidence, procurement proposals, buyer
journeys and the worker boundary.

The production-shaped browser stack proved:

- all 179 storefront component assertions and all 29 admin assertions;
- production frontend builds for the storefront and admin;
- all nine serial Playwright buyer journeys;
- the live policy-trace, procurement supersession and malicious
  trusted-supplier regressions;
- before/after invariance for quote, economics, purchase-order and payment
  state after a quarantined malicious reply;
- a real Redis/Celery task delivery plus the bounded retry/recovery tests.

This is local certification, not hosted or external-provider certification.
The new GitHub workflow is authored and locally validated, but still needs its
first hosted run. Gmail, Microsoft 365 and design-partner business feeds remain
deliberately outside the current proof because no external credentials or
authoritative source are available.

The next no-credential delivery order is:

1. Run and stabilize the new browser/worker workflow on GitHub.
2. Move the remaining legacy recommendation characterizations to V2 contracts,
   compatibility-route tests or frozen evidence. Eighteen test files still
   import the legacy router or its legacy test helper directly.
3. Project Party/account intelligence into tenant-scoped APIs, timelines and
   operator views; keep merge/split as governed proposals until reviewed.
4. Enforce lifecycle selling and procurement permissions at their execution
   boundaries.
5. Run forecast, supplier-score, replenishment, GMROI, shelf-velocity and
   stale-stock evaluations in shadow mode against versioned synthetic and
   replayable historical fixtures, preserving explicit undefined states.
6. Add UI disclosure for source authority, freshness, completeness, currency,
   UoM comparability, uncertainty, simulation/shadow status and human gates.
7. Reduce the large storefront/admin JavaScript chunks and then split
   `chat.py` and simplify `main.py` after the identity and communications
   composition roots are stable.

## Foundation execution update — 2026-07-28

The next dependency-ordered foundation slice is implemented:

- connector cursor/checkpoint and ERP outbound state is migration-owned;
- cursor advancement uses compare-and-set and rejects stale writers;
- OAuth tokens are cached by tenant, provider and subscription rather than by
  provider alone;
- connector retries honor bounded `Retry-After`, HTTP attempts share a total
  job budget, outbound rows are claimed atomically and stalled connector jobs
  are reconciled by Celery beat;
- connector results distinguish observed, empty, unavailable, unauthorised,
  malformed and partial outcomes;
- a dedicated browser/worker CI workflow uses separate databases, Redis,
  visible test reporting, per-test backstops and hard job/suite deadlines;
- an append-only authoritative feed contract accepts orders, order lines,
  location ATP, reservations, returns, receipts, invoices, purchase orders,
  inventory valuation and landed cost without directly mutating operational
  state;
- tenant-scoped Party, ExternalIdentity, relationships, observations,
  activities, snapshots and identity-resolution decision storage now exists;
- supplier and buyer communications have a provider-independent observation
  contract whose authority is always `observation_only`;
- product lifecycle transitions are tenant-scoped, versioned, auditable and
  human-approved, with selling and procurement permissions represented
  separately;
- replenishment inputs, GMROI, shelf velocity, weeks of supply and stale-stock
  price proposals have a deterministic shadow-only calculation boundary;
- two more legacy `recommend.py` test imports moved to V2 service contracts.

These foundations do not mean the production integrations are complete. The
remaining delivery order is:

1. Bind connector credentials and subscriptions to authoritative persisted
   tenant configuration. The current token cache is correctly scoped but still
   process-local, and most provider shapes remain scaffolds.
2. Run the new CI workflow on GitHub and fix any production-stack failures; its
   YAML and local constituent suites are validated, but the hosted worker and
   browser jobs have not yet executed.
3. Configure one real design-partner CSV/SFTP feed, add source-specific schema
   mapping and reconciliation, and project only approved observations into
   operational order, ATP and finance read models.
4. Wire authoritative source identities into Party resolution, build account
   timeline/API/UI projections and implement governed merge/split resolution.
5. Project the existing secure inbox/outbox into the generic communication
   observation table, then add purpose, consent, frequency and draft-approval
   policy for buyer communications.
6. Integrate lifecycle permissions with catalog selling and reorder execution;
   derive inventory history from reconciled observations and run the new
   metrics in shadow evaluation before proposing automation.
7. Continue legacy characterization migration. Eighteen test files still
   import the legacy router directly, so deletion remains blocked despite the
   production routing boundary already being V2-owned.

## P0 correctness update — 2026-07-28

The roadmap is now ordered around tenant-safe facts and bounded execution. The
latest correctness slice completed:

- attribution reward and trace-arm lookups are tenant-scoped, including
  adversarial coverage for reused trace and decision identifiers;
- chat consumes the tenant established by the authenticated operator context,
  applies one end-to-end deadline and returns a retryable `in_progress`
  response instead of allowing duplicate callers to wait for roughly 90
  seconds;
- inventory sync persists its run before provider I/O, records unavailable
  sources durably and rejects malformed or non-JSON provider responses;
- supplier anomaly baselines are tenant-scoped and quarantined observations no
  longer enter active stock or product projections;
- the Procurement projection follows an amended order across decision traces,
  preserves the original procurement request identity and passes the live SPA
  supersession regression;
- direct Xero writes are disabled by default, credit notes are drafted rather
  than authorised, and non-JSON provider errors remain observable.

The next execution order is:

1. **Migrations and connector reliability.** Apply and validate
   `20260807_inventory_feed_quarantine`, move the remaining `erp_sync_state`
   runtime DDL into a migration, and replace swallowed cursor/token errors with
   typed connector outcomes. Add cursor compare-and-set, page checkpoints,
   `Retry-After`, token caching by authoritative tenant subscription, total job
   budgets and stalled-job reconciliation.
2. **Production-shaped CI.** Give browser and worker suites isolated databases,
   visible per-test reporting and hard suite/test deadlines. The live
   cross-trace regression passes, but the full Vitest run can keep the process
   alive long after all 179 assertions have passed.
3. **One authoritative read-only feed.** Start with CSV/SFTP or one design
   partner and reconcile orders, order lines, location ATP/reservations,
   returns, receipts, invoices, purchase orders, valuation and landed cost.
4. **Provider-independent communications.** Continue durable observations,
   drafts, approval, correlation, quarantine disposition and synthetic
   transport tests. Real Gmail/M365 activation remains deliberately snoozed.
5. **Account intelligence, not a new CRM.** Add tenant-scoped Party,
   ExternalIdentity, PartyRelationship, observations, activities, rebuildable
   snapshots and governed merge/split decisions. Existing HubSpot,
   Salesforce and Dynamics routes remain adapter scaffolds until native APIs
   and contract tests exist.
6. **Lifecycle and inventory intelligence.** After authoritative history is
   reconciled, add `active -> sell_through -> procurement_blocked ->
   discontinued`, followed by calibrated replenishment, GMROI, shelf velocity
   and margin-floored stale-stock proposals in shadow mode.
7. **Parallel cleanup.** Continue moving legacy `recommend.py` test imports to
   V2 contracts, compatibility-route tests or frozen evidence. Split
   `fulfillment_cases.py`, then `chat.py`; reduce `main.py` after identity and
   communications composition is stable. These refactors do not outrank
   correctness or authoritative data.

Direct Xero execution must remain disabled until it uses proposal,
authorization and a tenant-bound durable delivery ledger. CRM writes remain
out of scope except for future governed proposals to ShopSquire-owned fields.

## Implementation update — 2026-07-28

Completed in the current P0 execution slice:

- inventory reorder execution now accepts only an immutable proposal ID;
- replenishment quantity, supplier, landed cost, currency and lead time are
  derived from canonical facts and a validated tenant-scoped supplier offer;
- human approval is bound to the proposal hash and proposal expiry;
- execution rechecks supplier and replenishment facts before creating a PO,
  treats authorization shadow denials/escalations as blocks, and fails closed
  when data readiness cannot be evaluated;
- an architecture test prohibits production callers from bypassing the
  dedicated reorder execution boundary;
- the supplier outbox and delivery-job ledger are migration-owned;
- `/outbound/process` now returns an accepted Celery job instead of transmitting
  synchronously;
- outbound processing, status, dead letters and acknowledgements are
  tenant-scoped, with bounded batches and a scheduled tenant sweep;
- migrations `20260802_inventory_reorder`, `20260803_outbound_jobs` and
  `20260804_inventory_claims` pass from an empty database and are applied to
  the inspected local database; stale execution claims reconcile an already
  persisted PO instead of creating a duplicate.

Still open after this slice:

- operator tenant identity is still ultimately based on the request tenant
  context and role/ABAC configuration; authoritative per-user tenant membership
  must become a first-class authenticated principal claim;
- the real Gmail/M365 poll worker still needs to enter the durable inbound
  inbox/evidence/correlation/`receive_email_reply()` boundary;
- buyer/customer email needs its own governed inbox and policy;
- provider-shaped and malicious-reply browser round trips remain required;
- authoritative orders, location ATP, returns, receipts, invoices and landed
  inventory valuation remain prerequisites for GMROI or autonomous inventory
  optimization.

## Objective

Build one vertical-agnostic commerce intelligence loop that:

1. observes authoritative market, inventory, order and communication facts;
2. converts them into evidence-backed findings;
3. proposes procurement or customer actions;
4. applies deterministic policy and human/autonomy gates;
5. communicates through durable supplier and buyer threads; and
6. measures the eventual commercial outcome.

The autonomous "brain" is not a larger prompt or a new monolithic agent. It is the typed,
auditable loop below. Models may classify, summarize and draft, but may not invent tenant identity,
availability, price, cost, supplier identity, commitment or execution authority.

```text
authoritative feeds + signed email events
                  |
                  v
 canonical facts and immutable evidence
                  |
                  v
 market findings + case context snapshots
                  |
                  v
 decision proposals (advisory, no side effects)
                  |
                  v
 deterministic policy + confidence + approval gates
                  |
                  v
 durable supplier/buyer communication outbox
                  |
                  v
 acknowledgements, replies, orders and outcomes
                  |
                  +----------> attribution and learning
```

## Non-negotiable domain contracts

Create or consolidate these small shared contracts before adding more agents:

- `CanonicalFact`: tenant, subject, fact type, value, unit/currency, event time, observed time,
  source, provenance, confidence, freshness and quality status.
- `EvidenceRef`: immutable raw reference, sanitized reference, content hash, custody state,
  retention class and access policy.
- `ConversationThread`: authoritative tenant, party type, party identity, provider subscription,
  provider thread/message identifiers, case/order/RFQ references and status.
- `MessageObservation`: direction, sender identity verdict, sanitized content, attachment evidence,
  detected intent, correlation confidence and quarantine state.
- `DecisionProposal`: decision type, facts used, assumptions, alternatives, expected benefit,
  risks, confidence, expiry and required authority.
- `ActionAuthorization`: allow, deny, needs information or human approval, with policy version,
  reasons, limits and approved content hash.
- `OutcomeEvent`: decision reference, action reference, target metric, observed result, attribution
  window and data-quality state.

These are opaque to product category. SKU, supplier, region, channel and use case remain identifiers
or taxonomy references rather than hard-coded laptop, pharmacy or retail vocabulary.

## Phase 0 — Stabilize the execution boundary

**Priority: P0. Complete before autonomy or a rollback observation window.**

### Progress in this implementation slice

- Real caller-visible deadline applied to in-process chat/V2 dispatch, with typed degradation,
  timeout trace evidence and bounded metrics.
- Shared admin API requests now have abort deadlines and caller cancellation propagation.
- `run_async_safe()` no longer re-waits during `ThreadPoolExecutor` shutdown after its deadline.
- Market refresh/state follows request tenant context; pipeline ingestion receives the same tenant;
  scheduled market analysis uses bounded authoritative tenant fan-out.
- Email evidence migrations form one Alembic chain through `20260801_email_ops`; the inspected local
  database is at that head.
- Strict Gmail/M365 subscription-to-tenant binding was confirmed as existing behavior.

1. Protect the current cutover and email work in reviewable commits.
2. Apply and validate the inbound inbox, correlation, evidence and disposition migrations.
3. Derive tenant and buyer identity from authenticated principals or signed connector
   subscriptions. Remove request-body/header-selected tenant authority from production paths.
4. Add buyer ownership checks to case, journey, confirmation and option-selection routes.
5. Enforce real deadlines on chat/V2 dispatch. Return typed timeout/degraded results and record
   timeout metrics by lane.
6. Add abort deadlines to the shared admin API client.
7. Replace the ineffective thread-based async timeout helper with a boundary that does not wait
   indefinitely during executor shutdown.
8. Move `/outbound/process` transmission to a worker trigger; the operator request should return
   an accepted/job response rather than process up to 50 SMTP calls inline.
9. Resolve the `confirm-cart` contract: explicitly distinguish authoritative ATP calculation from
   an operator-approved `source_qty` override.
10. Add per-test timeouts and clean-database fixtures to the critical integration and browser packs.

**Exit gate**

- No unbounded successor-path wait.
- No client-selected tenant or unauthenticated buyer mutation.
- Migrations pass on an empty database and a production-like upgrade copy.
- A stalled dependency produces a measured degraded result rather than a silent hang.

### Buyer identity prerequisite

Do not implement ownership by comparing two client-supplied `uid` strings. Before item 4 can close:

1. authenticated buyers must resolve from a verified bearer/session principal;
2. guest buyers must receive a high-entropy, HttpOnly session or case capability whose hash—not the
   raw token—is stored server-side;
3. the principal must be tenant-bound and case/order-bound;
4. buyer-safe and operator projections must remain separate;
5. production must reject body-only identity, while an explicitly marked demo mode may retain
   compatibility behavior;
6. existing `buyer_uid_hash` rows that contain raw UIDs need a migration/backfill classification
   before the column becomes an enforcement source.

## Phase 1 — Canonical intelligence substrate

**Priority: P0. This is the foundation for both Market Intelligence and Procurement.**

1. Make the canonical fact contract the only input to consequential market/procurement policy.
2. Preserve raw source records separately; adapters normalize them into facts without overwriting
   source evidence.
3. Add source watermarks, reconciliation counts and health states:
   `available`, `empty`, `stale`, `failed` and `quarantined`.
4. Never translate a failed query or missing table into an unexplained zero.
5. Enforce tenant, subject, time, unit and currency compatibility at every fact join.
6. Record explicit missing-data findings instead of filling unknown ATP, landed cost, delivery date
   or margin with defaults.
7. Add schema/version fields to facts, proposals, policies and outcomes.
8. Use migrations for persistent tables; remove production runtime DDL from these paths.

**First authoritative feed slice**

Onboard one tenant end to end:

- orders and line items;
- inventory/ATP by location;
- returns and cancellations;
- supplier quotes and purchase orders;
- goods receipts and invoices;
- landed cost and store settlement currency.

Do not connect five partial systems at once. One reconciled tenant with watermarks is more valuable
than many adapters with no evidence that their numbers match the source system.

## Phase 2 — Governed communication fabric

**Priority: P0/P1. Supplier and buyer communication become evidence-bearing domain events.**

### Supplier inbound

1. Verify Gmail or Microsoft notification identity and bind the subscription to an authoritative
   tenant before reading message content.
2. Deduplicate by tenant, provider and provider message ID.
3. Correlate using durable outbound message/thread mappings and immutable RFQ/case references.
   Subject parsing and UUID extraction are fallbacks, not primary identity.
4. Run a bounded synchronous ingress gate: identity, replay, size, basic content safety and
   correlation. Persist and return quickly.
5. Run OCR, QR, attachment sandboxing, linked-artifact analysis and deeper threat enrichment as
   durable jobs with timeouts, retries and dead letters.
6. Route every production connector through `receive_email_reply()`; retain an architecture test
   prohibiting direct use of the low-level receive function.
7. Classify supplier replies into typed observations:
   - quote;
   - partial availability;
   - substitute offer;
   - delivery/lead-time change;
   - request for information;
   - acknowledgement;
   - invoice/attachment;
   - refusal or no-bid;
   - suspicious/untrusted.
8. A classified message may update a case only after identity, correlation and schema validation.
   Quarantined content cannot mutate quote, economics, PO or payment state.

### Supplier outbound

1. Use one durable communication outbox for RFQs, RFIs, cancellations, PO notices and
   acknowledgements.
2. Bind recipient identity to the approved supplier registry, never buyer/model text.
3. Pin the exact approved content hash and policy decision to every send.
4. Require idempotency, bounded retry, dead-letter handling and delivery/ack status.
5. Keep autonomy level and authority explicit per message type. Autonomous RFQ sending must not
   silently authorize PO, cancellation or payment messages.

### Buyer/customer inbound

Introduce a buyer communication inbox using the same generic thread and evidence contracts, but a
separate policy profile. Recognize:

- requirement clarification;
- commitment/confirmation;
- option selection;
- deadline/address correction;
- change or cancellation request;
- consent or approval;
- complaint, return or damage claim;
- status question.

Buyer identity and case/order ownership must be authenticated. Email text alone must never authorize
payment, a material scope increase or a post-send cancellation.

### Buyer/customer outbound

1. Generate status messages from case state and authoritative facts, not free-form model assertions.
2. Separate safe autonomous notifications from approval-requiring commitments.
3. Approved autonomous messages may state recorded status, request missing information, present
   already-approved options and acknowledge receipt.
4. Prices, refund promises, delivery guarantees, substitutions and changed commercial terms require
   an authoritative fact plus the relevant authorization.
5. Record delivery, bounce, reply and customer response as outcome events.

**Exit gate**

- A real provider round trip is demonstrated for one supplier and one buyer mailbox.
- Malicious trusted-domain supplier mail cannot change commercial state in a Playwright regression.
- Buyer replies cannot cross tenant/order ownership or create an irreversible action from email text.

## Phase 3 — Market sensing and findings

**Priority: P1. Run only after canonical facts and source health are trustworthy.**

1. Remove hard-coded `default` tenant execution from live and scheduled market pipelines.
2. Fan out over a bounded authoritative tenant registry with per-tenant leases and checkpoints.
3. Schedule ingestion and analysis as jobs; operator refresh should enqueue and expose progress.
4. Produce findings for:
   - demand and conversion shifts;
   - stockout and excess-stock risk;
   - supplier lead-time/reliability change;
   - competitor price movement;
   - return/complaint clusters;
   - funnel and buyer-objection changes;
   - cost/margin pressure.
5. Attach evidence references, scope, freshness, confidence and expiry to every finding.
6. Distinguish observed, estimated, simulated, insufficient and unavailable values in APIs and UI.
7. Compare forecasts with seasonal-naive and moving-average baselines before model complexity is
   allowed to influence actions.

**Exit gate**

- Each live finding is reproducible from source facts and visibly distinct from replay data.
- Source failure is visible and alertable.
- Forecast comparison runs on real history with a frozen baseline definition.

## Phase 4 — Procurement decision intelligence

**Priority: P1. Convert findings into proposals, not direct actions.**

1. Build an immutable case-context snapshot containing:
   demand finding, ATP, open orders, buyer requirements, approved suppliers, quote history,
   lead-time reliability, landed cost, margin floor and communication status.
2. Generate typed proposals for:
   - no action;
   - request missing information;
   - RFQ fan-out;
   - reorder quantity/range;
   - supplier choice;
   - substitute option;
   - split fulfillment;
   - expedite;
   - delay or decline;
   - change/cancellation handling.
3. Rank proposals using deterministic feasibility and policy first. Models may explain trade-offs,
   but may not supply missing economics.
4. Preserve alternatives and refusal reasons so the operator can see what evidence would change
   the recommendation.
5. Add proposal expiry and automatic re-evaluation when ATP, price, quote, deadline or trust state
   changes.
6. Keep proposal, authorization and execution as separate records.

**Exit gate**

- Replaying the same case snapshot and policy version produces the same bounded proposal.
- Missing cost, ATP or currency causes `needs_information`, not invented economics.
- Supplier reply updates cause controlled re-evaluation rather than ad hoc state mutation.

## Phase 5 — Bounded autonomy ladder

**Priority: P1/P2. Increase authority only from measured evidence.**

Use explicit levels per action type:

- **L0 Observe:** findings and traces only.
- **L1 Advise:** proposals shown to an operator.
- **L2 Draft:** communication/action draft, no external effect.
- **L3 Execute reversible:** approved low-risk notifications or RFQs within policy limits.
- **L4 Execute consequential:** PO, cancellation, refund or payment; retain human approval until
  separately proven safe and legally appropriate.

Promotion requires:

- minimum sample size;
- acceptable false-action and refusal rates;
- no tenant/ownership violations;
- bounded latency and failure behavior;
- successful kill-switch and rollback rehearsal;
- per-action budget, supplier, category and confidence limits.

Do not use one global "autonomy enabled" switch. Authority is granted to a specific action type,
tenant, policy version and limit.

## Phase 6 — Outcomes and learning

**Priority: P2. This makes the system more intelligent without letting it self-authorize.**

1. Close the loop from findings and proposals to:
   - supplier response rate and time;
   - quote competitiveness;
   - fill rate and lead-time accuracy;
   - stockout and excess inventory;
   - gross margin and landed-cost variance;
   - cancellation/return rate;
   - buyer acceptance and satisfaction;
   - manual override and quarantine rates.
2. Attribute outcomes to immutable decision and action references.
3. Separate policy evaluation from policy changes. Learning produces a proposed policy adjustment;
   governance approves and versions it.
4. Run shadow and controlled cohorts against agreed baselines.
5. Preserve the ability to explain why a proposal changed between two policy/model versions.

## Phase 7 — Recommendation V1 retirement

**Priority: supporting refactor, parallel with Phases 0–2; not the product roadmap's center.**

1. Keep the V2-backed `/recommend/suggest` compatibility router through the sunset/traffic window.
   Rename the `main.py` alias to `recommend_compat_router` for clarity.
2. Fix the V2/chat timeout boundary before observing production cutover.
3. Move the 13 remaining legacy-private-helper tests to V2 contracts, compatibility contracts or
   frozen characterization evidence.
4. Adjudicate remaining reference, follow-up, multimodal/bulk and golden failures.
5. Require zero production imports, zero legacy private-helper test imports, acceptable degraded and
   timeout rates, and a successful artifact rollback rehearsal.
6. Archive/delete `recommend.py`; remove the compatibility route later, only when traffic reaches
   zero or the published compatibility obligation ends.

## Refactoring map

### Refactor now

- Split `fulfillment_cases.py` into thin routers:
  `procurement_cases`, `procurement_buyer`, `procurement_supplier_comms`,
  `procurement_purchase_orders`, `procurement_market` and `procurement_operations`.
- Keep workflow/state transitions in the fulfillment domain, not in routers.
- Extract one communication application layer shared by supplier and buyer channels, while keeping
  separate identity and authorization policies.
- Split email security by concern: connector identity, ingress gate, evidence custody, enrichment,
  correlation, disposition and threat policy.
- Consolidate tenant resolution into authenticated principal/subscription dependencies.
- Replace best-effort empty returns in intelligence paths with typed result/health objects.
- Create one job control surface for accepted/running/retrying/dead-letter/completed state.
- Rename misleading compatibility symbols; do not rename or move stable V2 core modules without need.

### Do not build

- A new all-knowing `BrainAgent` class.
- A shared free-form memory blob that supplier, buyer and market agents can all mutate.
- Direct LLM writes to case, quote, PO, payment or market-fact tables.
- A second orchestration framework before the typed contracts and jobs above work end to end.
- More vertical-specific rules in the agnostic core.

## Recommended delivery slices

1. **Safety and identity slice:** Phase 0 plus provider/tenant binding.
2. **Supplier loop slice:** outbound RFQ → verified reply → quote observation → quarantine/browser proof.
3. **Buyer loop slice:** authenticated status/clarification thread → option response → ownership proof.
4. **Truth slice:** one tenant's orders, ATP, returns, costs, receipts and invoices reconciled.
5. **Intelligence slice:** market findings → procurement proposal → human decision → outcome.
6. **Autonomy slice:** one reversible message type at L3 with limits and rollback.
7. **Retirement slice:** V1 archive after compatibility and rollback gates.

This order concentrates effort on the defensible product: evidence-backed commercial decisions and
governed action. Recommendation parity remains necessary, but it should no longer consume the roadmap
ahead of authoritative facts, communication custody, procurement outcomes and tenant-safe autonomy.
