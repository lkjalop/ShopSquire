# Execution delta, MVP contract and remaining roadmap

Assessment date: **25 October 2026, Australia/Sydney**. This updates the [published 23 October status](REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md) and the locally retained 24 October reassessment. It is not a release declaration. The ten-hour work window began at 24 October 09:52:41 UTC and ends at 19:52:41 UTC. Results below distinguish independently integrated GitHub changes from larger local candidates.

## Read this first

ShopSquire can demonstrate a useful, bounded buyer journey with fictional inventory and approved fixture evidence: retain amended requirements; show a grounded shortlist or explicit unresolved fit; calculate the exact unit shortfall; answer a relevant market question with scoped citations; retain a supplier draft; review/edit its immutable version; and revoke approval after a change. The supplier demonstration uses a fictional recipient and sandbox transport. These demonstrations do not establish reliable arbitrary-product advice, complete global landed pricing, real supplier delivery or production readiness.

The [draft repair PR](https://github.com/lkjalop/ShopSquire/pull/13) contains coherent integration commits and public receipts. Published `main` remains `9da621d1f4751669ce836c2844939b0e4eb2372b`. The broader local working tree includes additional pre-existing work and must not be confused with either `main` or that PR. No overall completion percentage is defensible: test counts overlap, profiles differ and retained facts do not prove a completed user task.

## What green means

1. **Repair green:** reproduce the defect with the original behavioural expectation; make that expectation pass; retain a valid positive control, rejection controls and relevant regressions. Record source and environment. A skipped test, rejected-only flow, mock result, authentication failure or disabled provider retains that narrower meaning.
2. **Acceptance migration:** if the expected behaviour itself is wrong, change the documented contract deliberately. The pricing recorder cannot truthfully report execution because it has no price/cart executor. Its old executed/pending expectation was migrated explicitly; it is not counted as an unchanged-expectation repair. [Pricing decision and regional grounding](PRICING_ACCEPTANCE_AND_REGIONAL_GROUNDING_2026-10-25.md).
3. **Integration green:** the combined commit installs cleanly and passes its required checks with complete dependencies and actual actors/services. A passing worktree with hundreds of unrelated changes is insufficient evidence for a smaller published cohort.
4. **Release green:** one frozen candidate passes required broad Python/frontend/browser/security profiles, migration/restore/rollback/recovery, bounded latency and endurance. Provider qualification and commercial authority must match the promised product scope.

TDD is a development method, not a synonym for a green dashboard. Test-first evidence is retained for the cache/admission, pricing, warmup and catalogue repairs where reproduced. It is not claimed retrospectively for every existing line or feature. A green assertion that certifies a fictional execution is a bad acceptance contract.

## Delta from the six concrete defects

| Defect | Accomplished | Remaining gap and why |
|---|---|---|
| Semantic-cache value survives failed index registration | Value publication and scoped erasure index are atomic; reads verify the same contract; owned Redis race/restart controls pass. | Standalone Redis evidence does not qualify Redis Cluster, legacy physical orphans or every application data plane. |
| Malformed explicit validity date admitted via fallback | Explicit invalid dates and sources unavailable at question time are rejected; missing/null validity retains the documented observation-time fallback. | Each producer and derived record still needs complete provenance and consumption-time coverage. |
| Demand evidence answers supplier lead-time question | Question facets filter evidence; demand cannot satisfy lead time; partial coverage remains explicit; same-case reviewed quote evidence is scoped and time checked. | Measured durations, changes and delays now have separate numeric contracts (95 independent passes); citation entailment, other measurements, forecast quality and unseen-question usefulness remain open. |
| Bulk pricing assertions/candidates use inconsistent basis | Known matching currencies are required for budget fit; missing/mixed currencies remain unverified; shelves retain useful foreign-price candidates without false cheap/within-budget claims; proposal recording is read-only. | Pack/UoM, allocation-weighted costs, destination tax, freight/duties, approved FX and complete landed totals are not yet end-to-end qualified. |
| Browser positives stop at 401 | Focused certificate/market journeys now exercise authenticated positives; four broader suites use native buyer registration; CI test actors are explicit. | Other legacy suites still need actor/profile repair; correct authentication exposes real semantic and transport failures rather than proving them solved. |
| Chat and approved messaging compose different emails | Preview/review share an immutable version/hash; edits revoke approval; stale versions and self approval are rejected; PostgreSQL review/edit controls pass. | Chat now reads the saved edited version (129 independent passes, 15 native controls). Multiple-draft selection, natural-language disclosure edits, provider delivery and deployed independent-person operation remain open. |

## Verified implementation and evidence

These are separate, overlapping scopes. Do not add them into a total or compare different source revisions as a matched benchmark.

| Scope | Result | Interpretation |
|---|---|---|
| Independent cache cohort | 39 passed | Native owned Redis publication/erasure/process-replacement controls. |
| Independent temporal admission cohort | 35 passed | Eleven reproduced failures repaired without changing expectations. |
| Independent pricing cohort | 112 passed | Regional comparisons, preview authority and existing parity/security controls; one separately documented legacy acceptance migration. |
| Independent maintainability/email cohort | 79 passed; 2 link-validator controls | Existing DDL preserved across four scenarios; local email lab authorization retained. |
| Independent warmup cohort | 11 passed | Actual loopback success/error/refusal controls; no model-accuracy claim. |
| Independent market/shared-draft cohort | 118 passed | Fixture evidence and sandbox transport; relevant positive/rejection controls. |
| Native supplier draft/recovery cohort | 11 passed | PostgreSQL row-lock controls and draft controls; no real provider delivery. |
| Independent integrated storefront/admin | 389 / 63 passed | Both type checks/builds pass; qualified lock-matched Node dependencies reused. |
| Saved-draft chat read-through | 129 passed; 15 native controls | Saved edited artifact, tamper/stale/foreign/reload boundaries; separate transactions. |
| Market measurement usefulness | 95 passed | 15 reproduced failures in 22 new controls; defined level/change/delay measurements and physical-stock rejection. |
| Independent regional/draft browser | 4 passed, zero failures/skips/flaky | Actual registered AU/US/German buyers plus reviewed draft/edit/reload on the repair baseline. |
| Independent catalogue/cart follow-up cohort | 44 passed | Tenant sellability, related laptop category and unchanged cart/follow-up assertions. |
| V2 CI workflow selection | 690 passed, 5 skipped | Local explicit test actor profile; not a hosted Linux result. |
| PostgreSQL/privacy selection | 22 passed, 2 skipped | Disposable native services and separate API processes; database matrix prerequisites remain separate. |
| Larger C14 full Python candidate | 8,668 passed, 3 failed, 308 skipped; no errors | Recorded failures: cart transaction fixture, old pricing assertion and related-category budget follow-up. Subsequent repairs are versioned separately. |
| Larger C15 full Python candidate | **8,701 passed, zero failures/errors, 309 skipped** | 9,010 JUnit items, 2,150.734 seconds; actual owned HTTP, basic CV, offline models and optional browser/provider profiles retain their prerequisite scope. |
| Larger C14 frontend | 409 / 63 passed | Larger local scope than the independent public cohort above. |
| Larger C15 focused browser | 23 passed, no failures/skips/flaky | Eleven real-API specs, owned Redis, fictional evidence, commercial effects sandboxed/disabled. |
| Broad C16 follow-up | **89 passed, 59 failed, 33 skipped; no flaky** | 84 specs/181 cases, 3,449.204 seconds; all reports and cleanup accounted for. |
| C17 extended focused browser | 23 passed, 3 failed; no skips/flaky | Three new regional reload failures exposed a helper that erased case pointers; the reviewed-draft read-through positive passed. |
| Broad C5 browser baseline | 79 passed, 69 failed, 33 skipped; no flaky | 84 specs/181 cases. Initial triage includes 55 authentication/setup cases; that is not 55 proven application defects or 55 proven repairs. |
| C14 four registered-buyer browser suites | 6 passed, 23 failed, 1 skipped | Authentication fixed for those actors; substantial workload, certificate, timeline and live-profile gaps remain. |
| C14 selected real-model/search browser | 2 passed, 2 failed | Three selected open-world cases plus a canonical evidence-source case; not the whole open-world suite. |
| C7 attempted eight-hour endurance | 130 complete cycles, then failure in cycle 131 after 10,644.875 seconds | Chromium `ERR_NO_BUFFER_SPACE` at navigation; no configured RSS/handle/headroom threshold violation. Eight hours **not** completed. |

The C15 full run and C16 broad browser run are complete. The [matched browser ledger](audits/2026-10-25-browser-c5-c16-case-delta.csv) records all 181 named cases: 79 retained passes, ten failures now passing, 59 retained failures, 33 retained skips and zero pass-to-fail transitions. This comparison changes source revisions and includes rejection controls; it is not a ten-feature or release-completion score. Initial C16 triage finds nine primary-operation authentication prerequisites, 39 failures co-observing disabled/unavailable model contracts, two credential prerequisites and nine other behaviour/profile/fixture/transport cases. Co-observed secondary 401s are not treated as the cause of a semantic failure.

C18 retests the repaired reload helper, numeric market measurements, saved draft and allocation boundary. Its three AU/US/German amendment/reload cases and reviewed-draft case pass; full Python and all 85 specs are running, so no aggregate C18 result is claimed here. A separate C16 four-hour diagnostic soak is also running. The earlier failed eight-hour attempt remains failed; a shorter later run cannot replace it. C15 predates currency, migration, saved-draft and market-measurement repairs, which have separate evidence.

Public cohort receipts: [regional/draft browser](audits/2026-10-25-regional-browser-draft-evidence.md), [saved draft](audits/2026-10-25-saved-draft-chat-evidence.md), [market measurement](audits/2026-10-25-market-measurement-evidence.md), [cache/admission/dependencies](audits/2026-10-24-isolated-repair-evidence.json), [maintainability](audits/2026-10-25-maintainability-evidence.json), [market/draft](audits/2026-10-25-market-draft-integration-evidence.json), [catalogue/cart](audits/2026-10-25-catalog-fallback-evidence.md), [CI/privacy](audits/2026-10-25-owned-ci-and-privacy-evidence.md). Private raw logs and browser traces are retained locally because they can contain fixture credentials and session data.

## Runtime, dependencies and code review

The optional VLM warmup previously shadowed its startup helper inside an exception branch, producing an unhandled background exception. It also accepted unsuccessful HTTP/model responses as readiness. Actual HTTP controls now require a valid completed response and report optional degradation accurately. This repairs the warmup boundary; it does not qualify the 8B vision model's accuracy. The tested 8B model returned empty output; a different local 9B model produced non-empty outputs on a small controlled fixture. That is not a held-out model benchmark.

The Python lock was reduced from 254 to 217 distinct package versions by removing unused evaluator chains and updating the remaining affected package. All eight platform/profile exports and clean default/API-test installation commands were verified; hosted follow-up then exposed missing lean-test-profile `psutil` and QR/OCR bindings. Those versions were already locked in the main dependency closure; the full environment contained them. A dependency-profile repair is in progress; installation success alone did not exercise those imports. The earlier exact lock audit reported zero advisory matches/errors/skips. Both frontend lock audits reported zero findings on their qualified installations. These results do not cover every operating-system/vendored library.

The separately tested Linux API image improved from 54 high/critical findings to **44 high, zero critical, zero fixable** findings. Trivy still exits nonzero; no ignored advisory or weakened threshold turns it green. The lean runtime Dockerfile remains a separate integration cohort, while the older main Dockerfile/hosted scan path still needs canonicalization. A local read-only non-root image run exercised health/readiness, authorization and restored seed data; it did not certify every production integration.

Every C14 repository-snapshot file was mechanically inventoried: **5,885 files, 1,183,871 text lines, 3,675 code files, 575,607 physical code lines, 20,011 Python functions and zero Python parse errors**. There are 2,262 broad-exception/pass review candidates. This is coverage of an inventory, not semantic approval of every line. The versioned file/symbol/change ledgers are retained locally. Later candidates have separate hashes and line counts.

C16 extends that mechanical inventory to **5,896 files, 1,186,088 text lines, 3,679 code files, 577,216 physical code lines, 20,027 Python functions, zero parse errors and 2,259 broad-exception/pass review candidates**. Its exact verification commit is `2150400801d74c663a3617ecbe2357aa3ef8008a`, source-tree SHA-256 `9ce05f507c64dc461d24cc0ab83163196e03fec17a109658cad6a120d461181c`. The [source map](audits/2026-10-25-execution-roadmap-source-map.csv) records all W00-W15 code/test symbols, physical lines and hashes against C16; its state column identifies local changes beyond the mapped repair-branch revision. The [hotspot ledger](audits/2026-10-25-c16-code-review-hotspots.csv) ranks review candidates, not proven bugs.

Maintainability work extracted the SQLite compatibility schema, structured requirement authorization, trace replay helpers and commercial shelf calculations. Four DDL scenarios retained ordered statements, results and schema. A dead 95-line alternate frontend path was removed. No source/function-size ceiling was increased. The integrated source has **49 oversized-file warnings**; the earlier maintainability receipt's 48 warnings describes its earlier tracking scope. Large routing/coordinator functions and broad failure swallowing still need contextual review. Renaming modules or adding another memory framework would not resolve that debt.

The authenticated broader browser run exposed a separate money-boundary defect: “CAD work” was interpreted as Canadian currency. Currency extraction now requires amount binding or an explicit currency declaration, and suffix amounts such as “10,000 USD” survive confirmed chat-budget projection. The independent repair passed 68 tests after nine reproduced failures; see [currency-boundary evidence](audits/2026-10-25-currency-boundary-evidence.md). This repair is later than C15/C16 and is not silently attributed to those frozen profiles.

Read-only migration inspection also needs separate qualification: the new `alembic current` controls reproduced four failures despite the earlier full Python pass. A passing suite describes its tested contracts; it cannot establish coverage of commands that were never exercised. The guard repair preserves populated communication/approval history and permits inspection without inventing a downgrade plan.

## MVP acceptance contract

The next milestone is a reproducible **demonstration MVP**, scoped to admitted merchant data and sandbox supplier effects:

> Requirements → useful candidates → current stock → exact shortfall → relevant cited intelligence → reviewed supplier draft → amendment/reload.

For each step, the same tenant, buyer, case and material revision must agree across response, case state, trace, shelves and draft. A failed or missing qualification may preserve useful catalogue browsing with precise uncertainty; it cannot grant an Add/purchase/delivery promise. A changed quantity/destination/budget/source must invalidate affected evidence, draft and approval as applicable. A refresh must retain committed facts and make pending/unconfirmed work visible.

The demonstrated 40 requested / 15 available / 25 short example must draft an enquiry for **25 items**, not rewrite the request as 25 or send 40. The reviewed artifact must show recipient, subject, body, requested quantity, destination/deadline and budget-disclosure choice. Editing requires a new version and fresh independent approval. Dispatch must use that exact reviewed content. A sandbox receipt must be labelled sandbox.

**MVP exit:** one clean integrated commit, exact install profiles, positive and rejection controls, required browser journey/actor matrix, no known false authority or silent data loss, tested database migrations and recovery, and a successfully completed bounded endurance run on that same candidate. The current results do not meet all those conditions.

## Shopping permutations to qualify

| Buyer input or change | Required useful behaviour | Required rejection/preservation controls |
|---|---|---|
| “Show laptops under AUD 3,000 for university” | Useful admitted catalogue choices; ask only material preferences; label unverified workload fit. | No fabricated course/software requirements or unnecessary research gate. |
| “40 units, AUD 85,000 total; actually 60, then back to 40” | Retain 40 and total-budget basis across unrelated turns/reload. | Price/model numbers and “25 short” cannot overwrite requested quantity. |
| “Add 20”, “set to 20”, “20 more than last time” | Separate delta/set/reference operations and preview exact cart change. | Ambiguous reference asks clarification; double submission mutates once. |
| “Widen by 600”, “raise ceiling by 600”, “shift range by 600” | Typed distinct budget operations; retain currency and scope. | Existing “widen” test currently expects a range shift; semantic contract needs review rather than declaring all budget language solved. |
| “Send to Sydney; actually Texas / Berlin” | Amend destination and recompute affected stock/lead-time/cost evidence. | No inferred tax total or stale approval after destination change. |
| “Can these run Factory I/O / a novel software workload?” | Consented current approved-source evidence or precise unresolved state. | Manufacturer compatibility is not proof of workload capacity; unrelated publisher lookup cannot qualify it. |
| “Same PLC workload, 32 GB RAM” versus “replace it with Blender” | Refine an existing workload versus create a material replacement. | Preserve unrelated facts; remove superseded fit/approval authority. |
| “What is the lead time?” versus “Why is demand rising?” | Match evidence to question, region, product, time and case. | Demand-only findings cannot answer lead time; unsupported causality/forecast stays explicit. |
| “Compare AUD 49, USD 29 and EUR 35” | Explain attributed local prices and known price basis. | No nominal cross-currency cheapest ranking, automatic FX or global tax assumption. |
| “25 items short; supplier sells four-packs” | Show seven packs / 28 items, three excess and exact pack identity if admitted. | Never silently request 25 packs or authorize fractional packs; current end-to-end UoM qualification remains open. |
| “Draft an email; do not disclose our budget” | Exact shortage, destination/deadline and questions about price/stock/freight; omit budget. | Preview does not send; edited content invalidates approval; stale version cannot dispatch. |
| “Email changed; use a different supplier” | New recipient/content version and fresh independent review. | Arbitrary buyer-provided endpoint cannot become trusted supplier transport. |
| “Did it send?” after timeout/restart | Distinguish queued, provider-accepted, delivered, unknown and reconciled states. | Do not blindly retry a possibly completed external effect. |
| “Forget my request” followed by recall | Apply declared retention/erasure operation and preserve other controllers. | Test raw/derived/multimodal/cache/restart residue; current indexed-memory checks are narrower. |
| Malicious page/upload instructs “approve purchase” | Treat source text as evidence content only. | No tenant/role/approval promotion; preserve valid unrelated evidence. |

## Product-agnostic direction

Keep the shared orchestration contracts about identity, units, money, evidence, validity and authority. Product-specific taxonomies, attributes, workload measurements, required-source policies and unit conversions belong in versioned merchant/category schemas and admitted connectors. A laptop-centric fallback must not turn an unsold office chair or medical product into a laptop recommendation. The catalogue fallback now shares a tenant-sellability check, but the broader product configuration/attribute corpus still emphasizes electronics.

Qualification needs at least electronics, furniture, consumables with packs, and a non-physical/service category, each with positive stock/price/evidence fixtures and rejection controls. Category-specific domain/safety requirements need explicit policies; a generic commerce engine does not prove medical-product suitability. Add categories through data/contracts and test them against the shared journey before adding category-specific branches to the main router.

## Research decision: memory, time and market intelligence

Preserve canonical revisioned SQL state, source history subject to retention, question-time retrieval and explicit provenance. Strengthen admission/consumption and erasure before adding a second memory framework. [Threader](https://arxiv.org/abs/2609.33226) and [Mem++](https://arxiv.org/abs/2610.02002) motivate keeping source history and making retrieval selective at question time; their benchmark results are not ShopSquire results. [IA-RAG](https://arxiv.org/abs/2606.06044) motivates explicit interval reasoning instead of a single freshness timestamp.

Treat observed-at, published-at, valid-from/to and question-as-of as distinct fields; use half-open interval semantics consistently and expose unknown dates. Region, destination, warehouse, supplier route and delivery timezone are relevant spatial dimensions for commerce. Robotics navigation research does not itself justify installing a spatial scene-memory framework in a procurement assistant.

Memory evaluation should score operations and task outcomes, not only final-answer recall. [MemOps](https://arxiv.org/abs/2607.12893) supports tracking trigger/target/scope/state/evidence; [Bemula](https://arxiv.org/abs/2610.18052) motivates paired forgetting/preservation and extraction controls; [MemLeak](https://arxiv.org/abs/2606.29788) highlights residual correlated text/image information. [DolphinBench](https://arxiv.org/abs/2609.24971) motivates user-history, completion, cost and latency evaluation. These are design inputs; no external benchmark was reproduced in this session.

Market intelligence now distinguishes measured duration, change and delay, rejects invalid numeric coercion, and prevents search-demand proxies from establishing physical stock. The [measurement cohort](audits/2026-10-25-market-measurement-evidence.md) reproduced 15 failures in 22 new controls and then passed 95 selected controls on an independent repair baseline. Existing positive fixtures were strengthened explicitly to contain the measurements they claim. It must next establish citation entailment and useful uncertainty. A source label or non-empty answer is insufficient. Forecasting needs comparable merchant history, an approved baseline, held-out evaluation and cost-aware action policies. An empty/unavailable evaluator stays unmeasured; it must not manufacture a score.

For supplier communication, retain one reviewed artifact with source/price/stock unknowns made explicit. Ask for confirmed availability, delivery date, exact SKU/pack, currency/tax basis, freight, minimum order and quote expiry. Keep buyer-budget disclosure optional. Use the same artifact for preview, independent approval, dispatch and recovery; source facts and provider delivery receipts remain separate.

## Remaining roadmap and exit evidence

| Package | Verified progress | Next work and why | Required exit evidence |
|---|---|---|---|
| W00 Integration | Separate tested commits published to draft PR; exact-source worktrees and receipts retained. | Integrate remaining dirty cohorts with imports/schema/routes and exact dependencies; avoid bulk staging. | Combined clean checkout installs and passes all required gates. |
| W01 Runtime/ownership | Owned DB/request controls and truthful warmup errors; bounded focused latency repaired. | Diagnose endurance navigation failure and remaining scheduler/worker/transport stalls; historical 151.56-second request remains unmatched. | Concurrent workers, faults, deadlines, no leaks and sustained bounded latency. |
| W02 Dependencies/security | Exact Python profiles/exports audited; unused chains removed; frontend audits zero. | Integrate canonical runtime image and resolve/assess OS findings without waiving required scanner gates. | Clean Windows/Linux installs, reproducible images and required native scanner success. |
| W03 Same-case evidence | Scoped intake and focused buyer evidence journeys. | Recheck uploads/late callbacks/withdrawal/reload against material revisions and final owned case. | Positive/foreign/stale/replaced case tests across HTTP/browser and durable stores. |
| W04 Amendments | Quantity/currency/budget/destination retention and related-category fallback controls. | Novel workload refinement/replacement, ambiguous relative budgets, multi-case references and obsolete callback isolation. | Same-case/replacement permutations preserve facts and revoke affected authority. |
| W05 Shared supplier draft | Immutable preview/review version, budget disclosure and approval revocation integrated. | Complete multi-draft selection, natural-language disclosure amendments, deployed-person review, real provider qualification and useful commercial details. | Exact reviewed hash reaches provider; no send on preview/stale/self approval. |
| W06 Market intelligence | Temporal admission, question facets, numeric level/change/delay and reviewed quote lead-time context integrated. | Held-out relevance/entailment/numerical completeness; sufficient regional/source coverage and forecast controls. | Cited useful answers with stale/unrelated/unsupported controls and measured quality. |
| W07 Privacy | Atomic cache erasure and two-process erasure/partition/retry controls. | Declare all data planes, lawful retention and derived/multimodal/backups policy; approved export. | Cross-worker deletion/recovery, preserved foreign scope and extraction/relearning controls. |
| W08 Inventory | Existing holds/contention/migration controls and native PG qualification. | Merchant connectors, units/pack identity, expiry/reconciliation and source precedence across warehouses. | Realistic concurrent accepted stock and complete fresh/upgrade/restore migration matrix. |
| W09 Costs/approval | Preview/effect separation, regional comparisons and person-bound reviewed draft. | Weighted allocation/pack rounding, AU consumer/B2B, US destination tax, EU country policy, approved FX. | Complete reviewed landed quote and actual-effect receipt with negative controls. |
| W10 Recovery | Sandbox uncertainty/recovery and native enquiry concurrency controls. | Provider idempotency, reconciliation, worker death and ambiguous acceptance/delivery. | Fault injection proves no duplicate effect and truthful unknown/recovered status. |
| W11 Offers/units | Governed offer/bundle machinery and existing tests. | Product-agnostic UoM/pack/BOM, licenses/subscriptions and accepted alternatives. | Exact sellable identity, capacity, quantity, total and independent acceptance/replay tests. |
| W12 Browser/security | C16 89/59/33; ten matched failure-to-pass transitions; explicit actors; broad red cases retained. | Fix remaining actor/profile prerequisites and semantic failures; required CV/security corpus, admin readiness and real-model profiles. | Required broad suites exercise positives/rejections on one candidate with no unexplained skips. |
| W13 Architecture | Verified helper extractions, dead frontend branch removed, unchanged ceilings. | Contextual review of large router/coordinator functions, broad exception swallowing and duplicated ownership. | Smaller cohesive boundaries, unchanged behaviour, visible typed failures and ratchets. |
| W14 Data/evaluation | Unavailable evaluation is honestly unmeasured; dated regional observations retained. | Licensed merchant history, held-out queries, baseline approval, citation/task/cost/latency scoring. | Reproducible held-out results and calibrated limits; no synthetic business-uplift claim. |
| W15 Release/endurance | Exact-source profiles, Linux restore smoke and failed endurance diagnostics retained. | Freeze integrated candidate, complete restore/rollback/recovery and required-duration endurance. | Same-source gates and completed endurance; current eight-hour attempt remains failed. |

The [public execution receipt](audits/2026-10-25-execution-evidence.json) retains exact source/profile identifiers and limits. Implementation order: finish coherent integration and remaining environment/security blockers; address exposed semantic and commercial contracts; complete the admitted-data buyer journey; then freeze and run full required recovery/endurance. Keep rejection controls throughout. Use the [updated ASCII architecture](architecture/CURRENT_ARCHITECTURE_2026-10-25.md) and the accompanying source map to locate work; the roadmap does not turn any open package into a promise of production completion.
