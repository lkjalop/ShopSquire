# Independent pilot review — 2026-09-09

## Verdict and limits

The assessment identifies genuine progress in compiler boundaries and procurement controls. It does not establish production readiness or complete buyer delivery. Its strongest overstatement is that a derivation ledger is the sole missing piece: a ledger records authority and provenance; it cannot establish CPU/GPU equivalence or complete OS compatibility by itself.

This review inspected implementation boundaries, reran procurement/ranking/size tests, and ran a fresh real-browser query against the existing local server. It did not approve sources, confirm a cart, draft or send supplier messages, restart services, or perform hosted/PostgreSQL certification. Historical claims such as full-suite coverage and crash causation were not independently reproduced. Test counts and pure-module design are not security certificates.

## Independently checked findings

Fresh isolated rerun of `tests/services/fulfillment`: **348 passed, 0 failures/errors/skips**, 33.108 seconds (JUnit: `C:/AI/ShopSquire-checkpoints/pilot-review-20260909/procurement.xml`). This independently certifies that selected directory, not the report's differently scoped 372-test count. The combined ranking/size run reproduced two ranking failures and one guard failure. The complete platform suite was not rerun.

| Finding | Assessment |
|---|---|
| Test flag writer rejects tracked config | Confirmed: `tests/utils.py:10` rejects absent/production paths before writing. This is a test helper, not universal filesystem protection. |
| Router uses a closed lane schema | Confirmed: `recommendation_core/router_model_call.py:70` imports LANES and constrains the output schema. Historical chair success was not rerun in this browser session. |
| Compiler refuses unapproved derivation | Confirmed: `recommendation_core/requirement_compiler.py:84`; preserve this boundary. |
| Literal CPU/GPU/OS evidence exists | Confirmed: `connectors/workload_evidence.py:55` retains observations and spans; `research_outcome.py:189` projects them. Observation is not validated compatibility. |
| FSM has 55 transitions, 9 agent-only, 14 human-only | Confirmed by importing and counting TRANSITIONS in the running checkout. |
| Ranking experiment is disconnected | Both integration tests fail again. The legacy intelligence stage contains ranking_nudge wiring; recommendation_core has no such references. Repair or explicitly retire the experiment, not its assertions alone. |
| Source-size guard remains red | Confirmed: chat.py 5787 > 5049; fulfillment_cases.py 2574 > 2447; shopping_cases.py 2397 > 2073. Do not raise ceilings. |
| Only one source review is pending | Incorrect if applied to registrations: 8 pending, 12 approved registration states; separately, one independent_review block is pending and 19 have no block. These are different authority axes, not 19 approvals. |
| Resident model removes GPU crash risk | Not established. Residency reduces cold-load exposure, not driver, VRAM-pressure or thermal risk. |
| Drafting is read-only | Incorrect. Drafting persists workflow state, although it need not dispatch anything. |

## Procurement boundary cautions

`fulfillment/domain.py` defines actors and transitions; `user_id` alone does not enforce separation of duties. Distinct-person controls require authenticated tenant-scoped principals, immutable requester and approval identities, delegation rules, version/content-hash binding and enforcement at dispatch—not merely an inequality on request-provided IDs.

`fulfillment/external_comms.py:360` checks stale human approval. `:378` autonomous send assumes prior guards have run. The shared transport path additionally checks outbound integrity and fails closed when scanning is unavailable. Keep these controls, but add direct-boundary and edit-between-approval-and-send tests before enabling autonomy. A pure FSM is useful, not proof that every caller correctly applies every guard.

`fulfillment_cases.py` confirm-cart rereads availability and records a buyer source-quantity override. Verify unreadable stock remains unknown rather than being narrated as proven supplier shortage. Prove stock shortage separately from affordability, and test idempotency under database concurrency, not only sequential replays.

## Fresh browser assessment

Artifacts: `C:/AI/ShopSquire-checkpoints/pilot-review-20260909/trace-assessment.json` and `.png`.

Fresh prompt: **Could a laptop under AUD 2,500 run PRAGMATA at 1080p?** Chromium GPU disabled; no retries, no cart or approval clicks. Opened all 15 Decision Trace panels. The harness reported no browser/API errors, but that is not a semantic pass.

| Panel | Observed |
|---|---|
| Summary | Missing query, intent, timing and tools; legacy/unrecorded owner. |
| Events | Interpretation and open-world discovery completion events present. |
| Execution | New trace says it predates the typed contract. Defect. |
| Research | PRAGMATA, 2 accepted claims, partial requirements, blocked catalog. Older discovery/interpretation statements remain alongside newer evidence. |
| Why | No ranked reasons; does not explain the actual missing compatibility predicates. |
| Intent | Says no signals despite explicit budget and requested laptop. |
| Memory | No recorded cache/memory events; absence is not a failure by itself. |
| Complexity | Counts `rag` inside PRAGMATA as a technical term; misleading signal. |
| Evidence | No evidence legs despite the research panel's provider evidence; distinguish a scoped recall view from total evidence. |
| Multimodal | No image/voice events, appropriate for this text-only request. |
| Security | No analysis available; does not certify pasted-URL handling. |
| Market | No scoped projection; no product set to certify here. |
| Procurement | No sourcing activity, appropriate; loading text remains visible. |
| Audit | No revisioned decision run; local SQLite WORM chain not populated. |
| Raw | Null input and empty replay tool list despite research events. |

External discovery really ran: receipts include three discovery dispatches and responding engines. The buyer still receives no qualified shelf. This run therefore proves execution, not successful end-to-end recommendations.

The screenshot still labels a 4 GB GPU threshold as verified official. Current source rejects unapproved derived claims. Crucially, API PID 37488 started **7 September at 21:00**, before the later compiler edits; do not treat this browser run as certification of those edits. Establish build identity/reload behavior, restart through the owned launcher, and rerun before attributing the discrepancy solely to current source code.

The architecture alternatives now render, but the UI says no form factor was specified even though the buyer explicitly asked for a laptop. Rendering is progress; correct applicability is not yet proven. The narrow split chat/review layout also remains difficult to read.

## Ordered roadmap and acceptance gates

1. **Establish the tested build.** Recoverable dependency-complete checkpoint; record commit plus dirty patch identity, active tenant/database/profile and listener ownership. Verify clean checkout, then restart and repeat the browser test. No reset or deletion.
2. **Finish typed compatibility and evidence authority.** Bind source and claims to software/version/platform and manifest revision. CPU/GPU alternatives, OS/architecture/API and storage requirements need typed evaluation against exact SKU data. Unknown stays unknown. Derived rules need version, input claim IDs, reviewer/scope and expiry; never infer GPU equivalence from VRAM alone.
3. **Reconcile terminal and trace projection.** Same operation/revision and evidence IDs across every panel. New operations cannot claim to predate the execution contract. Explicit laptop requests cannot receive an unspecified-form-factor prompt. Distinguish absent instrumentation from not-applicable data.
4. **Seal buyer delivery and procurement seams.** Complete accepted compatibility plus matching permitted stock must produce a nonempty qualified shelf. Partial/held/incompatible evidence must produce honest restrictions. Separate budget-only, stock-only and combined shortages; explicit sourcing confirmation produces a draft, never a send. Use isolated sandbox fixtures and a transport spy/outbox audit to prove dispatch absence. Test stale approvals, duplicate/concurrent confirmation and same-person approval rejection.
5. **Publish category manifests.** Add reviewed tenant/product/relationship/use/unit/operator/completeness manifests and immutable database revisions. Coffee packaging, groceries and pharmacy fixtures must not inherit hardware completeness. Fixtures are not regulatory or production approval. Core orchestration stays category-agnostic.
6. **Restore or retire the ranking experiment deliberately.** Decide whether its policy-compatible effect belongs in V2. If retained, test treatment/control plus scope/authority invariants. If retired, remove the console promise and audit consumers before deleting legacy code.
7. **Extract only behind characterization gates.** Terminal projection first, then research orchestration, within existing owned modules. Keep size ceilings and one-core/one-terminal guarantees unchanged.
8. **Certify deployment.** Failure injection, no-retry rotating live identities and multi-turn tests, clean PostgreSQL concurrency/migrations, hosted clean machine, independent source review and principal separation. Supplier integrations remain sandbox-only until authorized credentials and operational controls exist.

## Dirty tree

Before adding this review: **20 modified tracked files and 9 untracked entries**. The untracked requirement_scope module and its tests are dependencies, not disposable artifacts. This document makes 10 untracked entries. Keep runtime logs, databases, screenshots and credentials outside source commits. No implementation files were changed, committed, deleted or pushed during this assessment.
