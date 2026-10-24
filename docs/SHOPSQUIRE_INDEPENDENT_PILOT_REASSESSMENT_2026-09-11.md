# ShopSquire: independent platform assessment and pilot release roadmap

## Executive assessment

**ShopSquire has useful working subsystems, but it is not yet certified for an assisted-recommendation pilot.** The immediate blockers are audit access control, purchase-subject continuity, incomplete evidence-to-fit delivery, and a test oracle that permits incorrect journeys to pass. Adding a general agent loop, another RAG subsystem, or more application-name rules is not the next repair.

This assessment covers HEAD `a0218c26`, including implementation checkpoint `2f1592f2`. Source inspection, fresh tests and real browser journeys were performed against the running local stack. It is a targeted call-path review, not an audit of every repository line. No source approvals, cart mutations, supplier sends, payments, configuration changes, restart, implementation edits or commits were performed. Chat tests created local test conversations. Only this assessment document was added.

The most important corrections to the supplied report are:

1. Literal CPU/GPU requirements **already compile**. Fresh BG3 and PRAGMATA outcomes have four accepted claims and specifically lack `os` and `storage_type`. CPU/GPU alternatives and compatibility remain a separate unresolved problem.
2. A passing four-turn browser test **still contains a wrong chair outcome** and stale trace query text. Passing revisions and tab visibility are insufficient.
3. Bitemporal support is real on one query path, but the separate admin as-of path is neither equivalently filtered nor adequately protected at its route boundary. An unauthenticated local request returned a test decision.
4. The guarded-stage runner records failures; it does **not** guarantee that a failed stage cannot damage an existing shelf.
5. Market intelligence and RAG must be assessed by entry point and effective execution. Neither absence from chat's import graph nor absence of a launcher flag establishes platform-wide nonexistence.

## 1. Independent execution results

| Check | Fresh result | What it establishes |
|---|---|---|
| Complete `test_recommendation_core_brain.py` | 173 tests: **171 passed, 2 failed**, zero skips | Both reported budget-only scope regressions reproduced |
| Selected RAG, temporal, HippoGraph, market and workload suites | **117 passed**, zero failures/skips | Local subsystem contracts pass; not live deployment certification |
| Real Chromium: continuity/history plus unresolved-purchase suite | **4 passed, 1 failed**, 2.8 minutes, one worker, zero retries | Positive BG3 delivery remains red; other test assertions passed |
| All trace leaves across four turns | 15 leaves clicked per turn | Navigation works; saved content exposes semantic defects despite passing assertions |
| Positive BG3 delivery | accepted 4, missing OS/storage type, partial, blocked, no shelves | Live requirements reach the terminal, but no qualified delivery |
| PRAGMATA turn in continuity journey | accepted 4, missing OS/storage type, partial, blocked, no shelves | Same delivery boundary fails for another identity |
| Approximate budget and continuation | Existing browser assertions pass | Literal 3,000 anchor retained, no automatic stretch in tested outcomes; does not prove useful inventory delivery |
| Held Emulate3D to RAID request | Existing boundary assertions pass | This specific held-evidence isolation case passed today |
| Admin as-of GET without credentials | **HTTP 200**, returned own test decision fields | Reproduced local audit disclosure; fix before exposing the service |
| Stage mutates products, then throws | Empty products remain; stage records `error` | Guard does not restore pre-stage state |
| Source-size guard | Exit 0, many warnings | Existing ceilings satisfied, not architecture debt eliminated |

Evidence is preserved outside Git:

- `C:/AI/ShopSquire-checkpoints/reassessment-brain.xml` and `.log`.
- `C:/AI/ShopSquire-checkpoints/reassessment-subsystems.xml` and `.log`.
- `C:/AI/ShopSquire-checkpoints/reassessment-browser.log`.
- `C:/AI/ShopSquire-checkpoints/reassessment-browser/`: screenshots, videos, trace ZIPs and attached terminal/panel records.

The tested browser files are `live-turn-trace-continuity.spec.ts` and `live-unresolved-purchase-boundary.spec.ts`. No new browser retries were introduced. The tests were run unchanged, which makes their blind spots observable rather than hidden by new assertions.[^1]

The active health response reports `demo_v2`, external search enabled/configured/effective/live, but `probe_attempted=false`, `reachable=null` and null last-success fields. Those flags are capability declarations, not proof that every search provider works. The browser's live preflight test passed its `cached=false`, `live_allowed=true` and literal CPU/GPU assertions. **That verifies the structured-provider path; it does not certify arbitrary open-web discovery.** A rotating unfamiliar-query discovery gate remains necessary.

## 2. What is right, overstated or incomplete in Claude's report

| Report claim | Independent assessment |
|---|---|
| Two budget-only scope regressions | **Confirmed**, including exact test names and `None != el-6-6` failures |
| BG3 cannot deliver a qualified shelf | **Confirmed in fresh browser execution** |
| No workload journey can ever qualify | **Not proved** by these examples. State the tested failure and missing compatibility capability, not a universal result |
| CPU/GPU predicates cannot compile | **Incorrect as written**: exact cited strings compile; splitting alternatives and proving equivalence are unfinished |
| No observe/replan agent loop | Reasonable description of the main turn shape; absence of one chain entry is not proof of absence of retries throughout the system |
| Guarded stages cannot corrupt a shelf | **Incorrect guarantee**; a failure after in-place mutation leaves the mutation intact |
| DAG scheduling is the highest-value next work | **Not now**. Shared mutable outputs and model resource limits must be controlled before parallel scheduling |
| Bitemporal quad proves trace works | Quad proves fields exist. The two-time history tests give stronger evidence; the separate as-of endpoint exposes an important gap |
| FAQ/graph modules absent from chat are missing capabilities | They have other entry points. Reachability must be measured separately from route registration, invocation and buyer delivery |
| Market intelligence is a one-line enablement | A flag can enable a branch, but does not certify ingestion, worker flags, findings, provenance, privacy, commit success or consumer wiring |
| Chair switch is camera-safe | **Not generally reproducible**: today's passing continuity test retained Gaming Laptops for the chair request |
| Remaining work is mostly polish | **No**: unauthenticated audit access, wrong purchase scope, incomplete fit, concurrency and deployment proof are correctness/security work |

The supplied report is useful as a defect inventory and hypothesis set. Its grade labels and effort estimates should not be treated as release evidence.

## 3. Newly verified defects and immediate scrutiny

### 3.1 Audit access and temporal semantics: release-blocking

`decision_time_travel.py:7` exposes `/api/v1/admin/decisions/asof` without a route-level role dependency. Its helper, `decision_replay.py:28`, filters valid time and decision ID, not tenant or system/knowledge time. Router registration adds no dependencies. A no-credential GET for a decision created during this assessment returned HTTP 200 and fields including `input_data`, `retrieved_context` and `proposed_action`. No unrelated customer's record was accessed.[^2]

Admin MFA is not a substitute for authentication: `admin_mfa.py:35` applies additional checks to recognized privileged roles, then otherwise falls through. The route must independently reject unauthenticated callers. Production exposure was not tested; the missing route boundary is visible in code.

In contrast, `decisions.py:206` filters `tenant_id`, `valid_at` and `known_at`. Its retroactive correction regression passed. The correct conclusion is **uneven temporal-query implementation**, not “bitemporal is absent” or “bitemporal is certified.”[^3]

Repair through one existing tenant-scoped audit query boundary:

- Authenticate and authorize every audit read, export and replay entry point.
- Require tenant scope independent of possession of an opaque decision ID.
- Keep `valid_at` and `known_at` distinct; document valid-time-only endpoints honestly or migrate them.
- Keep original historical policy evaluation separate from replay against today's policy.
- Test unauthenticated, wrong-role and wrong-tenant requests, plus late corrections and equivalent time zones.

### 3.2 Purchase scope is still wrong in a passing journey

The fresh sequence was PRAGMATA laptop, chair, 10 laptops/30,000 total, then 12 laptops/same total. In revision 3:

- `canonical_facts.buyer_query` is the explicit chair request, including “not a laptop.”
- `catalog_scope.selected_taxonomy_root` remains `el-6-11-2`.
- `requested_product_form_factor` remains `Gaming Laptops`.
- The pending question says the $400 budget is below a $1,919 gaming floor.

This is an actual wrong purchasing result, not cosmetic trace wording. The test passes because its oracle checks budget and revision but not the expected category and applicable question. The core's prior-scope branch also independently fails both budget-only amendment regressions.[^4]

Fix the existing transition boundary, preserving two complementary rules:

1. A proven commercial-only amendment retains its prior purchased subject even when the model fails.
2. A new purchased subject suspends incompatible scope and obligations even when the replacement catalog node is unresolved.

Do not restore scope merely because an amount appears in the utterance: “a chair under 400” also contains a budget. Use the existing typed subject role, transition, authored facts and resolved taxonomy. Carry the same resolved scope into retrieval, fit, persisted state and projection. Never make the terminal scope only a cosmetic correction to an earlier wrong retrieval.

### 3.3 Trace identity is consistent while trace meaning is stale

The continuity test's revision and trace IDs passed, but summaries for the chair and bulk turns display the original PRAGMATA question. The local projection fallback in `DecisionTrace.tsx:1035` uses `localTurnProjection.objective` as `input_query`; summary renders it at line 2427. A retained case objective is not the current buyer utterance.[^5]

History intentionally displays a persisted objective. That can be legitimate, but it must be labelled **case objective**, alongside the selected turn's actual query and purchased subject. Current actions must bind to the current operation, not the history selector.

Other captured content includes:

- “Legacy Or Unrecorded” in Summary while Execution shows actual model/gate stages.
- “Loading the procurement case…” captured as acceptable nonempty content.
- Market “Connector health: Loading” alongside absence claims.
- Complexity identifying “rag” inside PRAGMATA as a technical term. This is an observer-quality issue, not evidence that the workload requires RAG.

The current loading assertion matches `Loading ...` with three literal dots; it does not exclude all loading states or the ellipsis character. This is why meaningful leaf-specific assertions matter more than tab visibility.

### 3.4 Evidence compilation and compatibility are distinct stages

The current path is:

`Steam document → retained literal fields/spans → scoped compiler → accepted predicates → inventory evaluation → terminal completeness/authority → UI`.

The Steam parser retains CPU/GPU/OS lines, but no `storage_type` extraction from Additional Notes. The compiler builds exact `in` predicates from full cited CPU/GPU strings. It does not yet split those strings into independently cited alternatives. The electronics manifest requires six attributes and its OS enum does not represent the observed Windows 10 requirement. These are concrete representation gaps.[^6]

Repair order:

1. Preserve the complete source representation and stable content hash; retain additional notes and span coordinates.
2. Separate OS family/version from CPU architecture. “Windows 10 64-bit” is neither simply “Windows 11” nor a performance equivalence.
3. Represent generic SSD separately from SATA/NVMe. Do not invent a storage interface.
4. Propose typed CPU/GPU alternatives with a span for each alternative, preserving OR/AND and conditional tiers.
5. Evaluate exact identity first. Use reviewed, versioned relations for performance or platform compatibility, including desktop/mobile distinctions and applicability limits.
6. Compute completeness against the scoped manifest and applicable requirement tier; then evaluate candidate compatibility separately.

An independent reviewer cannot repair missing extraction/wiring merely by signing a source. Conversely, code cannot create human review authority. These are separate deliverables.

The compiler rejects derived claims at `requirement_compiler.py:87`. Reuse the existing claim/review/provenance boundaries to support approved derivation receipts; do not create a second shadow compatibility engine. A receipt needs input claim IDs, rule/version, review scope, reviewer, timestamp, output predicate and expiry/invalidation lineage.

### 3.5 Scope is pinned in compilation, but not uniformly in fit

`fit.py:46` still defaults to `defs_union(DEFAULT_VERTICALS)` and line 55 applies `derivations_union(DEFAULT_VERTICALS)`. Several core callers invoke `build_cards` without definitions. Even callers passing scoped definitions still use the global derivation list through `variant_attributes`.[^7]

This is a source-level boundary concern, not a demonstrated pharmacy leakage incident in this run. Before publishing more category manifests, pass one immutable scope and its definitions/derivations through all fit paths, including prior-shortlist reuse, relaxations, floor computation and broad retrieval. Otherwise compiler scoping and product normalization have different policies.

### 3.6 The stage guard is observational, not transactional

A direct diagnostic started with one product, cleared products inside a stage, and raised an exception. The resulting response had no products and an `error` stage receipt. `_msg_priority` is measured only to record `won_message`; it does not restore state.[^8]

Do not add parallel execution over that shared mutable response. First make stages return typed artifacts or patches, validate them, then merge once under explicit ownership rules. A failed optional stage should contribute a failure receipt without partially mutating the accepted result. A failed critical stage must not be converted to an apparently successful turn.

The main pipeline need not become an open-ended agent loop. A bounded missing-attribute retrieval step can be useful **after** distinguishing absent source evidence from compiler rejection and incompatible inventory. Retrying the web for an already retrieved Windows 10 line does not fix the enum.

## 4. RAG and intelligence: what exists and what to use it for

| Capability | Actual implementation/entry point | Appropriate use and remaining proof |
|---|---|---|
| Structured catalog retrieval and fit | Recommendation core, taxonomy/candidate sets and attribute registry | Exact inventory, commercial constraints and compatibility. Not replaceable with embedding similarity |
| External evidence retrieval | Enrolled connectors and governed open-world research | Discover identity and cited requirements; provider freshness, parsing and product delivery are separate gates |
| FAQ RAG pipeline | `agentic_rag_pipeline.py`; `/api/v1/query` opt-in branch | FAQ plan/retrieve/rank/inject/decide/verify with citation/cache contracts. It is not a missing hardware-requirements engine |
| Semantic retrieval | `semantic_search.py:42` calls dense-index helpers | Candidate recall for text; record actual embedding/backend/fallback. Null trace context does not prove retrieval never ran |
| Temporal governance | Temporal authority, cache dependency/invalidation and history queries | Time-bounded validity and invalidation. Some `temporal_authority` code is operational response/calendar logic, not document retrieval |
| HippoGraph | `hippograph.py`, DB projection, feedback and read-only routes | Tenant-scoped entity/relationship recall using spreading activation; proposals only, not independent factual or fit authority |
| Generic graph adapter | `graph_retrieval.py`, graph router | Memory/Neo4j adjacency infrastructure, including account/device/IP relations. Not automatically GraphRAG over publisher documents |
| Market intelligence | Batch signal pipeline, analysis/findings, facade intelligence stage, operator consumers | Read-only evidence and later measured advice. Not an external requirements source or permission to qualify products |
| Cohort market projection | `hippograph_market_projection.py:76` | Small-cohort suppression and tenant-scoped aggregate output; not proof of validated demand forecasting |

The repository's HippoGraph is a custom implementation. Its name and PageRank-like recall do not establish that a published HippoRAG architecture or benchmark has been reproduced. Likewise, “TemporalRAG” should describe a measured retrieval contract: retrieve evidence applicable at a valid time **and** available at knowledge time, with source/corpus revisions and no future leakage. It does not require inventing another pipeline.[^9]

The fresh 117-test suite supports the local implementations, including FAQ citations, HippoGraph behavior, market scoping and temporal cache lifecycle. It does not demonstrate which branches execute under every running worker's configuration.

### Market intelligence roadmap

The existing facade calls `run_intelligence_stage`; its market mode is controlled by `HIPPOGRAPH_FEEDBACK_ENABLED`, with distinct off/shadow/live handling. Batch analysis and ingestion have separate `MARKET_ANALYSIS_ENABLED` and `MARKET_PIPELINE_ENABLED` gates. The local flag loader accepts environment overrides. Therefore launcher text alone is not an effective-mode audit.[^10]

Today's trace shows some observed aggregate/cohort projection content and internal-only procurement market text. That contradicts a blanket “all market panels are dark” claim, but does **not** prove live external market findings are consumed.

Before enabling a buyer-affecting mode:

- Expose effective API/worker modes, last successful run, input count, persisted count, age and safe failure codes.
- Prove `signal → finding → persisted history → scoped recall → trace` for the selected tenant.
- Keep simulated/replay data distinguishable from observed and licensed external data.
- Check cohort privacy, tenant isolation, source licence, time of availability and confidence calibration.
- In shadow, prove product eligibility, price, qualified ranking and commerce permissions are unchanged.
- Test database failure truth. `market_pipeline.py` catches commit failure while retaining calculated counts; a returned `persisted` count must not certify a durable commit.
- Evaluate forecasting on time-separated data and measure error, calibration, coverage and freshness; evaluate graph recall against useful reviewed evidence, not merely conversion reward.

The first pilot should keep external market intelligence advisory/shadow. It must not block resolving the buyer's actual purchase or inflate demand-based urgency.

## 5. What green must mean

**Green = correct buyer outcome AND cross-surface consistency AND durable/security evidence, on an identified build and profile.** A truthful refusal is necessary for incomplete evidence; it is a failed buyer-delivery result when the promised complete-evidence scenario should be supported.

Use an independent scenario oracle. Expected purchase type, budget, quantity, evidence applicability and inventory result must come from authored test facts—not from the same terminal object being checked. Test the oracle with deliberately wrong outcomes. The current oracle omits expected taxonomy and question relevance; its positive delivery check is optional.[^11]

### Test layers and required assertions

| Layer | Required red-to-green proof |
|---|---|
| Unit | Currency spans never become quantities; OS/architecture distinct; SSD not NVMe; alternatives preserve spans; reviewed rules do not expand outside their scope |
| Contract | Same tenant, purchased subject, workload IDs, manifest revision and claim dispositions through compiler, fit and terminal; no aggregate count substitutes for claim receipts |
| Integration | Budget-only amendment with model switch/outage retains scope; chair replacement clears gaming obligations; approved evidence reaches fit exactly once |
| Browser correctness | Explicit expected category and query after every turn; complete authorized evidence plus demonstrably matching stock yields products; incompatible/held/partial evidence cannot qualify |
| Browser consistency | Chat, shelves, questions, review controls and every trace leaf agree with the selected operation/revision and receipts |
| Race/failure | Late response, expired evidence, double click, stale confirmation, model timeout and provider failure leave one correct current outcome |
| Durable boundary | Draft acceptance writes the expected draft and no outbound/dispatch/payment records; request replay is idempotent |
| Deployment | Clean build, real PostgreSQL dialect/migration head, hosted auth/tenant isolation, concurrency, restart/recovery, audit export and restore evidence |

Positive delivery requires a reviewed inventory oracle too. A large budget alone does not establish that a specific SKU genuinely matches the publisher's CPU/GPU/OS requirements. Keep two gates: exact controlled evidence/inventory integration, and a real-model/live-source buyer journey. Neither replaces the other.

### Every Decision Trace leaf needs a semantic assertion

| Leaf | Required expected content |
|---|---|
| Summary | Current turn query, purchased subject, trace ID, operation/revision; retained objective separately labelled |
| Events | Relevant executed events, ordered IDs/timestamps; distinguish synthetic display rows from persisted execution |
| Execution | Real stage statuses and timings; critical failure visible; no invented legacy owner during hydration |
| Research | Unique applicable parsed/held/accepted/rejected claims, source and rule provenance, missing obligations |
| Why | Exact displayed configuration and compatibility verdict; no explanation from an old slate |
| Intent | Purchased item versus workload, negation, subject action and semantic source/fallback |
| Memory | Which facts were retained/cleared and why; missing telemetry is not “no memory used” |
| Complexity | Measured model/queue/deadline evidence; observer features must not imply authority |
| Evidence | Source spans, revisions, scope and dispositions agree with requirement cards |
| Multimodal | Present evidence or explicitly not applicable; no stale attachment inference |
| Security | Executed URL/policy controls or explicitly unassessed; absence is not a passed check |
| Market | Effective mode, source age, provenance, privacy status and applied=false in shadow |
| Procurement | Budget versus stock shortfall, draft lineage and human-only next action; resolved loading state |
| Audit | Selected historical query/objective, tenant, valid/knowledge time, immutable reference; no effect on current controls |
| Raw | Same operation/revision and redacted envelope; no credentials or cross-tenant data |

Do not check simply that all leaves contain text. “No explanation available,” a loading message and a stale PRAGMATA query all satisfy a nonempty assertion.

### Permanent journey set

Retain exact regressions, then add a rotating seed-recorded set of unfamiliar official identities. Include:

- Laptop → budget only with model available, unavailable and incorrectly switching.
- Laptop/game → chair with negation → laptop bulk purchase.
- Held workload → unrelated storage purchase; addition versus replacement versus refinement.
- Mainstream live requirements; unfamiliar title; ambiguous title; fabricated-title negative; future release/incomplete requirements.
- Relevant and irrelevant URLs, credentials/private IP/redirect attempts, provider timeout and zero-yield parsing.
- Complete evidence with matching SKU; complete evidence with incompatible SKU; held evidence; expired approval.
- Budget shortage with adequate stock, stock shortage with adequate money, and mixed shortage.
- Explicit draft-only sourcing acceptance and durable zero dispatch, separately from browser network absence.
- Authority downgrade, out-of-order completion and stale historical/review controls.

Zero Playwright retries and a recorded build/profile/tenant are mandatory for certification. Expected failures remain red in the certificate; do not skip shelf assertions when accepted claims unexpectedly become zero.

## 6. Reordered implementation roadmap

### P0-A: close audit access before wider exposure

Consolidate as-of/replay reads into the tenant- and role-scoped query boundary. Add unauthorized and cross-tenant tests before fixing. Exercise valid time and knowledge time independently. Audit all route registration paths, not just the primary decisions endpoint.

**Green:** no-credential and wrong-role callers cannot read records; tenant B cannot read tenant A with a known ID; retroactive history returns the correct version at both cutoffs.

### P0-B: repair the oracle and current-subject boundary together

Add expected taxonomy, purchase/workload separation, current-query and question-applicability assertions to the shared oracle. Seal today's chair payload and both budget-only regressions. Repair existing core/case transition logic; do not add a chair/RAID/application alias table.

**Green:** the same four-turn journey passes semantic assertions, not just revision checks; commercial-only refinements retain appropriate scope under model failure; genuine replacements do not.

### P0-C: finish one scoped evidence-to-fit path

Preserve cited OS/architecture/storage observations, typed alternatives and source representation. Pass scoped manifest definitions and derivations through every fit path. Count claims from unique applicable disposition receipts, not legacy aggregate maxima. Retire resolved questions by obligation ID.

**Green:** controlled exact-match evidence delivers inventory; missing/held/incompatible cases stay restricted; live positive delivery passes without relaxing the manifest. Reviewed equivalence is independently approved where needed.

### P0-D: make terminal projection authoritative in meaning as well as IDs

Use current buyer query separately from retained case objective. Derive counts, questions, authority and shelf IDs from one terminal projection. Legacy actions and trace hydration must not infer success/absence from incomplete loading data.

**Green:** all 15 leaf semantics and buyer surfaces match, including authority downgrade, old-response arrival and history navigation.

### P1-A: certify procurement outcomes separately

Budget shortfall and stock shortfall need different quantities, explanations and buyer actions. Use live current ATP plus controlled shortage fixtures. Explicit acceptance creates an inspectable draft; supplier dispatch remains off. Prove outbox/transport absence durably. Before real sending, enforce requester/approver separation and atomic spend reservation under concurrency.

**Green:** budget gap, local stock, transferable stock and true supplier shortfall reconcile; duplicate acceptance is idempotent; no dispatch or payment occurs.

### P1-B: improve evidence discovery and bounded recovery

Pass canonical publisher/product/version identity into candidate evaluation. Treat ownership relevance as a prerequisite, not a score that keyword-rich aggregators can outvote. Ask for clarification below the identity margin. Bind retries to approval/scope lineage. Distinguish source missing, parser rejected, policy held and stock incompatible before deciding to retry.

**Green:** unfamiliar identities work without name-specific patches; wrong sequel/editor/aggregator candidates cannot gain authority; one bounded targeted retry improves eligible gaps and stops predictably.

### P1-C: establish stage ownership, then extract

Replace in-place optional-stage mutation with validated typed artifacts/patches and explicit criticality. Record queue, execution and cancellation times. Only then consider parallel independent I/O or DAG scheduling. Keep one logical core execution and one terminal commit; bounded internal provider retry is not turn redispatch.

**Green:** mutation-then-error tests cannot damage prior accepted results; cancellation stops downstream work; independent stages cannot race shelf ownership. Architecture ceilings remain unchanged.

### P2: reviewed data and measured intelligence

Publish reviewed manifests and exact inventory with revision/freshness policy. Add packaging and cross-category isolation before expanding beyond electronics. Enable market/HippoGraph only in an explicitly selected shadow profile after ingestion and provenance gates. Reuse existing FAQ, graph and temporal modules where their contracts are relevant; do not wire every module into chat for the sake of an import graph.

**Green:** category-specific completeness and units; no cross-category derivations; graph/market results are scoped, measured, advisory and time-correct.

### Release: hosted, recovery and operational ownership

Run clean-checkout tests, real PostgreSQL migration and row-lock concurrency tests, then hosted browser/failure-injection certification. Verify backups by restoring them, and audit immutability by attempting prohibited modification under deployed retention policies. Record effective API/worker flags and last successful full-contract calls, not string presence in a launcher.

**Green:** reproducible build and evidence bundle, named support/rollback owner, successful recovery, no unreviewed sources promoted, no unsupported claims of WORM or hosted certification.

## 7. Implementation navigation: files and current anchors

These are reviewed entry points and proposed change boundaries, not a claim that every line has been audited.

| File:line | Role / next action |
|---|---|
| `src/app/routers/decision_time_travel.py:7` | Authenticate/authorize the alternate as-of route |
| `src/app/services/decision_replay.py:28` | Add tenant and explicit knowledge-time semantics through shared query logic |
| `src/app/routers/decisions.py:206` | Existing tenant/two-time query to reuse and test |
| `src/app/security/admin_mfa.py:35` | MFA is additional to route authentication, not a replacement |
| `src/app/bootstrap/admin_access_router_group.py:23` | Audit router registration/dependency coverage |
| `src/app/services/recommendation_core/core.py:329` | Budget-only prior-scope restoration defect |
| `src/app/services/case_catalog_candidates.py:205` | Category-change detection and governed candidate scope |
| `src/app/services/case_catalog_candidates.py:218` | Carry the validated current purchase scope into candidate construction |
| `src/app/services/turn_transition.py:43` | Existing commit contract; keep current query, retained objective and applicability distinct |
| `src/app/services/connectors/steam_requirements.py:258` | Preserve notes and typed source fields without inventing compatibility |
| `src/app/services/recommendation_core/workload_grounding.py:69` | Connector-to-compiler adapter and scoped literal receipts |
| `src/app/services/recommendation_core/requirement_compiler.py:41` | Scoped units/operators/spans and derivation authority |
| `data/attributes/electronics.json:6` | Required attributes; OS representation around line 320 |
| `src/app/services/recommendation_core/fit.py:40` | Remove implicit cross-vertical definitions/derivations from scoped paths |
| `src/app/services/research_outcome.py:217` | Receipt counting; remove ambiguous legacy aggregate precedence after parity tests |
| `src/app/services/terminal_research_reconciliation.py:30` | Resolve question obligations by applicable identity/requirements |
| `src/app/services/terminal_research_narration.py:33` | Narrate current terminal truth, not case-wide held counts |
| `src/app/services/open_world_research_discovery.py:98` | Candidate scoring currently awards path/title keyword bonuses |
| `src/app/services/recommendation_core/stage_runner.py:10` | Define artifact ownership and failure semantics before DAG work |
| `frontend/src/components/DecisionTrace.tsx:1035` | Hydration currently substitutes case objective as query |
| `frontend/src/components/DecisionTrace.tsx:2427` | Current-query and execution-owner display |
| `frontend/src/components/decision-trace/TurnHistoryPanel.tsx:16` | Label case objective versus selected turn; preserve history independence |
| `frontend/e2e/helpers/turnOracle.ts:2` | Add independent category, questions, provenance and delivery expectations |
| `frontend/e2e/live-turn-trace-continuity.spec.ts:37` | Seal current-query/category regressions and all semantic leaf expectations |
| `frontend/e2e/live-unresolved-purchase-boundary.spec.ts:25` | Existing unconditional live positive-delivery gate remains red |
| `tests/services/test_recommendation_core_brain.py:3218` | First reproduced budget-only regression; second at 3235 |
| `tests/test_decision_bitemporal_query.py:70` | Existing retroactive knowledge-time regression |
| `src/app/routers/query.py:29` | Separate opt-in FAQ RAG entry point |
| `src/app/services/hippograph.py:281` | Graph recall, not compatibility authority |
| `src/app/services/recommendation_facade.py:879` | Intelligence-stage wiring exists outside core module |
| `src/app/services/recommend_intelligence_stage.py:90` | Effective off/shadow/live mode and consumer behavior |
| `src/app/services/market_pipeline.py:20` | Batch ingestion/persistence; certify commit truth |
| `src/app/tasks/market_analysis_tasks.py:17` | Worker flags differ from request-path flags |

## 8. Git tree and checkpoints

At assessment start, the only untracked file was Claude's `SHOPSQUIRE_COMPREHENSIVE_DEEPDIVE_2026-09-11.md`. There were **no tracked implementation modifications**. The implementation and prior assessment checkpoints already exist as `2f1592f2` and `a0218c26`.

There is no implementation dirty tree to reset or clean. After this assessment, the expected additions are the two assessment documents. Test outputs remain outside the repository. Nothing should be deleted to manufacture a clean status.

Next commit sequence:

1. Audit access/temporal boundary fixes with negative authorization tests.
2. Oracle and subject-continuity repairs with both exact unit regressions and the live chair failure.
3. Scoped evidence/fit delivery, including all new manifest dependencies and tests.
4. Terminal/trace projection and semantic leaf tests.
5. Procurement durability and release evidence.

Keep assessment documents separate from implementation and from certificates. Each certificate must name commit, active profile, database dialect/head, test command, counts, skips, retries, input seed and artifact location. Do not call a component checkpoint a production release.

Do not raise size ceilings, remove failing assertions, approve sources, reset the tree or enable live market influence merely to achieve a green dashboard.

## 9. Pilot boundary and remaining decisions

A narrow internal pilot can use one tenant, reviewed electronics inventory, named operators, read-only connectors and draft-only sourcing. However, the audit-read gap must be closed before wider access. An assisted hardware recommendation promise requires the positive delivery gate; a refusal-focused demonstration does not satisfy it.

Independent source and compatibility reviewers, an inventory owner, hosted staging, deployment/support ownership, retention policy and approval-role decisions remain necessary. Their absence does not prevent fixing current scope, projection, parser representation, auth or test-oracle defects.

The next engineering milestone is therefore **secure, correctly scoped buyer delivery**, not more agents. The platform should become smarter through better evidence and typed boundaries; deterministic code should enforce contracts and authority, not accumulate another catalog of software-specific guesses.

## Sources

[^1]: Fresh local evidence: [backend scope results](C:/AI/ShopSquire-checkpoints/reassessment-brain.xml), [subsystem results](C:/AI/ShopSquire-checkpoints/reassessment-subsystems.xml), [browser results](C:/AI/ShopSquire-checkpoints/reassessment-browser.log). Test definitions: [continuity journey](C:/AI/ShopSquire/frontend/e2e/live-turn-trace-continuity.spec.ts:37), [positive delivery](C:/AI/ShopSquire/frontend/e2e/live-unresolved-purchase-boundary.spec.ts:25).
[^2]: [Alternate as-of route](C:/AI/ShopSquire/src/app/routers/decision_time_travel.py:7), [replay query](C:/AI/ShopSquire/src/app/services/decision_replay.py:28), [route composition](C:/AI/ShopSquire/src/app/bootstrap/admin_access_router_group.py:23), [MFA middleware](C:/AI/ShopSquire/src/app/security/admin_mfa.py:35). Fresh unauthenticated probe used only a decision generated by this assessment.
[^3]: [Tenant/two-time history SQL](C:/AI/ShopSquire/src/app/routers/decisions.py:206), [retroactive correction test](C:/AI/ShopSquire/tests/test_decision_bitemporal_query.py:70).
[^4]: [Prior scope restoration](C:/AI/ShopSquire/src/app/services/recommendation_core/core.py:329), [budget-only regression](C:/AI/ShopSquire/tests/services/test_recommendation_core_brain.py:3218), [candidate scope boundary](C:/AI/ShopSquire/src/app/services/case_catalog_candidates.py:205). Browser terminal/panel attachments are in the continuity trace ZIP under the evidence directory listed in section 1.
[^5]: [Trace hydration](C:/AI/ShopSquire/frontend/src/components/DecisionTrace.tsx:1035), [summary display](C:/AI/ShopSquire/frontend/src/components/DecisionTrace.tsx:2427), [history objective](C:/AI/ShopSquire/frontend/src/components/decision-trace/TurnHistoryPanel.tsx:28).
[^6]: [Steam field parser](C:/AI/ShopSquire/src/app/services/connectors/steam_requirements.py:258), [literal compiler adapter](C:/AI/ShopSquire/src/app/services/recommendation_core/workload_grounding.py:112), [compiler](C:/AI/ShopSquire/src/app/services/recommendation_core/requirement_compiler.py:41), [electronics manifest](C:/AI/ShopSquire/data/attributes/electronics.json:6).
[^7]: [Fit normalization defaults](C:/AI/ShopSquire/src/app/services/recommendation_core/fit.py:40), [shortlist fit caller](C:/AI/ShopSquire/src/app/services/recommendation_core/core.py:2514).
[^8]: [Guarded stage implementation](C:/AI/ShopSquire/src/app/services/recommendation_core/stage_runner.py:10). Direct mutation-before-error characterization returned an empty product list and an error receipt.
[^9]: [FAQ pipeline](C:/AI/ShopSquire/src/app/services/agentic_rag_pipeline.py:90), [query entry](C:/AI/ShopSquire/src/app/routers/query.py:29), [semantic retrieval](C:/AI/ShopSquire/src/app/services/semantic_search.py:42), [HippoGraph](C:/AI/ShopSquire/src/app/services/hippograph.py:281), [graph adapter](C:/AI/ShopSquire/src/app/services/graph_retrieval.py:15), [cache lifecycle](C:/AI/ShopSquire/src/app/services/temporal_invalidation.py:138).
[^10]: [Facade intelligence call](C:/AI/ShopSquire/src/app/services/recommendation_facade.py:879), [market mode](C:/AI/ShopSquire/src/app/services/recommend_intelligence_stage.py:90), [market pipeline](C:/AI/ShopSquire/src/app/services/market_pipeline.py:20), [worker gates](C:/AI/ShopSquire/src/app/tasks/market_analysis_tasks.py:17), [cohort projection](C:/AI/ShopSquire/src/app/services/hippograph_market_projection.py:76).
[^11]: [Current shared oracle](C:/AI/ShopSquire/frontend/e2e/helpers/turnOracle.ts:2), [trace test assertions](C:/AI/ShopSquire/frontend/e2e/live-turn-trace-continuity.spec.ts:65).
